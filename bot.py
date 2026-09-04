import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
import re
from concurrent.futures import ThreadPoolExecutor
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from io import BytesIO
from PIL import Image

# === إعداد نظام المراقبة وتسجيل الأخطاء ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات البيئة والمفاتيح ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

raw_keys = os.environ.get('GEMINI_API_KEYS') or os.environ.get('GEMINI_API_KEY') or ''
API_KEYS = [
    k.strip() for k in raw_keys.split(',') 
    if k.strip() and not k.strip().lower().startswith('aiza_invalid')
]

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات البيئة.")

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=5)

# === قاموس مؤقت لتخزين الصورة الأولى لكل مستخدم ===
USER_CHARTS_CACHE = {}

# === إدارة قاعدة البيانات ===
DB_FILE = 'tradeguard.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, 
                      is_sub INTEGER, start_date TEXT, end_date TEXT)''')
        conn.commit()

init_db()

def get_user(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, lang, trials, is_sub, start_date, end_date FROM users WHERE user_id=?", (user_id,))
        user = c.fetchone()
        if not user:
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", (user_id, 'ar', 0, 0, '', ''))
            conn.commit()
            user = (user_id, 'ar', 0, 0, '', '')
        return user

def update_user(user_id, field, value):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
        conn.commit()

# === القوالب والبرومبت المخصص للتحليل المزدوج (Multi-Timeframe) ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI Pro 📈\nنظام التحليل الفني المؤسسي المزدوج (Multi-Timeframe 4H/15M).\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل الآن **الشارت الأول (فريم 4 ساعات 4H)** للبدء.",
        'first_img_received': "📸 **تم استقبال شارت الفريم الكلي (4H) بنجاح!**\n\nالآن أرسل **الشارت الثاني (فريم 15 دقيقة 15M)** لتأكيد نقطة الدخول وتصفية المخاطر.",
        'wait': '⏳ جاري الدمج والتحليل المؤسسي المزدوج (4H + 15M) لتأكيد منطقة الدخول بدقة فائقة... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في استخدام التحليل المتقدم، يرجى الاشتراك.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل الفوري:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'btn_reset': '🔄 إعادة رفع شارت جديد',
        'reset_msg': 'تم مسح الشارت المرفوع سابقاً. يمكنك الآن إرسال **الشارت الأول (فريم 4H)** من جديد.',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك فعال ولغاية: `{end_date}`. بالتوفيق! 📈',
        'prompt': """أنت محترف تداول مؤسسي ومحلل كمي مالي متخصص في التداول عبر الأطر الزمنية المتقاطعة (Multi-Timeframe Analysis - SMC & Price Action).

أمامك صورتان لشارتات نفس الزوج/الأصل المالي:
1. الصورة الأولى: الشارت ذو الإطار الزمني الأكبر (فريم 4 ساعات 4H) لتحديد الاتجاه العام وهيكل السيولة العالي.
2. الصورة الثانية: الشارت ذو الإطار الزمني الأصغر (فريم 15 دقيقة 15M) لتحديد التمركز الدقيق، الرفض، ونقطة الدخول المثالية بمخاطرة دنيا.

التعليمات والقواعد الصارمة:
1. مطابقة التحليل: قم بالربط المباشر بين الاتجاه في فريم 4H ومناطق الدخول الفرعية في فريم 15M. إذا وجد تعارض واضح أو خطورة، أبلغ المستخدم بضرورة "الانتظار وعدم التداول".
2. الدقة الرقمية المطلقة: لا تقم بتخمين أي أسعار. استخرج جميع مستويات الأسعار، الـ SL والـ TP مباشرة من الأرقام المرئية على المحاور السعرية للصورة الثانية (15M) المتطابقة مع سياق الصورة الأولى (4H).
3. تقليل المخاطر: يجب أن يكون وقف الخسارة محكم وضيق بناءً على هيكل فريم 15M لحماية رأس المال وتقديم نسبة مخاطرة إلى عائد ممتازة (Risk-to-Reward >= 1:2).

أخرج التقرير النهائي مباشرة وبشكل منظم بالصيغة التالية دون أي تفكير جانبي:

1. تحليل سياق الاتجاه العام (4H Context):
- اتجاه الهيكل (صاعد/هابط/عرضي) ومناطق العرض/الطلب الكلية المعلمة على فريم 4H.

2. تحليل تأكيد الدخول والدقة (15M Refinement):
- كسر الهيكل الداخلي (mBOS / CHOCH) وسحب السيولة (Liquidity Sweep) على فريم 15M.

3. تقييم جودة الصفقة وتصفية المخاطر (Confluence Score):
- درجة توافق الفريمين المئوية (مثال: 85%) وتأكيد أمان الصفقة.

4. صفقة التداول التنفيذية المتقاطعة (Multi-Timeframe Trade Setup):
- القرار: (شراء Buy / بيع Sell / انتظار وعدم دخول Wait)
- نطاق الدخول الدقيق (Optimal Entry Zone - 15M): (سعر محدد)
- وقف الخسارة الحصين (Stop Loss - SL): (سعر دقيق جداً أسفل/أعلى هيكل الـ 15M)
- أهداف جني الأرباح (Take Profit Targets):
  • Target 1 (TP1):
  • Target 2 (TP2):
  • Target 3 (TP3):
- نسبة المخاطرة إلى العائد (Risk-to-Reward Ratio):
- نصيحة إدارة المخاطر وتصفية الخسارة:"""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI Pro 📈\nMulti-Timeframe Institutional Engine (4H/15M).\n\nChoose language / اختر لغتك:",
        'lang_selected': "English selected successfully ✅\nSend your **First Chart (4-Hour / 4H Frame)** now.",
        'first_img_received': "📸 **Higher Timeframe (4H) Received!**\n\nNow send the **Second Chart (15-Minute / 15M Frame)** to pinpoint execution.",
        'wait': '⏳ Executing Multi-Timeframe Analysis (4H + 15M) for zero-risk optimal entry... Please wait.',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe for full access.',
        'account': '👤 **Your Account Details**\n\n🆔 User ID: `{user_id}`\n📊 Free Trials Used: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Pro Subscription Plans**\n\n🔹 **10-Day Plan:** $20 (USDT)\n🔹 **Monthly Plan (30 Days):** $50 (USDT)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send transfer receipt & User ID (`{user_id}`) to Admin for instant activation:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'btn_reset': '🔄 Reset Chart Upload',
        'reset_msg': 'Previous chart cleared. Send your **First Chart (4H)** again.',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nActive until: `{end_date}`. Good luck! 📈',
        'prompt': """You are an institutional quantitative trader specializing in Multi-Timeframe Analysis (SMC & Price Action).

You are given TWO charts:
1. Image 1: Higher Timeframe (4-Hour / 4H) for macro trend and key Order Blocks.
2. Image 2: Lower Timeframe (15-Minute / 15M) for precise entry trigger and risk minimization.

Instructions:
1. Align 4H trend context with 15M lower timeframe structure. If there is a contradiction, signal "WAIT / NO TRADE".
2. Absolute Price Accuracy: Extract exact price levels from image 2 (15M) visible axes aligned with image 1 context.
3. Tight Risk Control: Set SL strictly based on 15M micro structure for minimum drawdown and high Risk-to-Reward.

Output Format (No preamble):

1. Macro Trend Context (4H):
- Structural Direction & Major Supply/Demand Zones on 4H.

2. Lower Timeframe Refinement (15M):
- Internal BOS/CHOCH and Liquidity Sweeps on 15M.

3. Confluence & Risk Score:
- Alignment Score (%) and safety confirmation.

4. Multi-Timeframe Trade Setup:
- Action: (Buy / Sell / Wait)
- Optimal Entry Zone (15M): (Exact price)
- Protected Stop Loss (SL): (Tight price from 15M)
- Take Profit Targets (TP):
  • Target 1 (TP1):
  • Target 2 (TP2):
  • Target 3 (TP3):
- Risk-to-Reward Ratio:
- Risk Management Directive:"""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    markup.add(KeyboardButton(TEXTS[lang]['btn_reset']))
    return markup

def clean_analysis_output(text, target_lang):
    if not text:
        return text
    if target_lang == 'ar':
        if "1. تحليل سياق الاتجاه العام" in text:
            text = "1. تحليل سياق الاتجاه العام" + text.split("1. تحليل سياق الاتجاه العام")[-1]
    else:
        if "1. Macro Trend Context" in text:
            text = "1. Macro Trend Context" + text.split("1. Macro Trend Context")[-1]

    patterns = [r'\(Self-Correction.*?\)', r'Strict and professional\?.*?\n', r'Order followed\?.*?\n']
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()

def safe_send_long_text(chat_id, status_message_id, full_text, target_lang='ar'):
    full_text = clean_analysis_output(full_text, target_lang)
    chunk_size = 3800
    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
    
    for index, chunk in enumerate(chunks):
        try:
            if index == 0:
                bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode='Markdown')
            else:
                bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
        except telebot.apihelper.ApiTelegramException:
            try:
                if index == 0:
                    bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode=None)
                else:
                    bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)
            except Exception as inner_e:
                logger.error(f"Fallback send failed: {inner_e}")

# === تحديث النماذج حصرياً للإصدارات الحديثة الموصى بها من واجهة برمجة التطبيقات (3.6 و 2.5 وما فوق) ===
TARGET_MODELS = [
    'gemini-3.6-flash',
    'gemini-2.5-flash',
    'gemini-2.5-pro'
]

def generate_multi_chart_analysis(prompt_text, img1, img2):
    if not API_KEYS:
        raise Exception("لم يتم العثور على مفاتيح API صالحة.")

    last_error = "لم تتم المحاولة بعد."

    for key_idx, key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=key)
            for model_name in TARGET_MODELS:
                try:
                    logger.info(f"⚡ جاري تحليل الشارتين بالمفتاح #{key_idx + 1} والنموذج [{model_name}]...")
                    model = genai.GenerativeModel(model_name)
                    
                    response = model.generate_content(
                        [prompt_text, img1, img2], 
                        safety_settings=safety_settings,
                        request_options={'timeout': 25}
                    )
                    
                    if response and response.text:
                        return response.text
                except Exception as err:
                    err_str = str(err)
                    last_error = err_str
                    logger.warning(f"تجاوز أو خطأ للنموذج [{model_name}]: {err_str}")
                    if "429" in err_str or "quota" in err_str.lower() or "404" in err_str or "not found" in err_str.lower():
                        continue
        except Exception as key_err:
            last_error = str(key_err)

    raise Exception(f"تعذر تحليل الصورتين عبر المفاتيح والنماذج الحديثة. آخر خطأ: {last_error}")

def process_photos_async(message, lang, img1, img2):
    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    try:
        analysis_result = generate_multi_chart_analysis(TEXTS[lang]['prompt'], img1, img2)
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang)
        
        user = get_user(message.chat.id)
        if not user[3]:
            update_user(message.chat.id, 'trials', user[2] + 1)

    except Exception as e:
        logger.error(f"خطأ المعالجة الخلفية: {traceback.format_exc()}")
        safe_send_long_text(message.chat.id, status_msg.message_id, f"❌ تعذر استكمال التحليل المزدوج.\nالسبب: `{e}`", target_lang=lang)

# === الأوامر والمعالجات ===
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
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, TEXTS[lang]['lang_selected'], reply_markup=get_main_keyboard(lang))

@bot.message_handler(func=lambda m: m.text and ('إعادة رفع' in m.text or 'Reset' in m.text))
def reset_chart_upload(message):
    user_id = message.chat.id
    if user_id in USER_CHARTS_CACHE:
        del USER_CHARTS_CACHE[user_id]
    user = get_user(user_id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    bot.reply_to(message, TEXTS[lang]['reset_msg'], parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text and ('حسابي' in m.text or 'Account' in m.text or m.text == '/my_account'))
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, _, end_date = user[1], user[2], user[3], user[4], user[5]
    if lang not in TEXTS: lang = 'ar'
    sub_status = TEXTS[lang]['active'].format(end=end_date) if is_sub else TEXTS[lang]['inactive']
    msg = TEXTS[lang]['account'].format(user_id=message.chat.id, trials=trials, sub_status=sub_status)
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text and ('الاشتراك' in m.text or 'Subscription' in m.text or m.text == '/subscribe'))
def sub_info(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    bot.reply_to(message, TEXTS[lang]['sub_info'].format(user_id=message.chat.id), parse_mode='Markdown')

@bot.message_handler(content_types=['photo'])
def handle_photos(message):
    user_id = message.chat.id
    user = get_user(user_id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    trials, is_sub, end_date_str = user[2], user[3], user[5]
    
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        try:
            if datetime.datetime.now(tz) > datetime.datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=tz):
                update_user(user_id, 'is_sub', 0)
                is_sub = 0
        except:
            pass

    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'], parse_mode='Markdown')
        return

    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    img = Image.open(BytesIO(downloaded_file))

    if user_id not in USER_CHARTS_CACHE:
        USER_CHARTS_CACHE[user_id] = img
        bot.reply_to(message, TEXTS[lang]['first_img_received'], parse_mode='Markdown')
    else:
        img1 = USER_CHARTS_CACHE.pop(user_id)
        img2 = img
        executor.submit(process_photos_async, message, lang, img1, img2)

if RENDER_URL:
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{TELEGRAM_TOKEN}")
        logger.info("✅ Webhook configured successfully.")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI Pro Multi-Timeframe Engine Active!"

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
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
