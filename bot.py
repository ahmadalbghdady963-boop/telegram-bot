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
    # الفحص التلقائي المستند إلى النماذج المتاحة حقيقةً في مكتبة جيميناي
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        logger.info(f"Available models found: {available_models}")
    except Exception as e:
        logger.warning(f"Could not list models dynamically: {e}")
        available_models = []

    # تم التحديث بناءً على سجلات السيرفر لتشمل نماذج الجيل الثالث المتاحة للمفاتيح الجديدة
    priority_candidates = [
        'gemini-3.7-flash',
        'gemini-3.5-flash',
        'gemini-3.1-pro-preview',
        'gemini-flash-latest',
        'gemini-pro-latest'
    ]
    
    candidate_models = []
    for m in priority_candidates:
        if any(m in am for am in available_models):
            candidate_models.append(m)
            
    # إضافة أي نموذج فلاش أو برو متاح كاحتياطي
    for am in available_models:
        if am not in candidate_models and ('flash' in am or 'pro' in am):
            # إزالة بادئة models/ لتجنب أخطاء التوجيه
            clean_name = am.replace('models/', '')
            candidate_models.append(clean_name)

    if not candidate_models:
        candidate_models = ['gemini-3.5-flash', 'gemini-3.1-pro-preview']

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
        
    raise Exception(f"API Error: All models failed. Last error: {last_error}")
