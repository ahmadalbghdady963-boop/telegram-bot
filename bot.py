import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
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

# === إعدادات النظام ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات Render.")

# تفعيل الـ API باستخدام مفتاحك الخاص (بدون اشتراطات على شكل المفتاح)
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# إعدادات الأمان
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# === تهيئة البوت والسيرفر ===
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# === قاعدة البيانات ===
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
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
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

# === نصوص اللغات (مع توجيه الذكاء الاصطناعي للاختصار قليلاً) ===
TEXTS = {
    'ar': {
        'wait': '⏳ جاري تحليل الشارت بأعلى دقة... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في تحليل الشارتات، يرجى الاشتراك.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI**\n\n🔹 **10 أيام:** 20 دولار\n🔹 **اشتراك شهري:** 50 دولار\n\n📥 **الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 أرسل إشعار التحويل والـ ID (`{user_id}`) للتفعيل:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'prompt': """أنت محلل أسواق مالية صارم ومحترف TradeGuard AI.
إذا لم تكن الصورة لشارت مالي، قل فقط: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية."
إذا كانت صحيحة، أعطني تحليلاً احترافياً دقيقاً ومباشراً بدون كلام زائد (بحد أقصى 350 كلمة)، بالترتيب التالي:
1. الاتجاه العام: (مباشر)
2. أقوى المقاومات: (أرقام دقيقة)
3. أقوى الدعوم: (أرقام دقيقة)
4. نسبة حدوث التوقع: (%)
5. الخلاصة والنصيحة: (شراء أو بيع أو انتظار)."""
    },
    'en': {
        'wait': '⏳ Performing technical analysis... Please wait.',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe to continue.',
        'account': '👤 **Your Account**\n\n🆔 ID: `{user_id}`\n📊 Trials: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **Subscriptions**\n\n🔹 **10 Days:** $20\n🔹 **1 Month:** $50\n\n📥 **USDT - TON Wallet:**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send receipt and your ID (`{user_id}`) to:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Ends: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'prompt': """You are a strict financial analyst, TradeGuard AI.
If the image is not a financial chart, reply ONLY with: "⚠️ Sorry, this image is not a candlestick chart."
If valid, provide a highly detailed but concise professional analysis (max 350 words) with NO intro/outro, in this exact format:
1. Market Trend: (Direct state)
2. Key Resistances: (Precise numbers)
3. Key Supports: (Precise numbers)
4. Probability of Success: (%)
5. Conclusion & Advice: (Clear decision)."""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

# =====================================================================
# حل مشكلة الرسائل الطويلة (MESSAGE_TOO_LONG) وأخطاء التنسيق (Entities)
# =====================================================================
def safe_send_long_text(chat_id, status_message_id, full_text):
    # الحد الأقصى لرسالة تليجرام هو 4096 حرف، سنقوم بتقسيمها إلى 4000 حرف لتكون آمنة.
    chunk_size = 4000
    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
    
    for index, chunk in enumerate(chunks):
        try:
            if index == 0:
                # الرسالة الأولى: نقوم بتعديل رسالة "الانتظار"
                bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode='Markdown')
            else:
                # إذا كانت الرسالة أطول من 4000 حرف، سيتم إرسال الباقي كرسائل جديدة متتالية
                bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
                
        except telebot.apihelper.ApiTelegramException as e:
            error_msg = str(e).lower()
            # في حال وجود خطأ بتنسيق النجوم/الرموز في Markdown
            if "can't parse entities" in error_msg or "400" in error_msg:
                try:
                    if index == 0:
                        bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode=None)
                    else:
                        bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)
                except Exception as inner_e:
                    logger.error(f"Fallback sending failed: {inner_e}")
            else:
                logger.error(f"Telegram Unknown Error: {e}")

# =====================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"), 
               InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    bot.reply_to(message, "مرحباً بك في TradeGuard AI 📈\nالرجاء اختيار لغتك / Choose your language:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_language(call):
    lang = call.data.split('_')[1]
    update_user(call.message.chat.id, 'lang', lang)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    msg = "أرسل أي صورة لشارت للتحليل الآن." if lang == 'ar' else "Send any chart image for analysis."
    bot.send_message(call.message.chat.id, msg, reply_markup=get_main_keyboard(lang))

@bot.message_handler(func=lambda message: message.text in [TEXTS['ar']['btn_acc'], TEXTS['en']['btn_acc'], '/my_account'])
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, _, end_date = user[1], user[2], user[3], user[4], user[5]
    sub_status = TEXTS[lang]['active'].format(end=end_date) if is_sub else TEXTS[lang]['inactive']
    msg = TEXTS[lang]['account'].format(user_id=message.chat.id, trials=trials, sub_status=sub_status)
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text in [TEXTS['ar']['btn_sub'], TEXTS['en']['btn_sub'], '/subscribe'])
def sub_info(message):
    lang = get_user(message.chat.id)[1]
    bot.reply_to(message, TEXTS[lang]['sub_info'].format(user_id=message.chat.id), parse_mode='Markdown')

@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return 
    try:
        parts = message.text.split()
        target_user = int(parts[1])
        days = int(parts[2])
        tz = pytz.timezone('Asia/Riyadh')
        start_date = datetime.datetime.now(tz)
        end_date = start_date + datetime.timedelta(days=days)
        update_user(target_user, 'is_sub', 1)
        update_user(target_user, 'start_date', start_date.strftime('%Y-%m-%d'))
        update_user(target_user, 'end_date', end_date.strftime('%Y-%m-%d'))
        bot.reply_to(message, f"✅ تم تفعيل الاشتراك للمستخدم {target_user} بنجاح لمدة {days} يوم.")
        bot.send_message(target_user, f"🎉 **تم تفعيل اشتراكك!**\nينتهي في: {end_date.strftime('%Y-%m-%d')}", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "❌ خطأ في الصيغة. استخدم: /activate <رقم_المستخدم> <عدد_الأيام>")

# === استكشاف النماذج المتاحة ديناميكياً باستخدام مفتاحك ===
def generate_chart_analysis(prompt, img):
    available_models = []
    try:
        # البحث عن النماذج المتاحة في حسابك والتي تدعم توليد المحتوى
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        logger.info(f"Discovered models for your API Key: {available_models}")
    except Exception as e:
        logger.error(f"Error fetching models list: {e}")
        # قوائم احتياطية في أسوأ الحالات
        available_models = ['models/gemini-1.5-flash', 'models/gemini-pro-vision']

    if not available_models:
        raise Exception("لم يتم العثور على أي نموذج داعم في مفتاح الـ API الخاص بك.")

    last_exception = None
    # يجرب البوت النماذج المتاحة واحداً تلو الآخر حتى ينجح
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

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not GEMINI_API_KEY:
        bot.reply_to(message, "❌ مفتاح GEMINI_API_KEY غير مضاف في السيرفر.")
        return

    user = get_user(message.chat.id)
    lang, trials, is_sub, end_date_str = user[1], user[2], user[3], user[5]
    
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        try:
            if datetime.datetime.now(tz) > datetime.datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=tz):
                update_user(message.chat.id, 'is_sub', 0)
                is_sub = 0
        except:
            pass

    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'], parse_mode='Markdown')
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img = Image.open(BytesIO(downloaded_file))
        
        # استدعاء التحليل
        analysis_result = generate_chart_analysis(TEXTS[lang]['prompt'], img)
        
        # إرسال التحليل عبر نظام "المقسّم الذكي" لتفادي أخطاء الرسائل الطويلة والتنسيق
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
    return "TradeGuard AI V8.0 (Anti-Long-Message & Auto-Discovery) is running!"

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
