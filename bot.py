# ============================================================
# TradeGuard AI — النسخة الكاملة (عربي حصراً، بدون حدود)
# ============================================================
import os
import re
import time
import json
import base64
import sqlite3
import logging
import traceback
import threading
import requests
from io import BytesIO
from datetime import datetime, timedelta

import pytz
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from flask import Flask, request
from PIL import Image

try:
    import google.generativeai as genai
    from google.generativeai.types import HarmCategory, HarmBlockThreshold
    GEMINI_OK = True
except ImportError:
    GEMINI_OK = False

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import yfinance as yf
except ImportError:
    yf = None

# ============================================================
# ⚙️  الإعدادات
# ============================================================
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('BOT_TOKEN')
GEMINI_API_KEY    = os.environ.get('GEMINI_API_KEY', '')
GROQ_API_KEY      = os.environ.get('GROQ_API_KEY', '')
OPENROUTER_API_KEY= os.environ.get('OPENROUTER_API_KEY', '')
RENDER_URL        = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID          = int(os.environ.get('ADMIN_ID', '0') or 0)

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN مفقود")

if GEMINI_OK and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

groq_client = Groq(api_key=GROQ_API_KEY) if (GROQ_API_KEY and Groq) else None

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:       HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# 🗄️  قاعدة البيانات (إحصاءات فقط — بدون اشتراكات)
# ============================================================
DB_PATH = 'tradeguard.db'

def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)

def init_db():
    conn = get_db(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT, first_name TEXT,
                  join_date TEXT, last_seen TEXT,
                  total_analyses INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analyses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER, symbol TEXT, decision TEXT,
                  entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL,
                  probability INTEGER, created_at TEXT)''')
    conn.commit(); conn.close()

init_db()

def get_user(user_id, username='', first_name=''):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    u = c.fetchone()
    now = datetime.now().isoformat()
    if not u:
        c.execute("INSERT INTO users VALUES (?,?,?,?,?,?)",
                  (user_id, username, first_name, now, now, 0))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        u = c.fetchone()
    else:
        c.execute("UPDATE users SET last_seen=? WHERE user_id=?", (now, user_id))
        conn.commit()
    conn.close()
    return u

def inc_analyses(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE users SET total_analyses = total_analyses + 1 WHERE user_id=?",
              (user_id,))
    conn.commit(); conn.close()

def save_analysis(user_id, symbol, decision, entry, sl, tp1, tp2, tp3, prob):
    conn = get_db(); c = conn.cursor()
    c.execute('''INSERT INTO analyses
                 (user_id, symbol, decision, entry, sl, tp1, tp2, tp3,
                  probability, created_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?)''',
              (user_id, symbol, decision, entry, sl, tp1, tp2, tp3, prob,
               datetime.now().isoformat()))
    conn.commit(); conn.close()

# ============================================================
# 📝  النصوص (عربي حصراً)
# ============================================================
TEXTS = {
    'welcome': (
        "🎯 *أهلاً بك في TradeGuard AI*\n\n"
        "مستشارك الذكي لتحليل الأسواق المالية والفوركس\n"
        "تحليل احترافي مبني على Price Action و Liquidity و Supply & Demand\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📸 *كيف تستخدم البوت؟*\n\n"
        "1️⃣ أرسل صورة الشارت (أو صورتين معاً)\n"
        "2️⃣ أضف اسم الأداة كتعليق: `XAUUSD` أو `EURUSD`\n"
        "3️⃣ انتظر التحليل الكامل ✅\n\n"
        "💎 *للحصول على دقة قصوى:*\n"
        "أرسل صورتين في نفس الرسالة:\n"
        "• الأولى: فريم 15 دقيقة (للدخول)\n"
        "• الثانية: فريم 4 ساعات (للاتجاه)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 *الاستخدام مجاني بلا حدود*\n\n"
        "الأوامر المتاحة:\n"
        "/start — البداية\n"
        "/help — المساعدة\n"
        "/mystats — إحصاءاتك"
    ),
    'wait': "🔍 *جاري فحص بنية السوق...*\n\n⏳ تحليل السيولة والعرض والطلب، لحظات من فضلك",
    'need_photo': "📸 أرسل صورة شارت واضحة (مع اسم الأداة كتعليق لنتيجة أدق)",
    'no_symbol': "⚠️ لم أجد اسم الأداة في التعليق\n\n💡 أعد الإرسال مع كتابة الرمز مثل: `XAUUSD` أو `EURUSD`",
    'rate_limit': "⏱️ الرجاء الانتظار {sec} ثانية قبل الإرسال مجدداً",
    'fetching_price': "🌐 جاري جلب السعر الحقيقي من السوق...",
    'disclaimer': (
        "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *تنبيه مهم*\n"
        "هذا تحليل آلي وليس توصية مالية مضمونة. لا يوجد تحليل بنسبة 100%. "
        "إدارة رأس المال مسؤوليتك الشخصية."
    ),
}

# ============================================================
# 🌐  جلب السعر الحقيقي
# ============================================================
SYMBOL_MAP = {
    "XAUUSD": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "SILVER": "SI=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X", "USDCHF": "CHF=X",
    "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "CAD=X",
    "BTCUSD": "BTC-USD", "BTC": "BTC-USD",
    "ETHUSD": "ETH-USD", "ETH": "ETH-USD",
    "US30": "^DJI", "DOW": "^DJI",
    "NAS100": "^NDX", "NASDAQ": "^NDX",
    "SPX500": "^GSPC", "SP500": "^GSPC",
    "USOIL": "CL=F", "WTI": "CL=F",
}

def get_live_price(symbol: str):
    """جلب السعر الحقيقي الحالي من yfinance."""
    if not symbol or yf is None:
        return None
    key = symbol.upper().replace("/", "").replace(" ", "").strip()
    ticker_sym = SYMBOL_MAP.get(key, key)
    try:
        t = yf.Ticker(ticker_sym)
        hist = t.history(period="2d", interval="15m")
        if hist.empty:
            hist = t.history(period="5d", interval="1h")
        if hist.empty:
            return None
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[0])
        change = ((last - prev) / prev * 100) if prev else 0
        high = float(hist["High"].max())
        low  = float(hist["Low"].min())
        return {
            "symbol": key,
            "ticker": ticker_sym,
            "price": round(last, 5),
            "change_pct": round(change, 2),
            "day_high": round(high, 5),
            "day_low":  round(low, 5),
        }
    except Exception as e:
        logger.warning(f"yfinance failed for {symbol}: {e}")
        return None

# ============================================================
# 🧠  قالب التحليل (عربي)
# ============================================================
SYSTEM_PROMPT = """أنت محلل أسواق مالية وفوركس مخضرم (CMT) بخبرة مؤسسية تتجاوز 20 عاماً في Price Action و Liquidity و Supply & Demand.

🎯 قواعد صارمة:
1. الصور المرفقة قد تكون لقطات شاشة كاملة من منصات تداول حقيقية (MetaTrader، TradingView، وسطاء) وتحتوي عناصر واجهة إضافية — هذا طبيعي. ابحث عن الشموع اليابانية ومحور الأسعار بدقة. ارفض فقط إذا كانت الصورة بلا أي شك لا علاقة لها بأي شارت مالي (مثل صورة شخصية أو ميم).
2. اعتمد فقط على الشموع والأسعار المرئية فعلياً في الصور. لا تخترع أرقاماً.
3. إذا تم تزويدك بسعر حقيقي من السوق، اعتبره المرجع الأول واستخدمه للتحقق.
4. لا تدّعي أبداً نسبة نجاح 100% - هذا غير واقعي.
5. أخرج التحليل بالعربية حصراً، بدون مقدمات، وفق القالب التالي تماماً:

━━━━━━━━━━━━━━━━━━━━━
🎯 التحليل الفني الشامل
━━━━━━━━━━━━━━━━━━━━━

1️⃣ هيكل السوق والاتجاه المسيطر:
• اتجاه فريم 4 ساعات: (صاعد/هابط/عرضي) — السبب البنيوي
• توافق أو تعارض فريم 15 دقيقة: (تحليل دقيق)

2️⃣ مناطق السيولة والعرض والطلب:
• منطقة العرض الرئيسية: (السعر بدقة + السبب الفني)
• منطقة الطلب الرئيسية: (السعر بدقة + السبب الفني)

3️⃣ أقوى المقاومات والدعوم:
• المقاومة المحورية: (السعر بدقة)
• الدعم المحوري: (السعر بدقة)

4️⃣ تقييم احتمالية الصفقة (Confluence Score):
احسب النسبة بدقة. البنود حصرية (لا يُحتسب أي إشارة مرتين):
• نقطة أساس: 50%
• اتجاه الفريمين: +15% إذا توافقا تماماً، أو -20% إذا تعارضا (اختر واحداً فقط)
• +15% إذا كان السعر عند منطقة سيولة/عرض/طلب قوية
• +10% إذا وُجد كسر هيكل واضح (BOS/CHoCH) يؤكد الفريم الأكبر (ولا يُحتسب إن كان معاكساً)
• +10% إذا كانت نسبة العائد للمخاطرة حتى TP1 ≥ 1:1.5
⚠️ النتيجة النهائية لا تتجاوز 95% أبداً.

قبل كتابة النتيجة، اذكر:
🔻 أضعف نقطة في هذا التحليل: (أقوى سبب فني قد يجعل الصفقة تفشل)

اعرض جدولاً مختصراً يوضح البنود المحققة، وتأكد أن المجموع يطابق الحساب فعلياً.

5️⃣ الخطة الاستثمارية (Trade Setup):
• القرار: (شراء / بيع / انتظار)
• منطقة الدخول المثالية (Entry): (سعر دقيق)
• وقف الخسارة (SL): عند أقرب نقطة إبطال فنية حقيقية (Swing أو Order Block) + هامش بسيط. اذكر السعر والمسافة.
• أهداف الربح:
  - TP1: (قريب — نسبة عائد للمخاطرة)
  - TP2: (متوسط)
  - TP3: (بعيد عند أقرب منطقة سيولة كبرى)
• إدارة المخاطر: لا تخاطر بأكثر من 1-2% من رأس المال، ويفضل تصفية جزئية عند TP1.

━━━━━━━━━━━━━━━━━━━━━

تعليمة إلزامية أخيرة:
• إذا كان القرار شراء أو بيع، أنهِ رسالتك بهذا السطر الحرفي بالضبط:
#DATA# DECISION=<BUY أو SELL> ENTRY=<رقم> SL=<رقم> TP1=<رقم> TP2=<رقم> TP3=<رقم>
• إذا كان القرار انتظار، اكتب بدلاً منه:
#DATA# NONE"""

# ============================================================
# 🤖  محركات الذكاء الاصطناعي (3 طبقات)
# ============================================================
def call_gemini(images_b64, prompt_text):
    if not (GEMINI_OK and GEMINI_API_KEY):
        return None, "gemini_unavailable"
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        parts = [prompt_text]
        for img_b64 in images_b64:
            parts.append({"mime_type": "image/jpeg",
                          "data": base64.b64decode(img_b64)})
        resp = model.generate_content(parts, safety_settings=safety_settings)
        return resp.text, None
    except Exception as e:
        logger.warning(f"Gemini failed: {e}")
        return None, str(e)

def call_groq(images_b64, prompt_text):
    if not groq_client:
        return None, "groq_unavailable"
    for model in ['llama-3.2-90b-vision-preview',
                  'llama-3.2-11b-vision-preview']:
        try:
            content = [{"type": "text", "text": prompt_text}]
            for img_b64 in images_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
                })
            resp = groq_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": content}],
                temperature=0.3,
                max_tokens=2500,
            )
            return resp.choices[0].message.content, None
        except Exception as e:
            logger.warning(f"Groq {model} failed: {e}")
            continue
    return None, "all_groq_models_failed"

def call_openrouter(images_b64, prompt_text):
    if not OPENROUTER_API_KEY:
        return None, "openrouter_unavailable"
    try:
        content = [{"type": "text", "text": prompt_text}]
        for img_b64 in images_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": "openrouter/free",
                  "messages": [{"role": "user", "content": content}],
                  "temperature": 0.3, "max_tokens": 2500},
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"], None
    except Exception as e:
        logger.warning(f"OpenRouter failed: {e}")
        return None, str(e)

def call_ai(images_b64, prompt_text):
    """يجرّب Gemini → Groq → OpenRouter بالترتيب."""
    text, err = call_gemini(images_b64, prompt_text)
    if text: return text, "gemini"
    logger.info(f"Gemini failed ({err}), trying Groq...")
    text, err = call_groq(images_b64, prompt_text)
    if text: return text, "groq"
    logger.info(f"Groq failed ({err}), trying OpenRouter...")
    text, err = call_openrouter(images_b64, prompt_text)
    if text: return text, "openrouter"
    return None, None

# ============================================================
# 🧹  تنظيف المخرجات
# ============================================================
def clean_output(text):
    if not text:
        return text
    if "1️⃣ هيكل السوق" in text:
        text = "1️⃣ هيكل السوق" + text.split("1️⃣ هيكل السوق")[-1]
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
        r'\(Note:.*?\)',
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()

# ============================================================
# 📊  ملخص الصفقة الآلي (يُحسب رياضياً)
# ============================================================
def verify_and_append_summary(text):
    if not text:
        return text, None
    m = re.search(r'#DATA#\s*(.*)', text)
    if not m:
        return text, None
    line = m.group(1).strip()
    text = text[:m.start()].rstrip()

    if line.upper().startswith('NONE'):
        return text, None

    nums = {k.upper(): float(v) for k, v in
            re.findall(r'(ENTRY|SL|TP1|TP2|TP3)\s*=\s*([\d.]+)', line,
                       flags=re.IGNORECASE)}
    dm = re.search(r'DECISION\s*=\s*(BUY|SELL)', line, flags=re.IGNORECASE)
    if 'ENTRY' not in nums or 'SL' not in nums:
        return text, None

    entry, sl = nums['ENTRY'], nums['SL']
    risk = abs(entry - sl)
    if risk == 0:
        return text, None

    decision = dm.group(1).upper() if dm else 'WAIT'
    dec_ar = "🟢 شراء" if decision == 'BUY' else "🔴 بيع"

    box = ["━━━━━━━━━━━━━━━━━━━━━",
           "📋 *الملخص التنفيذي (محسوب آلياً)*",
           "━━━━━━━━━━━━━━━━━━━━━",
           f"🎯 القرار: {dec_ar}",
           f"📍 الدخول: `{entry}`",
           f"🛑 وقف الخسارة: `{sl}` (مسافة {risk:.4f})",
           ""]
    for tk in ('TP1', 'TP2', 'TP3'):
        if tk in nums:
            reward = abs(nums[tk] - entry)
            box.append(f"✅ {tk}: `{nums[tk]}` ← 1:{reward/risk:.2f}")
    box.append("━━━━━━━━━━━━━━━━━━━━━")

    data = {
        'decision': decision,
        'entry': entry, 'sl': sl,
        'tp1': nums.get('TP1'), 'tp2': nums.get('TP2'), 'tp3': nums.get('TP3'),
    }
    return "\n".join(box) + "\n\n" + text, data

# ============================================================
# 📤  إرسال الرسائل الطويلة (إصلاح مقطوع)
# ============================================================
def safe_send_long_text(chat_id, status_msg_id, full_text, prefix_note=None):
    full_text = clean_output(full_text)
    summary_box, trade_data = verify_and_append_summary(full_text)
    if prefix_note:
        summary_box = prefix_note + "\n\n" + summary_box
    summary_box = summary_box + TEXTS['disclaimer']

    chunk_size = 3800
    chunks = [summary_box[i:i+chunk_size]
              for i in range(0, len(summary_box), chunk_size)]

    for idx, chunk in enumerate(chunks):
        try:
            if idx == 0:
                bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                                      text=chunk, parse_mode='Markdown')
            else:
                bot.send_message(chat_id=chat_id, text=chunk,
                                 parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Markdown send failed ({e}), plain text fallback")
            try:
                plain = re.sub(r'[*_`]', '', chunk)
                if idx == 0:
                    bot.edit_message_text(chat_id=chat_id,
                                          message_id=status_msg_id, text=plain)
                else:
                    bot.send_message(chat_id=chat_id, text=plain)
            except Exception as e2:
                logger.error(f"Plain send failed too: {e2}")

        time.sleep(0.4)

    return trade_data

# ============================================================
# 🚦  Rate Limiting
# ============================================================
_user_cooldown = {}
COOLDOWN_SEC = 20

def check_rate(user_id):
    now = time.time()
    last = _user_cooldown.get(user_id, 0)
    if now - last < COOLDOWN_SEC:
        return int(COOLDOWN_SEC - (now - last))
    _user_cooldown[user_id] = now
    return 0

# ============================================================
# 🖼️  معالجة الصور (إصلاح)
# ============================================================
def download_photo_as_b64(file_id):
    try:
        file_info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        # ضغط الصورة لتقليل الحجم
        img.thumbnail((1280, 1280))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        logger.error(f"photo download failed: {e}")
        return None

def extract_symbol(caption):
    if not caption:
        return None
    cap = caption.upper()
    for sym in SYMBOL_MAP.keys():
        if sym in cap:
            return sym
    m = re.search(r'\b([A-Z]{3,10})\b', cap)
    return m.group(1) if m else None

def process_analysis(chat_id, status_msg_id, photos_file_ids, caption):
    images_b64 = []
    for fid in photos_file_ids:
        b64 = download_photo_as_b64(fid)
        if b64:
            images_b64.append(b64)

    if not images_b64:
        bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                              text="❌ فشل تحميل الصور، حاول مجدداً")
        return

    symbol = extract_symbol(caption)
    live = get_live_price(symbol) if symbol else None

    prompt = SYSTEM_PROMPT
    context_parts = []
    if len(images_b64) == 1:
        context_parts.append(
            "📌 تم إرسال صورة واحدة فقط. اعتمد عليها حصراً، "
            "وأشر في النهاية أن الدقة أعلى مع فريم 4 ساعات."
        )
    else:
        context_parts.append(
            f"📌 تم إرسال {len(images_b64)} صور. الأولى فريم 15 دقيقة (الدخول)، "
            "الثانية فريم 4 ساعات (الاتجاه العام). حلل التوافق بينهما."
        )

    if symbol:
        context_parts.append(f"📌 الأداة المطلوبة: {symbol}")

    if live:
        context_parts.append(
            f"\n🌐 *بيانات سوق حقيقية (مرجع موثوق — اعتمدها):*\n"
            f"• الأداة: {live['symbol']}\n"
            f"• السعر الحالي: {live['price']}\n"
            f"• التغير: {live['change_pct']}%\n"
            f"• أعلى اليوم: {live['day_high']}\n"
            f"• أدنى اليوم: {live['day_low']}\n"
            f"استخدم هذه الأرقام للتحقق من دقة قراءتك للشارت."
        )

    full_prompt = "\n\n".join(context_parts) + "\n\n" + prompt

    text, engine = call_ai(images_b64, full_prompt)
    if not text:
        bot.edit_message_text(chat_id=chat_id, message_id=status_msg_id,
                              text="❌ فشل التحليل، الرجاء المحاولة لاحقاً")
        return

    prefix = f"✅ التحليل جاهز (المحرك: {engine})"
    if live:
        prefix += f"\n🌐 السعر المرجعي الحقيقي: `{live['price']}`"

    trade_data = safe_send_long_text(chat_id, status_msg_id, text,
                                     prefix_note=prefix)

    if trade_data:
        try:
            prob_match = re.search(r'(\d{1,3})\s*%', text)
            prob = int(prob_match.group(1)) if prob_match else None
            save_analysis(
                user_id=chat_id,
                symbol=symbol or 'UNKNOWN',
                decision=trade_data['decision'],
                entry=trade_data['entry'], sl=trade_data['sl'],
                tp1=trade_data['tp1'], tp2=trade_data['tp2'],
                tp3=trade_data['tp3'], prob=prob,
            )
        except Exception as e:
            logger.warning(f"save_analysis failed: {e}")

# ============================================================
# 📨  Handlers
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(message):
    get_user(message.from_user.id,
             message.from_user.username or '',
             message.from_user.first_name or '')
    bot.send_message(message.chat.id, TEXTS['welcome'], parse_mode='Markdown')

@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, TEXTS['welcome'], parse_mode='Markdown')

@bot.message_handler(commands=['mystats'])
def cmd_stats(message):
    u = get_user(message.from_user.id)
    total = u[5] if u else 0
    bot.send_message(
        message.chat.id,
        f"📊 *إحصاءاتك*\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"📈 عدد التحليلات: *{total}*\n"
        f"🎁 الاستخدام: *مجاني بلا حدود*",
        parse_mode='Markdown'
    )

# أوامر الأدمن
@bot.message_handler(commands=['admin_stats'])
def cmd_admin_stats(message):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM analyses"); an = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE last_seen > ?",
              ((datetime.now() - timedelta(days=1)).isoformat(),))
    active = c.fetchone()[0]
    conn.close()
    bot.send_message(message.chat.id,
        f"📊 *إحصاءات البوت*\n\n"
        f"👥 إجمالي المستخدمين: *{total}*\n"
        f"🟢 نشطون آخر 24 ساعة: *{active}*\n"
        f"📈 إجمالي التحليلات: *{an}*",
        parse_mode='Markdown')

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text.replace('/broadcast', '').strip()
    if not text:
        bot.reply_to(message, "الاستخدام: `/broadcast نص الرسالة`",
                     parse_mode='Markdown')
        return
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    ids = [r[0] for r in c.fetchall()]
    conn.close()
    sent = 0
    for uid in ids:
        try:
            bot.send_message(uid, f"📢 *إعلان*\n\n{text}", parse_mode='Markdown')
            sent += 1
            time.sleep(0.05)
        except Exception:
            pass
    bot.reply_to(message, f"✅ تم الإرسال إلى {sent}/{len(ids)}")

# استقبال الصور
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    get_user(user_id, message.from_user.username or '',
             message.from_user.first_name or '')

    wait = check_rate(user_id)
    if wait > 0:
        bot.reply_to(message, TEXTS['rate_limit'].format(sec=wait))
        return

    file_id = message.photo[-1].file_id
    caption = message.caption or ''

    status = bot.reply_to(message, TEXTS['wait'], parse_mode='Markdown')
    threading.Thread(
        target=process_analysis,
        args=(message.chat.id, status.message_id, [file_id], caption),
        daemon=True,
    ).start()

# استقبال نصوص (توجيه)
@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.text.startswith('/'):
        return
    bot.reply_to(message, TEXTS['need_photo'])

# ============================================================
# 🌐  Flask Webhook
# ============================================================
@app.route('/', methods=['GET'])
def index():
    return "✅ TradeGuard AI يعمل", 200

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            update = telebot.types.Update.de_json(request.get_data().decode('utf-8'))
            bot.process_new_updates([update])
        except Exception as e:
            logger.error(f"webhook error: {e}\n{traceback.format_exc()}")
        return '', 200
    return '', 403

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    if not RENDER_URL:
        return "❌ RENDER_EXTERNAL_URL مفقود", 500
    url = f"{RENDER_URL}/{TELEGRAM_TOKEN}"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=url)
    return f"✅ Webhook set: {url}", 200

# ============================================================
# 🚀  التشغيل
# ============================================================
if __name__ == '__main__':
    if RENDER_URL:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")
            logger.info(f"✅ Webhook registered: {RENDER_URL}")
        except Exception as e:
            logger.error(f"set_webhook failed: {e}")

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
