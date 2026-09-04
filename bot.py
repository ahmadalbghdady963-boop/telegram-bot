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

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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

ALLOWED_FIELDS = {'lang', 'trials', 'is_sub', 'start_date', 'end_date'}

def update_user(user_id, field, value):
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Invalid field: {field}")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

# === نصوص وقوالب اللغات ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI 📈\nمستشارك الذكي لتحليل الأسواق المالية والفوركس.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': (
            "تم اختيار اللغة العربية بنجاح ✅\n\n"
            "📊 **للحصول على أدق تحليل ممكن**، أرسل صورتين معاً في نفس الرسالة (كألبوم واحد):\n"
            "1️⃣ الصورة الأولى: شارت فريم 15 دقيقة (لتحديد الدخول بدقة)\n"
            "2️⃣ الصورة الثانية: شارت فريم 4 ساعات (لتأكيد الاتجاه العام)\n\n"
            "يمكنك أيضاً إرسال صورة واحدة فقط، لكن الدقة تكون أعلى بكثير عند إرسال الفريمين معاً."
        ),
        'wait': '⏳ جاري فحص بنية السوق، السيولة، ومستويات العرض والطلب... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار، يرجى الاشتراك للحصول على وصول غير محدود.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل الفوري:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك فعال الآن ولغاية تاريخ: `{end_date}`.',
        'disclaimer': '\n\n⚠️ *هذا تحليل مبني على الذكاء الاصطناعي وليس توصية مالية مضمونة. لا يوجد تحليل يضمن نتيجة 100%، إدارة رأس المال مسؤوليتك دائماً.*',
        'need_two_hint': "💡 نصيحة: أرسل صورتين معاً (15 دقيقة + 4 ساعات) في نفس الرسالة للحصول على تحليل أدق وأكثر موثوقية.",
        'system_instructions': """أنت محلل أسواق مالية وفوركس مخضرم (CMT) بخبرة مؤسسية تتجاوز 20 عاماً في Price Action وLiquidity وSupply & Demand.

قواعد صارمة:
1. إذا لم تكن أي من الصور شارت تداول مالي/شموع يابانية واضحة، اكتب فقط: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية أو سوق مالي."
2. اعتمد فقط على الشموع والأسعار المرئية فعلياً في الصور، بدون أي افتراضات أو أرقام مختلقة.
3. لا تدّعي أبداً نسبة نجاح 100% - هذا غير واقعي في أي سوق مالي.
4. أخرج التحليل باللغة العربية حصراً، بدون مقدمات أو تكرار، وفق القالب التالي تماماً:

1. هيكل السوق والاتجاه المسيطر:
- (اتجاه فريم 4 الساعات: صاعد/هابط/عرضي + السبب البنيوي)
- (توافق أو تعارض فريم 15 دقيقة مع الاتجاه العام)

2. مناطق السيولة ومستويات العرض والطلب:
- منطقة العرض الرئيسية: (السعر بدقة + السبب الفني)
- منطقة الطلب الرئيسية: (السعر بدقة + السبب الفني)

3. أقوى المقاومات والدعوم:
- المقاومة المحورية: (السعر بدقة)
- الدعم المحوري: (السعر بدقة)

4. تقييم احتمالية الصفقة (Confluence Score):
احسب النسبة وفق هذه المعادلة بدقة واذكر تفصيلها:
- نقطة أساس: 50%
- +15% إذا كان اتجاه الفريمين متوافقاً
- +15% إذا كان السعر عند منطقة سيولة/عرض/طلب قوية
- +10% إذا وُجد كسر هيكل واضح (BOS/CHoCH) يؤكد الاتجاه
- +10% إذا كانت نسبة العائد للمخاطرة حتى TP1 ≥ 1:1.5
- -20% إذا تعارضت إشارات الفريمين
النتيجة النهائية يجب ألا تتجاوز 95% مهما كانت الظروف (لا يوجد يقين مطلق في الأسواق).
اعرض: النسبة النهائية + جدول مختصر يوضح أي من البنود تحقق وأيها لا.

5. الخطة الاستثمارية (Trade Setup):
- القرار: (شراء / بيع / انتظار)
- منطقة الدخول المثالية (Entry Zone): (سعر دقيق)
- وقف الخسارة (SL): ضعه عند أقرب نقطة إبطال فنية حقيقية (Swing point أو حافة Order Block) + هامش بسيط فقط، وليس بعيداً بشكل اعتباطي. اذكر السعر والمسافة بالنقاط عن الدخول.
- أهداف الربح: TP1 (قريب - نسبة عائد للمخاطرة تقريبية)، TP2 (متوسط)، TP3 (بعيد عند أقرب منطقة سيولة/مقاومة كبرى)
- إدارة المخاطر: لا تخاطر بأكثر من 1-2% من رأس المال في الصفقة الواحدة، ويفضل تصفية جزء من الصفقة عند TP1.""",
        'prompt_single': "",  # يُبنى ديناميكياً أدناه
        'prompt_multi': "",
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nYour AI advisor for Forex and Financial Markets.\n\nChoose your language / اختر لغتك:",
        'lang_selected': (
            "English selected ✅\n\n"
            "📊 For the most accurate analysis, send TWO images together in one message (as an album):\n"
            "1️⃣ First image: 15-minute chart (precise entry)\n"
            "2️⃣ Second image: 4-hour chart (trend confirmation)\n\n"
            "A single image also works, but accuracy is significantly higher with both timeframes."
        ),
        'wait': '⏳ Scanning market structure, liquidity, and order blocks... Please wait.',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe for unlimited analysis.',
        'account': '👤 **Your Account**\n\n🆔 User ID: `{user_id}`\n📊 Trials Used: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Pro Plans**\n\n🔹 **10 Days:** $20 (USDT)\n🔹 **Monthly:** $50 (USDT)\n\n📥 **Wallet (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send receipt & ID (`{user_id}`) to activate:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Activated!** Valid until: `{end_date}`.',
        'disclaimer': "\n\n⚠️ *AI-generated analysis, not guaranteed financial advice. No analysis guarantees 100% results — risk management is always your responsibility.*",
        'need_two_hint': "💡 Tip: send two images together (15m + 4h) in one message for higher-accuracy analysis.",
        'system_instructions': """You are a veteran CMT-certified Forex analyst with 20+ years of institutional experience in Price Action, Liquidity, and Supply & Demand.

Strict rules:
1. If any image is not a clear financial candlestick chart, reply ONLY: "⚠️ Sorry, this image is not a candlestick chart or financial market graph."
2. Base everything strictly on visible candles/prices in the images. No invented numbers.
3. NEVER claim 100% success probability - that is unrealistic for any financial market.
4. Output in English only, no preamble, using this exact template:

1. Market Structure & Dominant Trend:
- (4H trend: bullish/bearish/consolidation + structural reason)
- (Does the 15m frame align or conflict with the higher timeframe?)

2. Liquidity & Supply/Demand Zones:
- Key Supply Zone: (exact price + technical reason)
- Key Demand Zone: (exact price + technical reason)

3. Core Support & Resistance:
- Pivot Resistance: (exact price)
- Pivot Support: (exact price)

4. Trade Probability (Confluence Score):
Compute using this exact formula and show your breakdown:
- Base: 50%
- +15% if both timeframes align in trend
- +15% if price is at a strong liquidity/supply/demand zone
- +10% if a clear structure break (BOS/CHoCH) confirms direction
- +10% if reward:risk to TP1 ≥ 1.5:1
- -20% if the two timeframes conflict
Final score must never exceed 95% under any circumstances.
Show: final % + a short table of which criteria were met.

5. Execution & Trade Setup:
- Decision: (Buy / Sell / Wait)
- Optimal Entry Zone: (exact price)
- Stop Loss (SL): place at the nearest real invalidation point (swing point or order block edge) + a small buffer only — never arbitrarily wide. State price and distance in pips from entry.
- Take Profit Targets: TP1 (near, approx R:R), TP2 (mid), TP3 (far, at next major liquidity/resistance zone)
- Risk Management: never risk more than 1-2% of capital per trade; consider partial close at TP1.""",
        'prompt_single': "",
        'prompt_multi': "",
    }
}

for _lang in TEXTS:
    _base = TEXTS[_lang]['system_instructions']
    if _lang == 'ar':
        TEXTS[_lang]['prompt_single'] = _base + "\n\nملاحظة: تم إرسال صورة واحدة فقط (بدون فريم مقارن)، اعتمد عليها حصراً وأشر في نهاية التحليل أن دقة الإشارة ستكون أعلى لو تم إرفاق فريم 4 ساعات."
        TEXTS[_lang]['prompt_multi'] = _base + "\n\nتم إرفاق صورتين: الأولى فريم 15 دقيقة (لحظة الدخول)، الثانية فريم 4 ساعات (السياق العام). حلل التوافق بينهما بدقة قبل إعطاء القرار النهائي."
    else:
        TEXTS[_lang]['prompt_single'] = _base + "\n\nNote: only one image was sent (no comparison timeframe). Use it exclusively and mention at the end that accuracy improves if a 4H chart is also attached."
        TEXTS[_lang]['prompt_multi'] = _base + "\n\nTwo images attached: first = 15m (entry), second = 4H (context). Carefully analyze their alignment before the final decision."

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

# === تنظيف مخرجات الذكاء الاصطناعي ===
def clean_analysis_output(text, target_lang):
    if not text:
        return text
    if target_lang == 'ar':
        if "1. هيكل السوق والاتجاه المسيطر:" in text:
            text = "1. هيكل السوق والاتجاه المسيطر:" + text.split("1. هيكل السوق والاتجاه المسيطر:")[-1]
    else:
        if "1. Market Structure" in text:
            text = "1. Market Structure" + text.split("1. Market Structure")[-1]

    patterns = [
        r'\(Self-Correction.*?\)',
        r'Strict and professional\?.*?\n',
        r'Order followed\?.*?\n',
        r'No fluff\?.*?\n',
        r'Max \d+ words\?.*?\n',
        r'Numbers accurate\?.*?\n',
        r'Wait, looking closer.*?\n',
        r'Final Polish.*?\n',
        r'Resulting analysis:?\n',
    ]
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()

def safe_send_long_text(chat_id, status_message_id, full_text, target_lang='ar'):
    full_text = clean_analysis_output(full_text, target_lang) + TEXTS[target_lang]['disclaimer']
    chunk_size = 3800
    chunks = [full_text[i:i + chunk_size] for i in range(0, len(full_text), chunk_size)]

    for index, chunk in enumerate(chunks):
        try:
            if index == 0:
                bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode='Markdown')
            else:
                bot.send_message(chat_id=chat_id, text=chunk, parse_mode='Markdown')
        except telebot.apihelper.ApiTelegramException as e:
            error_msg = str(e).lower()
            if "can't parse entities" in error_msg or "400" in error_msg:
                try:
                    if index == 0:
                        bot.edit_message_text(chat_id=chat_id, message_id=status_message_id, text=chunk, parse_mode=None)
                    else:
                        bot.send_message(chat_id=chat_id, text=chunk, parse_mode=None)
                except Exception as inner_e:
                    logger.error(f"Fallback failed: {inner_e}")
            else:
                logger.error(f"Send error: {e}")

# === كاش النماذج المتاحة (بدل استدعاء list_models في كل رسالة) ===
_model_cache = {'models': [], 'ts': 0}
MODEL_CACHE_TTL = 3600
FALLBACK_MODELS = ['models/gemini-2.5-flash', 'models/gemini-2.0-flash', 'models/gemini-1.5-flash', 'models/gemini-1.5-pro']

def get_available_models():
    now = time.time()
    if _model_cache['models'] and (now - _model_cache['ts'] < MODEL_CACHE_TTL):
        return _model_cache['models']
    try:
        models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        vision_models = [m for m in models if 'vision' not in m or 'flash' in m or 'pro' in m]
        ordered = sorted(vision_models, key=lambda x: ('flash' not in x, 'pro' not in x))
        if ordered:
            _model_cache['models'] = ordered
            _model_cache['ts'] = now
            return ordered
    except Exception as e:
        logger.error(f"Error listing models: {e}")
    if not _model_cache['models']:
        _model_cache['models'] = FALLBACK_MODELS
        _model_cache['ts'] = now
    return _model_cache['models']

def generate_chart_analysis(parts):
    models = get_available_models()
    if not models:
        raise Exception("لا يوجد نموذج ذكاء اصطناعي متاح حالياً.")
    last_err = None
    for model_name in models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(parts, safety_settings=safety_settings)
            if response and response.text:
                return response.text
        except Exception as e:
            last_err = e
            logger.warning(f"Model {model_name} failed: {e}")
            continue
    raise Exception(f"تعذر تحليل الصورة، يرجى المحاولة لاحقاً. ({last_err})")

# === تجميع صور الألبوم (فريمين معاً) ===
pending_albums = {}
albums_lock = threading.Lock()
ALBUM_WAIT_SECONDS = 2.5

def process_album(media_group_id):
    with albums_lock:
        album = pending_albums.pop(media_group_id, None)
    if not album:
        return

    chat_id = album['chat_id']
    lang = album['lang']
    status_msg_id = album['status_msg_id']
    trials = album['trials']
    is_sub = album['is_sub']
    photos = sorted(album['photos'], key=lambda x: x[0])[:2]

    try:
        images = []
        for _, file_id in photos:
            file_info = bot.get_file(file_id)
            downloaded = bot.download_file(file_info.file_path)
            images.append(Image.open(BytesIO(downloaded)))

        if len(images) == 1:
            parts = [TEXTS[lang]['prompt_single'], images[0]]
        else:
            parts = [TEXTS[lang]['prompt_multi'], "Chart 1 - Lower Timeframe (Entry):", images[0], "Chart 2 - Higher Timeframe (Trend):", images[1]]

        analysis_result = generate_chart_analysis(parts)
        safe_send_long_text(chat_id, status_msg_id, analysis_result, target_lang=lang)

        if not is_sub:
            update_user(chat_id, 'trials', trials + 1)
    except Exception as e:
        logger.error(f"Album processing error: {traceback.format_exc()}")
        safe_send_long_text(chat_id, status_msg_id, f"❌ تعذر استكمال التحليل.\nالسبب: `{e}`", target_lang=lang)

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
    bot.send_message(call.message.chat.id, TEXTS[lang]['lang_selected'], reply_markup=get_main_keyboard(lang), parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text and ('حسابي' in m.text or 'Account' in m.text or m.text == '/my_account'))
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, end_date = user[1], user[2], user[3], user[5]
    if lang not in TEXTS:
        lang = 'ar'
    sub_status = TEXTS[lang]['active'].format(end=end_date) if is_sub else TEXTS[lang]['inactive']
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
        start_date = datetime.datetime.now(tz)
        end_date = start_date + datetime.timedelta(days=days)

        target_user = get_user(target_user_id)
        target_lang = target_user[1] if target_user[1] in TEXTS else 'ar'

        update_user(target_user_id, 'is_sub', 1)
        update_user(target_user_id, 'start_date', start_date.strftime('%Y-%m-%d'))
        update_user(target_user_id, 'end_date', end_date.strftime('%Y-%m-%d'))

        bot.reply_to(message, f"✅ **تم التفعيل بنجاح!**\n👤 المستخدم: `{target_user_id}`\n📅 المدة: {days} يوم\n📅 الانتهاء: `{end_date.strftime('%Y-%m-%d')}`", parse_mode='Markdown')

        user_msg = TEXTS[target_lang]['activate_success_user'].format(end_date=end_date.strftime('%Y-%m-%d'))
        bot.send_message(target_user_id, user_msg, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: استخدم الصيغة الصحيحة تماماً:\n`/activate <USER_ID> <DAYS>`\n({e})")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not GEMINI_API_KEY:
        bot.reply_to(message, "❌ مفتاح GEMINI_API_KEY غير مضاف في إعدادات السيرفر.")
        return

    user = get_user(message.chat.id)
    lang = user[1] if user[1] in TEXTS else 'ar'
    trials, is_sub, end_date_str = user[2], user[3], user[5]

    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        try:
            if datetime.datetime.now(tz) > datetime.datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=tz):
                update_user(message.chat.id, 'is_sub', 0)
                is_sub = 0
        except Exception:
            pass

    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'], parse_mode='Markdown')
        return

    file_id = message.photo[-1].file_id

    if message.media_group_id:
        mgid = message.media_group_id
        with albums_lock:
            if mgid not in pending_albums:
                status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
                pending_albums[mgid] = {
                    'chat_id': message.chat.id,
                    'lang': lang,
                    'status_msg_id': status_msg.message_id,
                    'trials': trials,
                    'is_sub': is_sub,
                    'photos': [],
                    'timer': None,
                }
            pending_albums[mgid]['photos'].append((message.message_id, file_id))
            if pending_albums[mgid]['timer']:
                pending_albums[mgid]['timer'].cancel()
            t = threading.Timer(ALBUM_WAIT_SECONDS, process_album, args=(mgid,))
            pending_albums[mgid]['timer'] = t
            t.start()
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    try:
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        img = Image.open(BytesIO(downloaded_file))

        analysis_result = generate_chart_analysis([TEXTS[lang]['prompt_single'], img])
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang)
        bot.send_message(message.chat.id, TEXTS[lang]['need_two_hint'])

        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        safe_send_long_text(message.chat.id, status_msg.message_id, f"❌ تعذر استكمال التحليل.\nالسبب: `{e}`", target_lang=lang)

# === تشغيل السيرفر والـ Webhook ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI Pro V12.0 Active & Operational!"

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
