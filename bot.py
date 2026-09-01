import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
import re
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from io import BytesIO
from PIL import Image

# === إعداد نظام المراقبة ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات النظام وتغييرات البيئة ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات Render.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# إعدادات الأمان الخاصة بالذكاء الاصطناعي
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# === تهيئة البوت والسيرفر ===
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# === إدارة قاعدة البيانات ===
def get_db_connection():
    return sqlite3.connect('tradeguard.db', check_same_thread=False, timeout=10)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, 
                  is_sub INTEGER, start_date TEXT, end_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, lang, trials, is_sub, start_date, end_date FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", (user_id, 'ar', 0, 0, '', ''))
        conn.commit()
        user = (user_id, 'ar', 0, 0, '', '')
    conn.close()
    return user

def update_user(user_id, field, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

# === النصوص وقوالب اللغات ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI 📈\nمستشارك الذكي لتحليل الشارتات المالية والأسواق.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي صورة شارت مالي للتحليل الآن.",
        'wait': '⏳ جاري تحليل الشارت بدقة عالية... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في تحليل الشارتات، يرجى الاشتراك للحصول على وصول غير محدود.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المجانية المستعلمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد تحويل المبلغ، أرسل صورة الإشعار و الـ ID الخاص بك (`{user_id}`) لإدارة البوت لتفعيل حسابك فوراً:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك الآن فعال ولغاية تاريخ: `{end_date}`.\nيمكنك الآن إرسال عدد غير محدود من الشارتات للتحليل. نتمنى لك تداولاً موفقاً! 📈',
        'prompt': """أنت نظام التحليل الفني الاحترافي الصارم TradeGuard AI.
إذا لم تكن الصورة المرسلة عبارة عن شارت تداول مالي أو رسم بياني لشموع يابانية، أجب فقط بالنص التالي بدون زيادة:
"⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية."

إذا كانت الصورة لشارت تداول، قم بإجراء تحليل فني دقيق واحترافي، وقدم النتيجة حصراً بالصيغة الهيكلية التالية، وبدون كتابة أي تفكير داخلي أو ملاحظات مسودة أو مقدمات أو خاتمات:

1. الاتجاه العام:
(شرح دقيق واحترافي للاتجاه الحالي وإطار الشمعة والتذبذب إن وجد)

2. أقوى المقاومات:
- المقاومة الأولى (السعر): (السبب الفني)
- المقاومة الثانية (السعر): (السبب الفني)
- المقاومة الثالثة (السعر): (السبب الفني)

3. أقوى الدعوم:
- الدعم الأول (السعر): (السبب الفني)
- الدعم الثاني (السعر): (السبب الفني)
- الدعم الثالث (السعر): (السبب الفني)

4. نسبة حدوث التوقع:
- (نسبة مئوية % واضحة بناءً على المؤشرات والشموع)

5. الخلاصة والنصيحة:
القرار الاستثماري: (شراء / بيع / انتظار) مع الشرح المباشر.
- إيقاف الخسارة (SL): (مستوى السعر المحدد)
- أهداف البيع/الشراء (TP): (الهدف الأول والهدف الثاني)
- تنبيه: (ملاحظة إدارة مخاطر تحذيرية حاسمة)"""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nYour AI Assistant for Financial & Chart Analysis.\n\nChoose your language / اختر لغتك:",
        'lang_selected': "English language selected successfully ✅\nSend any chart image now for analysis.",
        'wait': '⏳ Analyzing chart with high precision... Please wait.',
        'no_trials': '⚠️ Sorry, you have used all your free trials (3/3).\n\nPlease subscribe to continue getting unlimited chart analysis.',
        'account': '👤 **Your Account Details**\n\n🆔 User ID: `{user_id}`\n📊 Free Trials Used: {trials}/3\n💎 Subscription Status: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Subscription Plans**\n\n🔹 **10-Day Plan:** $20 (USDT)\n🔹 **Monthly Plan (30 Days):** $50 (USDT)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 After transfer, send transfer proof & your User ID (`{user_id}`) to Admin to activate:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Your Subscription is Active!**\n\nYour subscription is now active until: `{end_date}`.\nYou can now send unlimited charts for analysis. Happy trading! 📈',
        'prompt': """You are TradeGuard AI, a strict professional financial chart analyst.
If the provided image is not a financial candlestick chart, reply ONLY with:
"⚠️ Sorry, this image is not a candlestick chart."

If valid, perform a precise technical analysis and return ONLY the structured report below, with NO internal thought process, draft notes, or self-corrections:

1. Market Trend:
(Detailed explanation of current trend and timeframe context)

2. Key Resistances:
- First Resistance (Level): (Technical reason)
- Second Resistance (Level): (Technical reason)
- Third Resistance (Level): (Technical reason)

3. Key Supports:
- First Support (Level): (Technical reason)
- Second Support (Level): (Technical reason)
- Third Support (Level): (Technical reason)

4. Probability of Success:
- (Clear percentage % based on chart patterns)

5. Conclusion & Advice:
Investment Decision: (Buy / Sell / Wait) with concise reasoning.
- Stop Loss (SL): (Price level)
- Take Profit (TP): (Target 1 & Target 2)
- Risk Warning: (Crucial management warning)"""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

# === تنظيف مخرجات التحليل الفني من أفكار الذكاء الاصطناعي الجانبية ===
def clean_analysis_output(text):
    if not text:
        return text
    patterns_to_remove = [
        r'\(Self-Correction.*?\):?',
        r'Strict and professional\?.*?\n',
        r'Order followed\?.*?\n',
        r'No fluff\?.*?\n',
        r'Max 350 words\?.*?\n',
        r'Numbers accurate\?.*?\n',
        r'Wait, looking closer.*?\n',
        r'Final Polish.*?\n',
        r'Resulting analysis:?\n'
    ]
    cleaned = text
    for pattern in patterns_to_remove:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()

# === معالج إرسال النصوص الطويلة وتخطي أخطاء تليجرام ===
def safe_send_long_text(chat_id, status_message_id, full_text):
    full_text = clean_analysis_output(full_text)
    chunk_size = 3800
    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
    
    for index, chunk in enumerate(chunks):
        try:
            if index == 0:
                bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode='Markdown')
            else:
                bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
        except telebot.apihelper.ApiTelegramException as e:
            error_msg = str(e).lower()
            if "can't parse entities" in error_msg or "400" in error_msg or "bad request" in error_msg:
                try:
                    if index == 0:
                        bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode=None)
                    else:
                        bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)
                except Exception as inner_e:
                    logger.error(f"Fallback sending failed: {inner_e}")
            else:
                logger.error(f"Telegram API Exception: {e}")

# === استكشاف المحركات والتحليل التلقائي ===
def generate_chart_analysis(prompt, img):
    available_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        logger.info(f"Discovered models for API Key: {available_models}")
    except Exception as e:
        logger.error(f"Error fetching models list: {e}")
        available_models = ['models/gemini-1.5-flash', 'models/gemini-2.0-flash', 'gemini-1.5-flash']

    if not available_models:
        raise Exception("لم يتم العثور على أي نموذج ذكاء اصطناعي متاح لمفتاح API الخاص بك.")

    last_exception = None
    for model_name in available_models:
        try:
            logger.info(f"Attempting analysis with model: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, img], safety_settings=safety_settings)
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            last_exception = e
            continue

    raise last_exception or Exception("تعذر الوصول لأي من محركات الذكاء الاصطناعي.")

# === أوامر البوت والأحداث ===

@bot.message_handler(commands=['start'])
def send_welcome(message):
    get_user(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"), 
               InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    bot.reply_to(message, TEXTS['ar']['welcome'], reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_language(call):
    lang = call.data.split('_')[1]
    update_user(call.message.chat.id, 'lang', lang)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, TEXTS[lang]['lang_selected'], reply_markup=get_main_keyboard(lang))

# معالج معلومات الحساب (يعمل بالعربية والإنجليزية والأمر)
@bot.message_handler(func=lambda message: (message.text and ("حسابي" in message.text or "Account" in message.text or message.text == '/my_account')))
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, _, end_date = user[1], user[2], user[3], user[4], user[5]
    if lang not in TEXTS: lang = 'ar'
    sub_status = TEXTS[lang]['active'].format(end=end_date) if is_sub else TEXTS[lang]['inactive']
    msg = TEXTS[lang]['account'].format(user_id=message.chat.id, trials=trials, sub_status=sub_status)
    bot.reply_to(message, msg, parse_mode='Markdown')

# معالج الاشتراك (تم إصلاحه ليعرض البيانات والمحفظة دائماً)
@bot.message_handler(func=lambda message: (message.text and ("الاشتراك" in message.text or "Subscription" in message.text or message.text == '/subscribe')))
def sub_info(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    bot.reply_to(message, TEXTS[lang]['sub_info'].format(user_id=message.chat.id), parse_mode='Markdown')

# أمر تفعيل الاشتراك من الآدمن مع إرسال إشعار فوري للمستخدم
@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return 
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ صيغة الأمر الصحيحة:\n`/activate <User_ID> <Days>`\nمثال: `/activate 123456789 30`", parse_mode='Markdown')
            return

        target_user_id = int(parts[1])
        days = int(parts[2])
        
        tz = pytz.timezone('Asia/Riyadh')
        start_date = datetime.datetime.now(tz)
        end_date = start_date + datetime.timedelta(days=days)
        
        target_user = get_user(target_user_id)
        target_lang = target_user[1] if target_user[1] in TEXTS else 'ar'
        
        update_user(target_user_id, 'is_sub', 1)
        update_user(target_user_id, 'start_date', start_date.strftime('%Y-%m-%d'))
        update_user(target_user_id, 'end_date', end_date.strftime('%Y-%m-%d'))
        
        # رد لتأكيد التفعيل للآدمن
        bot.reply_to(message, f"✅ **تم تفعيل الاشتراك بنجاح!**\n\n👤 المستخدم: `{target_user_id}`\n📅 الأيام: {days} يوم\n📅 تاريخ الانتهاء: `{end_date.strftime('%Y-%m-%d')}`", parse_mode='Markdown')
        
        # إرسال إشعار التفعيل تلقائياً إلى المستخدم
        user_notify_msg = TEXTS[target_lang]['activate_success_user'].format(end_date=end_date.strftime('%Y-%m-%d'))
        bot.send_message(target_user_id, user_notify_msg, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Activation Error: {e}")
        bot.reply_to(message, f"❌ حدث خطأ أثناء التفعيل: {e}")

# معالج استقبال الصور والتحليل
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not GEMINI_API_KEY:
        bot.reply_to(message, "❌ مفتاح GEMINI_API_KEY غير مضاف في السيرفر.")
        return

    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    trials, is_sub, end_date_str = user[2], user[3], user[5]
    
    # التحقق من انقضاء الاشتراك
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        try:
            if datetime.datetime.now(tz) > datetime.datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=tz):
                update_user(message.chat.id, 'is_sub', 0)
                is_sub = 0
        except Exception as e:
            logger.error(f"Sub check error: {e}")

    # التحقق من المحاولات المجانية
    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'], parse_mode='Markdown')
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img = Image.open(BytesIO(downloaded_file))
        
        # إجراء التحليل بلغة المستخدم المختارة
        analysis_result = generate_chart_analysis(TEXTS[lang]['prompt'], img)
        
        # إرسال النتيجة بآمان وتصفيتها من التفكير الجانبي
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result)
        
        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)

    except Exception as e:
        error_details = str(e)
        logger.error(f"Chart Analysis Error: {traceback.format_exc()}")
        msg = f"❌ تعذر استكمال التحليل.\nالسبب: `{error_details}`"
        safe_send_long_text(message.chat.id, status_msg.message_id, msg)

# === مسارات السيرفر ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI V9.0 (Ultimate Master Edition) is running active!"

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
        except Exception as e:
            logger.error(f"Webhook Error: {e}")
        return "OK", 200
    return "Forbidden", 403

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    
    if RENDER_URL:
        clean_url = RENDER_URL.rstrip('/')
        bot.set_webhook(url=f"{clean_url}/{TELEGRAM_TOKEN}")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
