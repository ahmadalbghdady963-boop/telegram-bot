import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
import re
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
        'no_trials_msg': '⚠️ **لقد تم إنهاء محاولاتك الثلاثة المجانية.**\n\nللاستمرار في الاستفادة من تحليلات الذكاء الاصطناعي المفتوحة، رجاءً شحن حسابك عبر إرسال:\n🔹 **20 دولار** (للاشتراك لمدة 10 أيام)\n🔹 **50 دولار** (للاشتراك الشهري)\n\n📥 **عنوان الدفع (USDT - شبكة TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 **طريقة التفعيل:**\nأرسل صورة إشعار التحويل ورقم الـ ID الخاص بك `{user_id}` عبر التلغرام إلى حساب الإدارة:\n@TradeGuard_Admin',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك فعال الآن ولغاية تاريخ: `{end_date}`.\nيمكنك الآن إرسال الشارتات بحرية تامة. بالتوفيق! 📈',
        'prompt': """أنت خبير التداول الفني ومحلل هيكل السوق (Institutional Price Action Expert). مهمتك فحص الشارت المرفق بمنتهى الدقة والصرامة وإعطاء خطة تداول متكاملة.

إذا لم تكن الصورة لشارت تداول مالي يحتوي شموعاً يابانية ومحور أسعار، اكتب فقط: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية."

إذا كان الشارت صحيحاً، اكتب الرد باللغة العربية فقط، بأسلوب مباشر واحترافي بالهيكل التالي:

1. 📊 الاتجاه العام وهيكل السوق:
- الاتجاه: (صاعد / هابط / عرضي)
- الوصف: (تحليل مختصر لحركة السعر الحالية)

2. 🚧 المستويات المفتاحية:
- أقوى مقاومة: (السعر بدقة من المحور الأيمن + السبب)
- أقوى دعم: (السعر بدقة من المحور الأيمن + السبب)

3. 🎯 خطة التداول الاحترافية:
- القرار: (شراء / بيع / انتظار)
- نقطة الدخول (Entry): (السعر المحدد بدقة)
- وقف الخسارة (SL): (مستوى سعري صارم)
- الهدف الأول (TP1): (السعر المستهدف الأول)
- الهدف الثاني (TP2): (السعر المستهدف الثاني)
- الهدف الثالث (TP3): (السعر المستهدف الثالث)

4. 📈 نسبة نجاح التوقع:
- (نسبة مئوية واضحة ومدروسة)

⚠️ تنبيه المخاطر: التزم دائماً بوقف الخسارة."""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nChoose your language / اختر لغتك:",
        'lang_selected': "English language selected successfully ✅\nSend any chart image now for institutional analysis.",
        'wait': '⏳ Analyzing market structure and preparing complete trading setup... Please wait.',
        'no_trials_msg': '⚠️ **Your 3 free trials have expired.**\n\nTo continue using AI analysis, please top up your account by sending:\n🔹 **$20** (10-Day Subscription)\n🔹 **$50** (Monthly Subscription)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 **Activation:**\nSend transfer receipt and User ID `{user_id}` via Telegram to Admin:\n@TradeGuard_Admin',
        'account': '👤 **Your Account Details**\n\n🆔 User ID: `{user_id}`\n📊 Free Trials Used: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Subscriptions**\n\n🔹 **10-Day Plan:** $20 (USDT)\n🔹 **Monthly Plan (30 Days):** $50 (USDT)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send receipt & ID (`{user_id}`) to Admin:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nActive until: `{end_date}`.\nEnjoy unlimited chart analysis! 📈',
        'prompt': """You are an Institutional Price Action Expert. Analyze the attached trading chart with extreme rigor.

If the image is not a candlestick chart with a price axis, reply ONLY: "⚠️ Sorry, this image is not a candlestick chart."

If valid, output ONLY in English using this exact structure:

1. 📊 Market Trend & Structure:
- Trend: (Bullish / Bearish / Ranging)
- Description: (Brief context)

2. 🚧 Key Levels:
- Major Resistance: (Exact price + Reason)
- Major Support: (Exact price + Reason)

3. 🎯 Professional Trading Setup:
- Decision: (Buy / Sell / Wait)
- Entry Price: (Exact entry level)
- Stop Loss (SL): (Strict protective level)
- Take Profit 1 (TP1): (First target)
- Take Profit 2 (TP2): (Second target)
- Take Profit 3 (TP3): (Extended target)

4. 📈 Probability of Success:
- (Percentage value)

⚠️ Risk Warning: Always strictly enforce Stop Loss."""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

def safe_send_long_text(chat_id, status_message_id, full_text, target_lang='ar'):
    try:
        bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=full_text.strip(), parse_mode='Markdown')
    except Exception:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=full_text.strip(), parse_mode=None)
        except Exception:
            pass

# دالة تجهيز وضغط الصورة لتقليل استهلاك الكوتا
def prepare_image(img_bytes):
    img = Image.open(BytesIO(img_bytes))
    if img.mode != 'RGB':
        img = img.convert('RGB')
    max_dim = 1024
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return img

def generate_chart_analysis(prompt, img):
    # استخدام نماذج Flash المباشرة للحد من تجاوز الكوتا
    candidate_models = ['models/gemini-1.5-flash', 'models/gemini-2.0-flash', 'gemini-1.5-flash']
    
    last_error = None
    for model_name in candidate_models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                [prompt, img], 
                generation_config=ANALYTICAL_GEN_CONFIG,
                safety_settings=safety_settings
            )
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            last_error = e
            if "429" in str(e) or "quota" in str(e).lower():
                time.sleep(2)
            continue
            
    if last_error and ("429" in str(last_error) or "quota" in str(last_error).lower()):
        raise Exception("QUOTA_EXCEEDED")
    raise Exception("تعذر تحليل الصورة حالياً، يرجى إعادة المحاولة.")

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
        except Exception:
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
        
        bot.reply_to(message, f"✅ **تم التفعيل بنجاح!**\n👤 المستخدم: `{target_user_id}`\n📅 الفترة: {days} يوم\n📅 الانتهاء: `{end_date.strftime('%Y-%m-%d')}`", parse_mode='Markdown')
        
        user_msg = TEXTS[target_lang]['activate_success_user'].format(end_date=end_date.strftime('%Y-%m-%d'))
        bot.send_message(target_user_id, user_msg, parse_mode='Markdown', reply_markup=get_main_keyboard(target_lang))
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: استخدم الصيغة `/activate <USER_ID> <DAYS>`")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not GEMINI_API_KEY:
        bot.reply_to(message, "❌ مفتاح الذكاء الاصطناعي غير مضاف في السيرفر.")
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
        msg = TEXTS[lang]['no_trials_msg'].format(user_id=message.chat.id)
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # ضغط الصورة لتوفير الكوتا والتوكينات
        img = prepare_image(downloaded_file)
        
        analysis_result = generate_chart_analysis(TEXTS[lang]['prompt'], img)
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang)
        
        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        if "QUOTA_EXCEEDED" in str(e):
            err_text = "⚠️ وصل الحساب المجاني للحد الأقصى من الطلبات المسموح بها في الدقيقة. يرجى الانتظار 30 ثانية وإعادة إرسال الصورة."
        else:
            err_text = "❌ تعذر استكمال التحليل بسبب ضغط الشبكة، يرجى إعادة المحاولة."
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=err_text)

# === تشغيل السيرفر ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI V14.0 Quota-Optimized Active!"

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
    return "Forbidden", 403

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{TELEGRAM_TOKEN}")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
