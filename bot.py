import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from flask import Flask, request
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
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
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# إعدادات الأمان
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ضبط دقة الذكاء الاصطناعي
ANALYTICAL_GEN_CONFIG = GenerationConfig(
    temperature=0.1,
    top_p=0.9,
    top_k=40,
    max_output_tokens=2048
)

# === تهيئة البوت والسيرفر ===
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# === إدارة قاعدة البيانات ===
def get_db_connection():
    return sqlite3.connect('tradeguard.db', check_same_thread=False, timeout=20)

def init_db():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, 
                      is_sub INTEGER, start_date TEXT, end_date TEXT)''')
        conn.commit()
    finally:
        conn.close()

init_db()

def get_user(user_id):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id, lang, trials, is_sub, start_date, end_date FROM users WHERE user_id=?", (user_id,))
        user = c.fetchone()
        if not user:
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", (user_id, 'ar', 0, 0, '', ''))
            conn.commit()
            user = (user_id, 'ar', 0, 0, '', '')
        return user
    finally:
        conn.close()

def update_user(user_id, field, value):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
        conn.commit()
    finally:
        conn.close()

# === نصوص وقوالب اللغات ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI 📈\nمستشارك الذكي والاحترافي لتحليل الشارتات المالية.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي صورة لشارت مالي للتحليل المؤسسي الآن.",
        'wait': '⏳ جاري فحص هيكل السوق وتجهيز خطة التداول الشاملة... برجاء الانتظار.',
        'no_trials_msg': '⚠️ **لقد تم إنهاء محاولاتك المجانية.**\n\nللاستمرار في الاستفادة من تحليلات الذكاء الاصطناعي، رجاءً شحن حسابك:\n🔹 **20 دولار** (10 أيام)\n🔹 **50 دولار** (شهري)\n\n📥 **عنوان الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 للتفعيل أرسل صورة التحويل والـ ID `{user_id}` إلى:\n@TradeGuard_Admin',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك**\n\n🔹 **10 أيام:** 20 دولار (USDT)\n🔹 **شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 للتفعيل راسل:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nصالح لغاية: `{end_date}`.\nيمكنك الآن إرسال الشارتات بحرية. بالتوفيق! 📈',
        'prompt': """أنت خبير تداول مؤسسي (Smart Money & Price Action). افحص الشارت بدقة. 
إذا لم تكن الصورة لشارت تداول، اكتب فقط: "⚠️ الصورة لا تطابق شارت تداول."

إذا كان شارتاً، اكتب تحليلاً باللغة العربية حصراً، بأسلوب مباشر دون مقدمات، ويجب أن يملأ كل النقاط التالية بدقة:

1. 📊 الاتجاه وهيكل السوق:
- الاتجاه العام: (صاعد/هابط/عرضي)
- التوصيف: (شرح مختصر لحركة السعر)

2. 🚧 المستويات المفتاحية:
- مقاومة رئيسية: (السعر بدقة + السبب)
- دعم رئيسي: (السعر بدقة + السبب)

3. 🎯 خطة التداول الشاملة:
- القرار: (شراء / بيع / انتظار)
- نقطة الدخول (Entry): (مستوى سعري محدد)
- وقف الخسارة (SL): (مستوى حماية صارم)
- الهدف الأول (TP1): (السعر)
- الهدف الثاني (TP2): (السعر)
- الهدف الثالث (TP3): (السعر الأبعد)

4. 📈 نسبة نجاح الفرصة:
- (النسبة المئوية %)

⚠️ تذكير: التزم دائماً بوقف الخسارة."""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nChoose your language / اختر لغتك:",
        'lang_selected': "English selected successfully ✅\nSend any chart image now.",
        'wait': '⏳ Analyzing market structure and preparing trading setup... Please wait.',
        'no_trials_msg': '⚠️ **Trials Expired.**\n\nTop up your account to continue:\n🔹 **$20** (10 Days)\n🔹 **$50** (Monthly)\n\n📥 **USDT - TON Network:**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send receipt & ID `{user_id}` to:\n@TradeGuard_Admin',
        'account': '👤 **Account Details**\n\n🆔 ID: `{user_id}`\n📊 Trials: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **Subscriptions**\n\n🔹 **10-Day:** $20 (USDT)\n🔹 **Monthly:** $50 (USDT)\n\n📥 **USDT - TON Network:**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Contact Admin:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Ends: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nValid until: `{end_date}`. Enjoy! 📈',
        'prompt': """You are an Institutional Trading Expert. Analyze the chart.
If not a chart, reply ONLY: "⚠️ Not a valid trading chart."

If valid, output ONLY in English using this exact structure:

1. 📊 Trend & Structure:
- Main Trend: (Bullish/Bearish/Ranging)
- Context: (Brief explanation)

2. 🚧 Key Levels:
- Major Resistance: (Price + Reason)
- Major Support: (Price + Reason)

3. 🎯 Comprehensive Trading Setup:
- Decision: (Buy/Sell/Wait)
- Entry Price: (Exact level)
- Stop Loss (SL): (Strict level)
- Take Profit 1 (TP1): (Price)
- Take Profit 2 (TP2): (Price)
- Take Profit 3 (TP3): (Extended Price)

4. 📈 Setup Probability:
- (Percentage %)

⚠️ Risk Warning: Always enforce SL."""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

def safe_send_long_text(chat_id, status_message_id, full_text):
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=full_text.strip(), parse_mode='Markdown')
    except Exception:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=full_text.strip(), parse_mode=None)
        except Exception:
            pass

def prepare_image(img_bytes):
    img = Image.open(BytesIO(img_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    max_dim = 1024
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return img

def generate_chart_analysis(prompt, img):
    # الفحص التلقائي المستند إلى النماذج المتاحة حقيقةً في مكتبة جوني آي (بدون أسماء وهمية)
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        logger.info(f"Available models found: {available_models}")
    except Exception as e:
        logger.warning(f"Could not list models dynamically: {e}")
        available_models = []

    # ترتيب الأولويات للنماذج المعتمدة (الحديثة أولاً ثم الروابط العامة)
    priority_candidates = [
        'gemini-3.1-flash',
        'gemini-3.7-flash',
        'gemini-1.5-flash',
        'gemini-2.5-pro',
        'gemini-1.5-pro',
        'gemini-flash-latest',
        'gemini-pro-latest'
    ]
    
    # دمج النماذج المتاحة فعلياً من الحساب مع القائمة المفضلة
    candidate_models = []
    for m in priority_candidates:
        if any(m in am for am in available_models):
            candidate_models.append(m)
            
    # إضافة أي نموذج آخر متاح يدعم المحتوى كاحتياطي نهائي
    for am in available_models:
        if am not in candidate_models and ('flash' in am or 'pro' in am):
            candidate_models.append(am)

    # إذا لم تنجح الجدولة التلقائية، نضع الأسماء الأكثر ضماناً كملجأ أخير
    if not candidate_models:
        candidate_models = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-pro-latest']

    last_error = None
    for model_name in candidate_models:
        try:
            logger.info(f"Trying model: {model_name}")
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                [prompt, img], 
                generation_config=ANALYTICAL_GEN_CONFIG,
                safety_settings=safety_settings
            )
            if response and response.text:
                return response.text
        except Exception as e:
            err_str = str(e).lower()
            logger.warning(f"Model {model_name} failed: {e}")
            last_error = e
            if "429" in err_str or "quota" in err_str:
                time.sleep(2)
            continue
            
    if last_error and ("1024" in str(last_error) or "quota" in str(last_error).lower()):
        raise Exception("QUOTA_EXCEEDED")
        
    raise Exception(f"API Error. Please try again.")

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
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, TEXTS[lang]['lang_selected'], reply_markup=get_main_keyboard(lang))

@bot.message_handler(func=lambda m: m.text and ('حسابي' in m.text or 'Account' in m.text or m.text == '/my_account'))
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, end_date_str = user[1], user[2], user[3], user[5]
    if lang not in TEXTS: lang = 'ar'
    
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        today_date = datetime.datetime.now(tz).date()
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if today_date > end_date:
                is_sub = 0
                update_user(message.chat.id, 'is_sub', 0)
        except:
            pass

    sub_status = TEXTS[lang]['active'].format(end=end_date_str) if is_sub else TEXTS[lang]['inactive']
    msg = TEXTS[lang]['account'].format(user_id=message.chat.id, trials=trials, sub_status=sub_status)
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text and ('الاشتراك' in m.text or 'Subscription' in m.text or m.text == '/subscribe'))
def sub_info(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    bot.reply_to(message, TEXTS[lang]['sub_info'].format(user_id=message.chat.id), parse_mode='Markdown')

@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return 
    try:
        parts = message.text.split()
        target_user_id = int(parts[1])
        days = int(parts[2])
        
        tz = pytz.timezone('Asia/Riyadh')
        start_date = datetime.datetime.now(tz).date()
        end_date = start_date + datetime.timedelta(days=days)
        
        target_user = get_user(target_user_id)
        target_lang = target_user[1] if target_user[1] in TEXTS else 'ar'
        
        update_user(target_user_id, 'is_sub', 1)
        update_user(target_user_id, 'start_date', start_date.strftime('%Y-%m-%d'))
        update_user(target_user_id, 'end_date', end_date.strftime('%Y-%m-%d'))
        update_user(target_user_id, 'trials', 0)
        
        bot.reply_to(message, f"✅ **تم التفعيل بنجاح!**\n👤 المستخدم: `{target_user_id}`\n📅 الانتهاء: `{end_date.strftime('%Y-%m-%d')}`", parse_mode='Markdown')
        user_msg = TEXTS[target_lang]['activate_success_user'].format(end_date=end_date.strftime('%Y-%m-%d'))
        bot.send_message(target_user_id, user_msg, parse_mode='Markdown', reply_markup=get_main_keyboard(target_lang))
    except:
        bot.reply_to(message, f"❌ استخدم الصيغة `/activate <USER_ID> <DAYS>`")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not GEMINI_API_KEY:
        bot.reply_to(message, "❌ مفتاح الـ API غير مضاف.")
        return

    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    trials, is_sub, end_date_str = user[2], user[3], user[5]
    
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        today_date = datetime.datetime.now(tz).date()
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            if today_date > end_date:
                update_user(message.chat.id, 'is_sub', 0)
                is_sub = 0
        except:
            pass

    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials_msg'].format(user_id=message.chat.id), parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img = prepare_image(downloaded_file)
        
        analysis_result = generate_chart_analysis(TEXTS[lang]['prompt'], img)
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result)
        
        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)

    except Exception as e:
        logger.error(f"Error during analysis: {traceback.format_exc()}")
        if "QUOTA_EXCEEDED" in str(e):
            err_text = "⚠️ وصلت لـ الحد الأقصى المجاني من جوجل في الدقيقة. يرجى الانتظار دقيقة وإعادة إرسال الصورة."
        else:
            err_text = "❌ حدث خطأ في الاتصال بالذكاء الاصطناعي، يرجى إعادة المحاولة."
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=err_text)

# === تشغيل السيرفر ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI V16.0 - Fully Validated Active!"

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        except Exception as e:
            logger.error(f"Webhook Error: {e}")
        return "OK", 200
    return "Forbidden", 1024

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep1 = 1
    time.sleep(1) 
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{TELEGRAM_TOKEN}")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
