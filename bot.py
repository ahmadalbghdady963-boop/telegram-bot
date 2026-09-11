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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
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
    'qwen/qwen3.8-27b',
    'qwen/qwen3.6-27b',
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
        'lang_selected': (
            "مرحباً بك في TradeGuard AI 📈\n"
            "مستشارك الذكي لتحليل الأسواق المالية والفوركس.\n\n"
            "📊 **للحصول على أدق تحليل ممكن**، أرسل الصور معاً في نفس الرسالة (كألبوم واحد)، **بهذا الترتيب تحديداً**:\n"
            "1️⃣ الصورة الأولى: شارت فريم 15 دقيقة (لتحديد الدخول بدقة)\n"
            "2️⃣ الصورة الثانية: شارت فريم 4 ساعات (المنطقة والسياق)\n"
            "3️⃣ (اختياري) الصورة الثالثة: شارت الفريم اليومي D1 (لتأكيد الاتجاه العام الأكبر وتجنب الدخول عكسه)\n\n"
            "💎 **الأهم**: أضف اسم الأداة ككتابة (Caption) على إحدى الصور قبل الإرسال (مثل XAUUSD أو EURUSD)، "
            "ليجلب البوت أسعاراً حقيقية فعلية من السوق ويتحقق منها بدل تخمينها من الصورة فقط.\n\n"
            "يمكنك أيضاً إرسال صورة واحدة فقط، لكن الدقة تزداد مع كل فريم إضافي تُرفقه بنفس الترتيب أعلاه."
        ),
        'wait': '⏳ جاري فحص بنية السوق، السيولة، ومستويات العرض والطلب... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار، يرجى الاشتراك للحصول على وصول غير محدود.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل الفوري:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك فعال الآن ولغاية تاريخ: `{end_date}`.',
        'disclaimer': '\n\n⚠️ *هذا تحليل مبني على الذكاء الاصطناعي وليس توصية مالية مضمونة. لا يوجد تحليل يضمن نتيجة 100%، إدارة رأس المال مسؤوليتك دائماً.*',
        'need_two_hint': "💡 نصيحة: أرسل صورتين أو ثلاثاً معاً بالترتيب (15 دقيقة ثم 4 ساعات ثم يومي اختياري) في نفس الرسالة للحصول على تحليل أدق وأكثر موثوقية.",
        'symbol_tip': "💡 لرفع الدقة أكثر: أضف اسم الأداة ككتابة (Caption) على الصورة قبل الإرسال، مثل XAUUSD أو EURUSD أو BTCUSD، ليتحقق البوت من أسعار حقيقية فعلية بدل الاعتماد على قراءة الصورة فقط.",
        'system_instructions': """أنت محلل أسواق مالية وفوركس مخضرم (CMT) بخبرة مؤسسية تتجاوز 20 عاماً في Price Action وLiquidity وSupply & Demand.

التزم بالإيجاز الشديد في كل نقطة (جملة إلى جملتين كحد أقصى لكل بند فرعي، بدون حشو أو تكرار) مع الحفاظ الكامل على القالب والبنود الخمسة أدناه دون حذف أي منها — هذا يضمن وصول التحليل كاملاً دون انقطاع بسبب طول الرد.

قواعد صارمة:
1. الصور المرفقة قد تكون لقطات شاشة كاملة من منصات تداول حقيقية (مثل MetaTrader 4/5، TradingView، تطبيقات وسطاء) وتحتوي عناصر واجهة إضافية حول الشارت نفسه (أسعار Buy/Sell، حجم اللوت، أزرار، خلفيات، علامات مائية) — هذا لا يعني أنها ليست شارتاً مالياً؛ ابحث عن الشموع اليابانية ومحور الأسعار داخل الصورة بعناية حتى لو كانت محاطة بعناصر واجهة أخرى. **ارفض فقط** إذا كانت الصورة بلا أي شك لا علاقة لها إطلاقاً بأي شارت مالي (مثل صورة شخصية، ميم، أو نص عشوائي) — في هذه الحالة فقط اكتب حرفياً: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية أو سوق مالي."
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
احسب النسبة وفق هذه المعادلة بدقة، والبنود التالية **حصرية** (لا يجوز احتساب نفس الإشارة في أكثر من بند واحد):
- نقطة أساس: 50%
- اتجاه الفريمين: **إما** +15% إذا كان الفريمان متوافقين تماماً، **أو** -20% إذا تعارضا (اختر واحداً فقط منهما، لا الاثنين معاً)
- +15% إذا كان السعر عند منطقة سيولة/عرض/طلب قوية
- +10% فقط إذا وُجد كسر هيكل واضح (BOS/CHoCH) على نفس اتجاه الفريم الأكبر ويؤكده (وليس كسراً معاكساً له - الكسر المعاكس يدخل ضمن بند "التعارض" أعلاه فقط، لا يُحتسب هنا مرة أخرى)
- +10% إذا كانت نسبة العائد للمخاطرة حتى TP1 ≥ 1:1.5
النتيجة النهائية يجب ألا تتجاوز 95% مهما كانت الظروف (لا يوجد يقين مطلق في الأسواق).
قبل كتابة النتيجة النهائية، ابحث فعلياً عن أقوى سبب فني قد يجعل هذه الصفقة تفشل (حتى لو كانت الأغلبية تدعم الصفقة) واذكره صراحة في سطر منفصل باسم "أضعف نقطة في هذا التحليل:" — إذا لم تجد أي ضعف حقيقي بعد بحث جاد، فهذا نادر جداً ويستحق الشك بدل الثقة الكاملة.
تعليمة إلزامية: إذا كانت "أضعف نقطة" تصف خطراً قريباً ومحدداً (مثل احتمال ارتداد عكسي أو Pullback قبل استئناف الاتجاه)، يجب أن ينعكس هذا فعلياً على القرار في البند 5 أدناه — لا تكتفِ بذكره كملاحظة جانبية ثم توصي بدخول فوري داخل نفس منطقة الخطر تلك. بدلاً من ذلك: إما أوصِ بالانتظار (Wait) مع تحديد الإشارة أو المستوى الذي يجب تأكيده أولاً قبل الدخول، أو اجعل الدخول أمراً معلقاً عند سعر يقع فعلياً بعد نهاية الحركة المعاكسة المتوقعة، لا داخلها.
اعرض: النسبة النهائية + جدول مختصر يوضح أي من البنود تحقق وأيها لا، مع التأكد أن مجموع البنود يطابق الحساب الحسابي فعلياً دون ازدواج.

5. الخطة الاستثمارية (Trade Setup):
- القرار: (شراء / بيع / انتظار) — يجب أن يتوافق مع تعليمة الربط بـ"أضعف نقطة" أعلاه.
- منطقة الدخول المثالية (Entry Zone): (سعر دقيق)
- نوع الأمر: قارن سعر الدخول المثالي بالسعر الحالي الفعلي صراحة، ثم حدد: **"أمر فوري (Market)"** فقط إذا كان السعر الحالي عند منطقة الدخول بالفعل مع تأكيد واضح الآن ولم تُحدَّد أي منطقة خطر قريبة في "أضعف نقطة"، أو **"أمر معلق (Buy Limit / Sell Limit / Buy Stop / Sell Stop)"** إذا كانت منطقة الدخول المثالية تبعد عن السعر الحالي أو إذا حذّرت "أضعف نقطة" من حركة معاكسة قريبة — في هذه الحالة انتظر وصول السعر إليها بدل ملاحقته، واذكر نوع الأمر المعلق الصحيح تحديداً (Limit إذا كان الدخول عند ارتداد من منطقة أبعد وأسوأ سعرياً من السعر الحالي، Stop إذا كان الدخول يتطلب تأكيد اختراق فوق/تحت السعر الحالي).
- وقف الخسارة (SL): ضعه عند أقرب نقطة إبطال فنية حقيقية (Swing point أو حافة Order Block) + هامش بسيط فقط، وليس بعيداً بشكل اعتباطي ولا مساوياً تماماً لسعر تلك المنطقة بلا أي هامش. اذكر السعر والمسافة بالنقاط عن الدخول.
- أهداف الربح: TP1 (قريب - نسبة عائد للمخاطرة تقريبية)، TP2 (متوسط)، TP3 (بعيد عند أقرب منطقة سيولة/مقاومة كبرى)
- إدارة المخاطر: لا تخاطر بأكثر من 1-2% من رأس المال في الصفقة الواحدة، ويفضل تصفية جزء من الصفقة عند TP1.

تعليمة إلزامية أخيرة: إذا كان القرار شراء أو بيع، أنهِ رسالتك بالكامل بسطر واحد فقط بهذا الشكل الحرفي بالضبط (بدون أي نص إضافي على نفس السطر، وبنفس الأرقام العشرية المستخدمة في التحليل):
#DATA# DECISION=<BUY أو SELL> ENTRY=<رقم> SL=<رقم> TP1=<رقم> TP2=<رقم> TP3=<رقم>
إذا كان القرار انتظار (Wait)، اكتب بدلاً منه: #DATA# NONE""",
        'prompt_single': "",  # يُبنى ديناميكياً أدناه
        'prompt_multi': "",
    }
}

for _lang in TEXTS:
    _base = TEXTS[_lang]['system_instructions']
    TEXTS[_lang]['prompt_single'] = _base + "\n\nملاحظة: تم إرسال صورة واحدة فقط (بدون فريم مقارن)، اعتمد عليها حصراً وأشر في نهاية التحليل أن دقة الإشارة ستكون أعلى لو تم إرفاق فريم 4 ساعات."
    TEXTS[_lang]['prompt_multi'] = _base + "\n\nتم إرفاق صورتين: الأولى فريم 15 دقيقة (لحظة الدخول)، الثانية فريم 4 ساعات (السياق العام). حلل التوافق بينهما بدقة قبل إعطاء القرار النهائي."
    TEXTS[_lang]['prompt_triple'] = _base + (
        "\n\nتم إرفاق ثلاث صور: الأولى فريم 15 دقيقة (لحظة الدخول)، الثانية فريم 4 ساعات (المنطقة والسياق المتوسط)، "
        "الثالثة فريم يومي D1 (الاتجاه العام الأكبر). اعتبر الفريم اليومي المرجع الأعلى أولوية بين الثلاثة: "
        "إذا كان الاتجاه اليومي يعارض بوضوح اتجاه فريم 4 الساعات، اذكر هذا التعارض صراحة ضمن \"أضعف نقطة في هذا التحليل\" "
        "وطبّق عليه نفس تعليمة الحذر الإلزامية (انتظار أو أمر معلق بعد تأكيد إضافي)، حتى لو بدت إشارة فريم 4 الساعات وحدها ممتازة."
    )

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

    # حماية إضافية: بعض النماذج الأصغر (مثل Qwen عبر Groq) قد تكرر سطراً طويلاً
    # مباشرة بعد نفسه أحياناً (لوحظ فعلياً في الإنتاج) — نحذف أي تكرار متتالٍ فوري.
    paragraphs = re.split(r'\n\s*\n', cleaned)
    deduped_paragraphs = []
    for para in paragraphs:
        p_stripped = para.strip()
        if deduped_paragraphs and p_stripped and len(p_stripped) > 15 and p_stripped == deduped_paragraphs[-1].strip():
            continue
        deduped_paragraphs.append(para)
    cleaned = '\n\n'.join(deduped_paragraphs)

    lines = cleaned.split('\n')
    deduped = []
    for line in lines:
        stripped = line.strip()
        if deduped and stripped and len(stripped) > 5 and stripped == deduped[-1].strip():
            continue
        deduped.append(line)
    cleaned = '\n'.join(deduped)

    return cleaned.strip()

SUMMARY_LABELS = {
    'ar': {
        'title': '📋 ملخص سريع للصفقة (محسوب آلياً وموثق):',
        'decision': 'القرار', 'buy': '🟢 شراء', 'sell': '🔴 بيع',
        'entry': '📍 الدخول', 'sl': '🛑 الوقف', 'dist': 'مسافة السعر',
    },
}

def verify_and_append_rr(text, target_lang):
    """يبحث عن سطر #DATA# الذي يُخرجه النموذج، يحذفه من النص الظاهر للمستخدم،
    ثم يبني صندوق ملخص سريع (القرار + الدخول + الوقف + الأهداف الثلاثة) بأرقام
    محسوبة رياضياً بدقة تامة في الكود بدل الاعتماد على حساب النموذج النصي لها
    (أثبتت أمثلة حقيقية أنه عرضة لخطأ صغير متكرر) — ليسهل إيجادها دون قراءة
    التحليل الكامل بالكامل."""
    if not text:
        return text
    match = re.search(r'#DATA#\s*(.*)', text)
    if not match:
        return text
    data_line = match.group(1).strip()
    text = text[:match.start()].rstrip()

    if data_line.upper().startswith('NONE'):
        return text

    nums = {k.upper(): v for k, v in re.findall(r'(ENTRY|SL|TP1|TP2|TP3)\s*=\s*([\d.]+)', data_line, flags=re.IGNORECASE)}
    decision_match = re.search(r'DECISION\s*=\s*(BUY|SELL)', data_line, flags=re.IGNORECASE)
    try:
        entry = float(nums['ENTRY'])
        sl = float(nums['SL'])
    except (KeyError, ValueError):
        return text

    risk = abs(entry - sl)
    if risk == 0:
        return text

    L = SUMMARY_LABELS.get(target_lang, SUMMARY_LABELS['ar'])
    lines = [L['title']]
    if decision_match:
        lines.append(f"{L['decision']}: {L['buy'] if decision_match.group(1).upper() == 'BUY' else L['sell']}")
    lines.append(f"{L['entry']}: {entry}")
    lines.append(f"{L['sl']}: {sl} ({L['dist']}: {risk:.4f})")
    tp1_ratio = None
    for tp_key in ('TP1', 'TP2', 'TP3'):
        if tp_key in nums:
            try:
                tp_val = float(nums[tp_key])
                reward = abs(tp_val - entry)
                ratio = reward / risk
                lines.append(f"🎯 {tp_key}: {tp_val} ← 1:{ratio:.2f}")
                if tp_key == 'TP1':
                    tp1_ratio = ratio
            except ValueError:
                continue

    if tp1_ratio is not None:
        rr_ok = tp1_ratio >= 1.5
        if rr_ok:
            lines.append("✅ معيار +10% (R:R لـTP1 ≥ 1.5) محقق فعلياً وفق الأرقام أعلاه.")
        else:
            lines.append(f"❌ تحقق آلي: معيار +10% (R:R لـTP1 ≥ 1.5) **غير محقق فعلياً** — النسبة الحقيقية 1:{tp1_ratio:.2f} فقط. إن ادّعى التحليل أدناه أن هذا المعيار تحقق، فهذا خطأ ويجب تجاهله والاعتماد على هذا الرقم المحسوب.")

    if len(lines) <= 3:
        return text
    return "\n".join(lines) + "\n\n" + text


def safe_send_long_text(chat_id, status_message_id, full_text, target_lang='ar', prefix_note=None, resolved_symbol=None):
    full_text = clean_analysis_output(full_text, target_lang)
    full_text = verify_and_append_rr(full_text, target_lang)
    if resolved_symbol:
        tag = f"🏷️ الأداة المتعرف عليها: {resolved_symbol}" if target_lang == 'ar' else f"🏷️ Recognized instrument: {resolved_symbol}"
        full_text = tag + "\n\n" + full_text
    if prefix_note:
        full_text = prefix_note + "\n\n" + full_text
    full_text = full_text + TEXTS[target_lang]['disclaimer']
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
                max_tokens=900,
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

# === تنبيه مخاطر الأخبار الاقتصادية (طبقة اختيارية جديدة) ===
# مهما كان التحليل الفني دقيقاً، بيانات اقتصادية عالية التأثير (فائدة، تضخم،
# وظائف) يمكن أن تُحدث قفزة سعرية تخترق أي وقف خسارة محسوب بدقة فنية تامة.
# هذه طبقة اختيارية بالكامل (تُفعَّل فقط عند إضافة ECONOMIC_CALENDAR_API_KEY)
# ولا تُعطّل أي شيء إن لم تُفعَّل. المصدر: jblanked.com (خطة مجانية محدودة
# بطلب واحد يومياً تقريباً، لذا نخزّن النتيجة يومياً بدل طلبها مع كل تحليل).
ECONOMIC_CALENDAR_API_KEY = os.environ.get('ECONOMIC_CALENDAR_API_KEY', '')
_econ_cache = {'events': None, 'ts': 0}
ECON_CACHE_TTL = 20 * 3600

def _get_high_impact_events_today():
    if not ECONOMIC_CALENDAR_API_KEY:
        return None
    now = time.time()
    if _econ_cache['events'] is not None and (now - _econ_cache['ts'] < ECON_CACHE_TTL):
        return _econ_cache['events']
    try:
        resp = requests.get(
            "https://www.jblanked.com/news/api/forex-factory/calendar/today/",
            headers={"Authorization": f"Api-Key {ECONOMIC_CALENDAR_API_KEY}", "Content-Type": "application/json"},
            params={"impact": "High"},
            timeout=15,
        )
        if resp.status_code == 200:
            events = resp.json()
            if isinstance(events, list):
                _econ_cache['events'] = events
                _econ_cache['ts'] = now
                return events
    except Exception as e:
        logger.warning(f"Economic calendar fetch failed: {e}")
    return _econ_cache['events']

def _currencies_from_ticker(ticker):
    if not ticker:
        return []
    if ticker.endswith('=X') and len(ticker) == 8:
        base = ticker[:6]
        return [base[:3], base[3:]]
    if ticker in ('XAUUSD=X', 'XAGUSD=X', 'BTC-USD', 'ETH-USD', '^DJI', '^NDX', '^GSPC'):
        return ['USD']
    if ticker == '^GDAXI':
        return ['EUR']
    if ticker == '^FTSE':
        return ['GBP']
    return []

def check_news_risk(symbol_text, lang):
    """يتحقق من وجود بيانات اقتصادية عالية التأثير اليوم لعملات الأداة المطلوبة.
    يرجع نص تنبيه أو None (بصمت) إن لم يوجد مفتاح، أو لم يتعرف على الرمز، أو لا يوجد خطر."""
    ticker = _resolve_ticker(symbol_text)
    currencies = _currencies_from_ticker(ticker)
    if not currencies:
        return None
    events = _get_high_impact_events_today()
    if not events:
        return None
    try:
        matches = [e for e in events if e.get('Currency') in currencies and str(e.get('Impact', '')).lower() == 'high']
    except Exception:
        return None
    if not matches:
        return None

    if lang == 'ar':
        lines = ["⚠️ **تنبيه: بيانات اقتصادية عالية التأثير اليوم**"]
        for e in matches[:3]:
            lines.append(f"- {e.get('Currency')}: {e.get('Name')} ({e.get('Date')})")
        lines.append("قد تُحدث هذه البيانات تقلبات حادة تخترق أي وقف خسارة فني مهما كان محسوباً بدقة — تحقق من توقيتها الفعلي بنفسك قبل الدخول، أو انتظر بعد صدورها.")
    else:
        lines = ["⚠️ **Alert: high-impact economic data today**"]
        for e in matches[:3]:
            lines.append(f"- {e.get('Currency')}: {e.get('Name')} ({e.get('Date')})")
        lines.append("This data can cause sharp moves that blow through any technically-sound stop-loss — verify the exact release time yourself before entering, or wait until after it's released.")
    return "\n".join(lines)

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
    photos = sorted(album['photos'], key=lambda x: x[0])[:3]

    try:
        images = []
        for _, file_id in photos:
            file_info = bot.get_file(file_id)
            downloaded = bot.download_file(file_info.file_path)
            images.append(Image.open(BytesIO(downloaded)))

        if len(images) == 1:
            base_prompt = TEXTS[lang]['prompt_single']
        elif len(images) == 2:
            base_prompt = TEXTS[lang]['prompt_multi']
        else:
            base_prompt = TEXTS[lang]['prompt_triple']
        snapshot = fetch_market_snapshot(symbol_caption)
        prompt_text = base_prompt + ("\n\n" + snapshot if snapshot else "")

        if len(images) == 1:
            parts = [prompt_text, images[0]]
        elif len(images) == 2:
            parts = [prompt_text, "Chart 1 - Lower Timeframe (Entry):", images[0], "Chart 2 - Higher Timeframe (Trend):", images[1]]
        else:
            parts = [prompt_text,
                     "Chart 1 - Lower Timeframe (Entry, e.g. 15m):", images[0],
                     "Chart 2 - Mid Timeframe (Zones/Context, e.g. 4H):", images[1],
                     "Chart 3 - Daily Timeframe (Dominant Trend Filter):", images[2]]

        analysis_result = generate_chart_analysis(parts)
        safe_send_long_text(chat_id, status_msg_id, analysis_result, target_lang=lang, prefix_note=check_news_risk(symbol_caption, lang), resolved_symbol=_resolve_ticker(symbol_caption))
        if not snapshot:
            bot.send_message(chat_id, TEXTS[lang]['symbol_tip'])

        if not is_sub:
            update_user(chat_id, 'trials', trials + 1)
    except Exception as e:
        logger.error(f"Album processing error: {traceback.format_exc()}")
        safe_send_long_text(chat_id, status_msg_id, f"❌ تعذر استكمال التحليل.\nالسبب: `{e}`", target_lang=lang)
        notify_admin_failure(chat_id, e)

# === الأوامر والمعالجات ===

@bot.message_handler(commands=['start'])
def send_welcome(message):
    get_user(message.chat.id)
    bot.reply_to(message, TEXTS['ar']['lang_selected'], reply_markup=get_main_keyboard('ar'), parse_mode='Markdown')

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

@bot.message_handler(commands=['diag'])
def admin_diag(message):
    """أداة تشخيص فورية لصاحب البوت فقط: تفحص كل مزود ذكاء اصطناعي على حدة
    باختبار حقيقي مصغّر، بدل انتظار فشل تحليل حقيقي لمستخدم لاكتشاف المشكلة
    (تماماً كما حدث مرتين سابقاً مع تعطل Gemini وتوقف نماذج Groq)."""
    if str(message.chat.id) != str(ADMIN_ID):
        return
    status_msg = bot.reply_to(message, "🔍 جاري فحص كل مزود على حدة، قد يستغرق ثوانٍ...")
    test_img = Image.new('RGB', (20, 20), color='white')
    test_prompt = "Reply with only the single word: OK"
    results = []

    text, err = _try_gemini([test_prompt, test_img])
    results.append(f"• Gemini: {'✅ يعمل' if text else '❌ ' + str(err)[:200]}")

    text, err = _try_groq([test_prompt, test_img])
    if not groq_client:
        results.append("• Groq: ⚪ لم يُفعَّل (لا يوجد GROQ_API_KEY)")
    else:
        results.append(f"• Groq: {'✅ يعمل' if text else '❌ ' + str(err)[:200]}")

    text, err = _try_openrouter([test_prompt, test_img])
    if not OPENROUTER_API_KEY:
        results.append("• OpenRouter: ⚪ لم يُفعَّل (لا يوجد OPENROUTER_API_KEY)")
    else:
        results.append(f"• OpenRouter: {'✅ يعمل' if text else '❌ ' + str(err)[:200]}")

    results.append(f"• بيانات Yahoo Finance: {'✅ متاحة' if yf else '❌ مكتبة yfinance غير مثبتة'}")
    results.append(f"• تقويم الأخبار الاقتصادية: {'✅ مُفعَّل' if ECONOMIC_CALENDAR_API_KEY else '⚪ لم يُفعَّل (اختياري)'}")

    bot.edit_message_text(
        chat_id=message.chat.id, message_id=status_msg.message_id,
        text="🩺 **نتيجة فحص المزودين:**\n" + "\n".join(results),
        parse_mode='Markdown'
    )

def notify_admin_failure(user_chat_id, error):
    """يُرسل تنبيهاً فورياً للأدمن عند فشل كل المزودين معاً لمستخدم حقيقي،
    بدل انتظار أن يكتشف المستخدم المشكلة ويرسل لك لقطة شاشة يدوياً."""
    if not ADMIN_ID or str(ADMIN_ID) == '0' or str(user_chat_id) == str(ADMIN_ID):
        return
    try:
        bot.send_message(int(ADMIN_ID), f"🚨 فشل تحليل لمستخدم `{user_chat_id}`:\n{str(error)[:500]}\n\nجرّب `/diag` لفحص الحالة.", parse_mode='Markdown')
    except Exception as notify_err:
        logger.error(f"Failed to notify admin: {notify_err}")

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
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang, prefix_note=check_news_risk(message.caption, lang), resolved_symbol=_resolve_ticker(message.caption))
        bot.send_message(message.chat.id, TEXTS[lang]['need_two_hint'])
        if not snapshot:
            bot.send_message(message.chat.id, TEXTS[lang]['symbol_tip'])

        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)
    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        safe_send_long_text(message.chat.id, status_msg.message_id, f"❌ تعذر استكمال التحليل.\nالسبب: `{e}`", target_lang=lang)
        notify_admin_failure(message.chat.id, e)

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
