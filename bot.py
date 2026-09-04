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
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from io import BytesIO
from PIL import Image
import yfinance as yf # المكتبة الجديدة لربط البوت بأسواق المال الحقيقية

# === إعداد نظام المراقبة وتسجيل الأخطاء ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات البيئة والمفاتيح ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

raw_keys = os.environ.get('GEMINI_API_KEYS') or os.environ.get('GEMINI_API_KEY') or ''
API_KEYS = [k.strip() for k in raw_keys.split(',') if k.strip() and not k.strip().lower().startswith('aiza_invalid')]

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود.")

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# === إدارة قاعدة البيانات ===
def get_db_connection():
    return sqlite3.connect('tradeguard.db', check_same_thread=False, timeout=10)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, is_sub INTEGER, start_date TEXT, end_date TEXT)''')
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

# === القوالب والبرومبت المتقدم ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI Pro 📈\nالمحرك الذكي المتقدم لتحليل الشارتات المالية بدقة مؤسسية فائقة.\n\nالرجاء اختيار لغتك:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي شارت مالي للتحليل المؤسسي الآن.",
        'wait': '⏳ جاري الاتصال بأسواق المال لاستخراج البيانات الحية ومطابقتها مع الشارت... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3). يرجى الاشتراك.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري:** 50 دولار (USDT)\n\n📥 **عنوان الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 للتفعيل راسل: @TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\nاشتراكك فعال ولغاية: `{end_date}`. بالتوفيق! 📈',
        'prompt': """أنت خبير مالي كمي (Quant Analyst). مهمتك تحليل الصورة المرفقة، ولكن **يمنع منعاً باتاً استنتاج أي أسعار من الصورة فقط**. 
لقد قمت أنا بكسر حاجز الصورة وجلبت لك البيانات الحقيقية من السوق المالي لهذه اللحظة.

البيانات الحية المباشرة من السوق الآن:
{live_data}

تعليمات التحليل الخوارزمي الصارمة:
1. استخدم الأرقام المذكورة في "البيانات الحية" أعلاه لتحديد السعر الحالي، ومطابقته مع الهيكل الفني الموجود في الصورة (الشموع، الدعوم، المقاومات).
2. إذا كان السعر الحالي في السوق قريباً من منطقة سيولة (Liquidity Pool) أو كتلة طلب (Order Block) تظهر في الصورة، قم بالإشارة إليها بالأرقام الدقيقة.
3. التزم بإدارة مخاطر صارمة: يجب أن يكون وقف الخسارة (SL) خلف آخر قاع/قمة هيكلية بوضوح لتجنب ضرب الستوب الوهمي. نسبة العائد للمخاطرة (R:R) يجب ألا تقل عن 1:2.

اكتب التقرير بالصيغة التالية فقط بدون مقدمات:

1. نظرة السوق والبيانات الحقيقية:
- الزوج/الأصل: (بناء على البيانات)
- السعر الحالي الفعلي: (اذكر الرقم الدقيق)
- الاتجاه العام الهيكلي: (من خلال تقييم الصورة)

2. مناطق العرض والطلب (Smart Money Concepts):
- منطقة العرض (المقاومة): (رقم دقيق استناداً للتحليل المشترك)
- منطقة الطلب (الدعم): (رقم دقيق)
- الفجوات السعرية (FVG): (إن وجدت)

3. قرار التداول الخوارزمي (التوصية):
- الإجراء: (شراء / بيع / انتظار)
- نقطة الدخول (Entry): (رقم دقيق)
- وقف الخسارة (SL): (رقم دقيق لتجنب تصفية الحساب)
- الأهداف (TP):
  • الهدف الأول:
  • الهدف الثاني:
- تنبيه المخاطر: (إرشادات لحجم العقد مقارنة بحجم المحفظة)"""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI Pro 📈\nChoose your language:",
        'lang_selected': "English selected ✅\nSend a chart image.",
        'wait': '⏳ Connecting to live markets & correlating chart data. Please wait...',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe.',
        'account': '👤 Account: `{user_id}`\nTrials: {trials}/3\nSub: {sub_status}',
        'sub_info': '💎 Subscribe:\n10 Days: $20\n30 Days: $50\nUSDT TON: `UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`',
        'active': 'Active ✅ ({end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 Account',
        'btn_sub': '💎 Subscribe',
        'activate_success_user': '🎉 Activated until `{end_date}`.',
        'prompt': """You are a Quant Analyst. DO NOT hallucinate prices from the image alone. I have fetched LIVE market data for you to use as reality grounding.

LIVE MARKET DATA:
{live_data}

Rules:
1. Merge the visual structure (SMC, Order Blocks) with the exact live data numbers.
2. Ensure accurate Support/Resistance based on real prices.
3. Strict R:R minimum 1:2.

Format:
1. Market Overview: (Symbol, Live Price, Trend)
2. SMC Zones: (Supply/Demand exact prices)
3. Algorithmic Trade Setup: (Action, Entry, SL, TP1, TP2, Risk Advice)"""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

CANDIDATE_MODELS = ['gemini-3.6-flash', 'gemini-3.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash']

def fetch_live_market_data(image, api_key):
    """
    الخطوة السرية: استخدام الذكاء الاصطناعي لاستخراج الرمز، ثم جلب الأسعار الحقيقية من ياهو فاينانس.
    """
    genai.configure(api_key=api_key)
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        ext_prompt = "Examine this trading chart. Extract ONLY the financial symbol (e.g. EURUSD, XAUUSD, BTC-USD, AAPL). If it's a forex pair, write it like EURUSD=X. If gold, XAUUSD=X. If you are not absolutely sure, reply with UNKNOWN. Reply with just the symbol, nothing else."
        res = model.generate_content([ext_prompt, image])
        symbol = res.text.strip().upper()
        
        if "UNKNOWN" in symbol or not symbol:
            return "تعذر استخراج الرمز المالي بدقة من الصورة. التحليل سيعتمد على الرؤية البصرية فقط."
        
        # الاتصال بالسوق الحقيقي
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="2d")
        if data.empty:
             return f"الرمز المستخرج ({symbol}) صحيح، لكن بيانات السوق الحية غير متوفرة حالياً."
             
        latest = data.iloc[-1]
        live_info = f"Symbol: {symbol}\nCurrent Close Price: {latest['Close']:.5f}\n24H High: {latest['High']:.5f}\n24H Low: {latest['Low']:.5f}\nVolume: {latest['Volume']}"
        return live_info
    except Exception as e:
        logger.error(f"Market Data Fetch Error: {e}")
        return "حدث خطأ أثناء الاتصال بالأسواق. سيتم الاعتماد على الصورة فقط."

def generate_hybrid_analysis(base_prompt, img, lang):
    if not API_KEYS:
        raise Exception("مفاتيح API مفقودة.")
    
    # 1. استخراج البيانات الحقيقية
    live_data_context = fetch_live_market_data(img, API_KEYS[0])
    logger.info(f"Live Data Extracted: {live_data_context}")
    
    # 2. حقن البيانات في البرومبت
    final_prompt = base_prompt.format(live_data=live_data_context)
    
    last_error = ""
    for key in API_KEYS:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-1.5-pro') # استخدام برو للتحليل المعقد
            response = model.generate_content(
                [final_prompt, img], 
                safety_settings=safety_settings,
                request_options={'timeout': 30}
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = str(e)
            continue
            
    raise Exception(f"فشل التحليل. آخر خطأ: {last_error}")

def process_photo_async(message, lang):
    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img = Image.open(BytesIO(downloaded_file))
        
        analysis_result = generate_hybrid_analysis(TEXTS[lang]['prompt'], img, lang)
        
        # تنظيف وإرسال
        chunks = [analysis_result[i:i+3800] for i in range(0, len(analysis_result), 3800)]
        for idx, chunk in enumerate(chunks):
            if idx == 0:
                bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=chunk, parse_mode='Markdown')
            else:
                bot.send_message(chat_id=message.chat.id, text=chunk, parse_mode='Markdown')
                
        user = get_user(message.chat.id)
        if not user[3]: 
            update_user(message.chat.id, 'trials', user[2] + 1)

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ خطأ: `{e}`")

# === معالجات الأوامر (كما هي) ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    get_user(message.chat.id)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"), InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    bot.reply_to(message, TEXTS['ar']['welcome'], reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_language(call):
    lang = call.data.split('_')[1]
    update_user(call.message.chat.id, 'lang', lang)
    try: bot.delete_message(call.message.chat.id, call.message.message_id)
    except: pass
    bot.send_message(call.message.chat.id, TEXTS[lang]['lang_selected'], reply_markup=get_main_keyboard(lang))

@bot.message_handler(func=lambda m: m.text and ('حسابي' in m.text or 'Account' in m.text))
def account_info(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    sub_status = TEXTS[lang]['active'].format(end=user[5]) if user[3] else TEXTS[lang]['inactive']
    bot.reply_to(message, TEXTS[lang]['account'].format(user_id=message.chat.id, trials=user[2], sub_status=sub_status), parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text and ('الاشتراك' in m.text or 'Subscription' in m.text))
def sub_info(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    bot.reply_to(message, TEXTS[lang]['sub_info'], parse_mode='Markdown')

@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID): return 
    try:
        parts = message.text.split()
        target_user_id, days = int(parts[1]), int(parts[2])
        tz = pytz.timezone('Asia/Riyadh')
        end_date = datetime.datetime.now(tz) + datetime.timedelta(days=days)
        update_user(target_user_id, 'is_sub', 1)
        update_user(target_user_id, 'end_date', end_date.strftime('%Y-%m-%d'))
        bot.reply_to(message, f"✅ تم التفعيل للمستخدم `{target_user_id}` حتى `{end_date.strftime('%Y-%m-%d')}`", parse_mode='Markdown')
        bot.send_message(target_user_id, TEXTS['ar']['activate_success_user'].format(end_date=end_date.strftime('%Y-%m-%d')), parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {e}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    if not user[3] and user[2] >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'])
        return
    threading.Thread(target=process_photo_async, args=(message, lang), daemon=True).start()

@app.route('/', methods=['GET'])
def home(): return "TradeGuard AI Pro Hybrid Edition Active!"

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
            threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        except: pass
        return "OK", 200
    return "Forbidden", 403

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    if RENDER_URL: bot.set_webhook(url=f"{RENDER_URL.rstrip('/')}/{TELEGRAM_TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), threaded=True)
