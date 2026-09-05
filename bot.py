import os
import time
import sqlite3
import datetime
import pytz
import logging
import traceback
import re
import base64
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from io import BytesIO
from PIL import Image

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import yfinance as yf
except ImportError:
    yf = None

# === إعداد نظام المراقبة ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات النظام ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات Render.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# عميل Groq يُستخدم كخط دعم احتياطي (fallback) عندما يتعذر الوصول لـ Gemini
# (مثلاً بسبب مشاكل مصادقة من طرف جوجل مثل مفاتيح AQ. الجديدة).
groq_client = Groq(api_key=GROQ_API_KEY) if (GROQ_API_KEY and Groq) else None
GROQ_VISION_MODELS = [
    'meta-llama/llama-4-scout-17b-16e-instruct',
    'meta-llama/llama-4-maverick-17b-128e-instruct',
]

# طبقة ثالثة مجانية اختيارية: OpenRouter — راوتر تلقائي يوزّع الطلبات على أكثر
# من 18 نموذجاً مجانياً يدعم الصور، فيتجاوز عملياً سقف أي مزود واحد بمفرده.
# للتفعيل: أنشئ حساباً مجانياً بدون بطاقة على openrouter.ai/keys وأضف القيمة
# في متغير البيئة OPENROUTER_API_KEY على Render. إن لم تُضف القيمة، تُتخطى
# هذه الطبقة تلقائياً دون أي خطأ.
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
OPENROUTER_MODEL = 'openrouter/free'

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
            "💎 **الأهم**: أضف اسم الأداة ككتابة (Caption) على إحدى الصورتين قبل الإرسال (مثل XAUUSD أو EURUSD)، "
            "ليجلب البوت أسعاراً حقيقية فعلية من السوق ويتحقق منها بدل تخمينها من الصورة فقط.\n\n"
            "يمكنك أيضاً إرسال صورة واحدة فقط، لكن الدقة تكون أعلى بكثير عند إرسال الفريمين معاً مع اسم الأداة."
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
        'symbol_tip': "💡 لرفع الدقة أكثر: أضف اسم الأداة ككتابة (Caption) على الصورة قبل الإرسال، مثل XAUUSD أو EURUSD أو BTCUSD، ليتحقق البوت من أسعار حقيقية فعلية بدل الاعتماد على قراءة الصورة فقط.",
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
            "💎 **Most important**: add the instrument name as a caption on one of the photos before sending "
            "(e.g. XAUUSD or EURUSD), so the bot fetches real live prices to verify against, instead of guessing from the image alone.\n\n"
            "A single image also works, but accuracy is significantly higher with both timeframes plus the symbol."
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
        'symbol_tip': "💡 For higher accuracy: add the instrument name as a photo caption before sending, e.g. XAUUSD, EURUSD, or BTCUSD, so the bot can verify against real live prices instead of relying on image reading alone.",
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

def _pil_to_data_uri(img, fmt='JPEG'):
    buf = BytesIO()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buf, format=fmt, quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f"data:image/jpeg;base64,{b64}"

def _build_openai_style_content(parts):
    content = []
    for p in parts:
        if isinstance(p, Image.Image):
            content.append({"type": "image_url", "image_url": {"url": _pil_to_data_uri(p)}})
        else:
            content.append({"type": "text", "text": str(p)})
    return content

def _try_gemini(parts):
    """يحاول التحليل عبر Gemini. يرجع النص عند النجاح أو None عند الفشل."""
    if not GEMINI_API_KEY:
        return None, None
    models = get_available_models()
    last_err = None
    for model_name in models:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(parts, safety_settings=safety_settings)
            if response and response.text:
                return response.text, None
        except Exception as e:
            last_err = e
            logger.warning(f"Gemini model {model_name} failed: {e}")
            continue
    return None, last_err

def _try_groq(parts):
    """يحاول التحليل عبر Groq (خط احتياطي أول). يرجع النص عند النجاح أو None عند الفشل."""
    if not groq_client:
        return None, None
    messages = [{"role": "user", "content": _build_openai_style_content(parts)}]
    last_err = None
    for model_name in GROQ_VISION_MODELS:
        try:
            completion = groq_client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.3,
                max_tokens=2500,
            )
            text = completion.choices[0].message.content
            if text:
                return text, None
        except Exception as e:
            last_err = e
            logger.warning(f"Groq model {model_name} failed: {e}")
            continue
    return None, last_err

def _try_openrouter(parts):
    """يحاول التحليل عبر OpenRouter (خط احتياطي ثانٍ، مجاني بالكامل). يرجع النص أو None."""
    if not OPENROUTER_API_KEY:
        return None, None
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": _build_openai_style_content(parts)}],
                "temperature": 0.3,
                "max_tokens": 2500,
            },
            timeout=60,
        )
        data = resp.json()
        text = data.get('choices', [{}])[0].get('message', {}).get('content')
        if text:
            return text, None
        return None, data.get('error', resp.text)
    except Exception as e:
        logger.warning(f"OpenRouter failed: {e}")
        return None, e

def generate_chart_analysis(parts):
    if not GEMINI_API_KEY and not groq_client and not OPENROUTER_API_KEY:
        raise Exception("لا يوجد أي مزود ذكاء اصطناعي مُهيّأ (GEMINI_API_KEY أو GROQ_API_KEY أو OPENROUTER_API_KEY).")

    text, gemini_err = _try_gemini(parts)
    if text:
        return text
    if gemini_err:
        logger.warning(f"Gemini غير متاح، جاري التحويل إلى Groq. السبب: {gemini_err}")

    text, groq_err = _try_groq(parts)
    if text:
        return text
    if groq_err:
        logger.warning(f"Groq غير متاح، جاري التحويل إلى OpenRouter. السبب: {groq_err}")

    text, or_err = _try_openrouter(parts)
    if text:
        return text

    raise Exception(f"تعذر تحليل الصورة عبر جميع المزودين. Gemini: {gemini_err} | Groq: {groq_err} | OpenRouter: {or_err}")

# === بيانات سعرية حقيقية للتحقق من دقة القراءة البصرية ===
# المشكلة الجذرية في "تحليل صورة شارت": النموذج البصري يُخمّن الأسعار من مواقع
# البكسلات على الشارت، وهذا عرضة للخطأ دائماً مهما تحسّن الـ Prompt.
# الحل: نجلب بيانات سعرية حقيقية ومؤكدة من Yahoo Finance (مجاني تماماً، بدون
# مفتاح API وبدون حد استخدام يومي مقلق لحجم استخدام شخصي) ونمررها للنموذج
# كأرقام موثوقة، ونجعل مهمة الصورة الاكتفاء بتأكيد الشكل والبنية والزخم.
COMMON_TICKERS = {
    'XAUUSD': 'XAUUSD=X', 'GOLD': 'XAUUSD=X', 'GC': 'XAUUSD=X', 'ذهب': 'XAUUSD=X',
    'XAGUSD': 'XAGUSD=X', 'SILVER': 'XAGUSD=X', 'فضة': 'XAGUSD=X',
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'NZDUSD': 'NZDUSD=X', 'USDCHF': 'USDCHF=X',
    'EURJPY': 'EURJPY=X', 'GBPJPY': 'GBPJPY=X',
    'BTCUSD': 'BTC-USD', 'BTC': 'BTC-USD', 'بيتكوين': 'BTC-USD',
    'ETHUSD': 'ETH-USD', 'ETH': 'ETH-USD',
    'US30': '^DJI', 'NAS100': '^NDX', 'SPX500': '^GSPC', 'GER40': '^GDAXI', 'UK100': '^FTSE',
}

def _resolve_ticker(symbol_text):
    if not symbol_text:
        return None
    key = re.sub(r'[^A-Za-z0-9]', '', symbol_text).upper()
    if key in COMMON_TICKERS:
        return COMMON_TICKERS[key]
    if len(key) == 6 and key.isalpha():
        return key + '=X'
    return None

def fetch_market_snapshot(symbol_text):
    """يجلب بيانات سعرية حقيقية (OHLC حقيقية من Yahoo Finance) لدعم دقة التحليل.
    يرجع نص ملخص جاهز للحقن في الـ prompt، أو None إن تعذر التعرف على الرمز أو الجلب."""
    ticker = _resolve_ticker(symbol_text)
    if not ticker or not yf:
        return None
    try:
        data = yf.download(ticker, period='5d', interval='1h', progress=False, auto_adjust=True)
        if data is None or data.empty or len(data) < 15:
            return None
        highs = data['High'].squeeze()
        lows = data['Low'].squeeze()
        closes = data['Close'].squeeze()

        last_price = float(closes.iloc[-1])
        true_range = (highs - lows).abs()
        atr = float(true_range.rolling(14).mean().iloc[-1])

        recent = data.tail(60)
        swing_highs = sorted(set(recent['High'].squeeze().nlargest(3).round(4).tolist()), reverse=True)
        swing_lows = sorted(set(recent['Low'].squeeze().nsmallest(3).round(4).tolist()))

        return (
            f"[بيانات سعرية حقيقية موثقة من Yahoo Finance للرمز {ticker} - فريم ساعة]\n"
            f"- آخر سعر إغلاق مسجل فعلياً: {last_price:.4f}\n"
            f"- متوسط مدى التقلب الحقيقي ATR(14): {atr:.4f}\n"
            f"- أبرز القمم السعرية الحديثة (مرشحات مقاومة حقيقية): {swing_highs}\n"
            f"- أبرز القيعان السعرية الحديثة (مرشحات دعم حقيقي): {swing_lows}\n"
            f"تعليمة إلزامية: اعتمد على هذه الأرقام الحقيقية كمرجع أساسي لأي سعر تذكره في "
            f"التحليل (الدعم/المقاومة/الدخول/الوقف/الأهداف)، ولا تخترع رقماً يخالفها. "
            f"استخدم الصورتين فقط لتأكيد شكل الشموع والبنية والزخم اللحظي، وليس لقراءة الأرقام."
        )
    except Exception as e:
        logger.warning(f"Market data fetch failed for {symbol_text} ({ticker}): {e}")
        return None

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
    symbol_caption = album.get('symbol_caption')
    photos = sorted(album['photos'], key=lambda x: x[0])[:2]

    try:
        images = []
        for _, file_id in photos:
            file_info = bot.get_file(file_id)
            downloaded = bot.download_file(file_info.file_path)
            images.append(Image.open(BytesIO(downloaded)))

        base_prompt = TEXTS[lang]['prompt_single'] if len(images) == 1 else TEXTS[lang]['prompt_multi']
        snapshot = fetch_market_snapshot(symbol_caption)
        prompt_text = base_prompt + ("\n\n" + snapshot if snapshot else "")

        if len(images) == 1:
            parts = [prompt_text, images[0]]
        else:
            parts = [prompt_text, "Chart 1 - Lower Timeframe (Entry):", images[0], "Chart 2 - Higher Timeframe (Trend):", images[1]]

        analysis_result = generate_chart_analysis(parts)
        safe_send_long_text(chat_id, status_msg_id, analysis_result, target_lang=lang)
        if not snapshot:
            bot.send_message(chat_id, TEXTS[lang]['symbol_tip'])

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
    if not GEMINI_API_KEY and not groq_client and not OPENROUTER_API_KEY:
        bot.reply_to(message, "❌ لا يوجد أي مفتاح ذكاء اصطناعي مُفعّل في إعدادات السيرفر.")
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
                    'symbol_caption': None,
                    'timer': None,
                }
            if message.caption and not pending_albums[mgid]['symbol_caption']:
                pending_albums[mgid]['symbol_caption'] = message.caption
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

        snapshot = fetch_market_snapshot(message.caption)
        prompt_text = TEXTS[lang]['prompt_single'] + ("\n\n" + snapshot if snapshot else "")
        analysis_result = generate_chart_analysis([prompt_text, img])
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang)
        bot.send_message(message.chat.id, TEXTS[lang]['need_two_hint'])
        if not snapshot:
            bot.send_message(message.chat.id, TEXTS[lang]['symbol_tip'])

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
