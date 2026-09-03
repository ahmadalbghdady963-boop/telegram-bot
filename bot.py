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

# === إعدادات النظام والمفاتيح Multi-API Keys ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

# قراءة مفاتيح API المتعددة المفصولة بفاصلة
raw_keys = os.environ.get('GEMINI_API_KEYS') or os.environ.get('GEMINI_API_KEY') or ''
API_KEYS = [k.strip() for k in raw_keys.split(',') if k.strip()]

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات Render.")

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

def update_user(user_id, field, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

# === نصوص وقوالب اللغات والتحليل الفني (مع تحسين البرومبت) ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI 📈\nمستشارك الذكي لتحليل الأسواق المالية والفوركس بأعلى دقة مؤسسية.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي شارت مالي (فوركس، ذهب، مؤشرات، كريبتو) للتحليل الاحترافي الآن.",
        'wait': '⏳ جاري فحص بنية السوق، السيولة، ومستويات العرض والطلب بدقة فائقة... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في استغلال الفرص الاحترافية، يرجى الاشتراك للحصول على وصول غير محدود.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل الفوري:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك الاحترافي فعال الآن ولغاية تاريخ: `{end_date}`.\nيمكنك الآن إرسال أي عدد من الشارتات للتحليل المتقدم. بالتوفيق والربح الوفير! 📈',
        'prompt': """أنت محلل أسواق مالية وفوركس مخضرم وحاصل على شهادة CMT مع خبرة مؤسسية تتجاوز 20 عاماً في قراءة حركة السعر (Price Action)، هياكل السيولة (Liquidity Pools)، ومناطق الطلب والعرض (Supply & Demand).
مهمتك تحليل الشارت المرفق بدقة مطلقة واستخراج حقائق صافية بناءً على الشموع الظاهرة حصراً دون أي افتراضات أو تخيلات وهمية.

قواعد صارمة جداً:
1. إذا لم تكن الصورة لشارت تداول مالي أو شموع يابانية واضحة، اكتب حرفياً وبدون إضافات: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية أو سوق مالي."
2. اعتمد على الأسعار والقمم والقعور المرئية بدقة بالغة من على المحاور الظاهرة بالشارت.
3. تنبيه حاسم لسرقة السيولة (Liquidity Sweep): إذا لاحظت وجود ذيول شموع طويلة جداً (Spikes/Wicks) تم رفضها بقوة من القمم أو القيعان، قم بتقييمها كإشارات صيد سيولة وانعكاس محتمل وليست مجرد استمرار للاتجاه.
4. قدم تحليلاً مؤسسياً احترافياً متكاملأً باللغة العربية حصراً وبدون أي مقدمات أو تكرار أو مسودات تفكير، مستخدماً القالب التالي تماماً:

1. هيكل السوق والاتجاه المسيطر:
- الإطار الزمني المقدر ونوع الاتجاه (صاعد/هابط/عرضي مع ذكر السبب البنيوي للشموع والسيولة).

2. مناطق السيولة ومستويات العرض والطلب:
- مناطق العرض الرئيسية: (الأسعار والأسباب الفنية بدقة)
- مناطق الطلب الرئيسية: (الأسعار والأسباب الفنية بدقة)

3. أقوى المقاومات والدعوم الحقيقية:
- المقاومة المحورية: (السعر بدقة)
- الدعم المحوري: (السعر بدقة)

4. نسبة نجاح واغتنام الفرصة (Probability):
- (% نسبة مئوية دقيقة ومدروسة بناءً على قوة الانعكاس أو استمرار الزخم)

5. الخطة الاستثمارية والتنفيذية (Trade Setup):
- القرار الاستثماري: (شراء Buy / بيع Sell / انتظار ومراقبة Wait)
- منطقة الدخول المثالية (Entry Zone): (السعر المحدد بدقة)
- وقف الخسارة الحصين (Stop Loss - SL): (مستوى السعر لمنع الخسارة)
- أهداف جني الأرباح (Take Profit - TP): (الهدف الأول TP1، الهدف الثاني TP2، الهدف الثالث TP3)
- إدارة المخاطر الصارمة: (توجيه فني قصير وحازم لإدارة رأس المال وتجنب الانزلاق السعري)"""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nYour elite AI institutional advisor for Forex and Financial Markets.\n\nChoose your language / اختر لغتك:",
        'lang_selected': "English language selected successfully ✅\nSend any financial chart image (Forex, Gold, Indices, Crypto) for professional analysis now.",
        'wait': '⏳ Scanning market structure, liquidity pools, and order blocks with high precision... Please wait.',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe for unlimited institutional-grade analysis.',
        'account': '👤 **Your Account Details**\n\n🆔 User ID: `{user_id}`\n📊 Free Trials Used: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Pro Subscription Plans**\n\n🔹 **10-Day Plan:** $20 (USDT)\n🔹 **Monthly Plan (30 Days):** $50 (USDT)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send transfer receipt & User ID (`{user_id}`) to Admin for instant activation:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nActive until: `{end_date}`.\nEnjoy unlimited professional chart analysis! 📈',
        'prompt': """You are an elite veteran Forex and financial markets technical analyst with 20+ years of institutional experience in Price Action, Liquidity Pools, and Supply & Demand zones.
Your mission is to analyze the attached chart with absolute precision, extracting pure factual insights based exclusively on visible candles and price action without hallucinations or fake readings.

Strict Rules:
1. If the image is not a valid candlestick chart or financial graph, reply ONLY: "⚠️ Sorry, this image is not a candlestick chart or financial market graph."
2. Base all price levels, swing highs, and swing lows strictly on the visible axis numbers.
3. Liquidity Sweep Warning: If long wicks or spikes show sharp price rejection, treat them as liquidity sweeps and potential reversals, not trend continuations.
4. Output ONLY in English using this exact template with NO preambles, chain-of-thought, or markdown meta-text:

1. Market Structure & Dominant Trend:
- Estimated timeframe and trend direction (Bullish/Bearish/Consolidation with structural reasoning).

2. Liquidity & Supply/Demand Zones:
- Key Supply Zones: (Exact price levels & technical rationale)
- Key Demand Zones: (Exact price levels & technical rationale)

3. Core Support & Resistance:
- Pivot Resistance: (Exact price)
- Pivot Support: (Exact price)

4. Trade Probability Score:
- (% calculated success probability based on momentum and structural confluence)

5. Execution & Trade Setup:
- Investment Decision: (Buy / Sell / Wait)
- Optimal Entry Zone: (Exact price level)
- Stop Loss (SL): (Protected price level)
- Take Profit Targets (TP): (TP1, TP2, and TP3)
- Risk Management Note: (Brief, strict risk control directive)"""
    }
}

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
        elif "1. الاتجاه العام:" in text:
            text = "1. الاتجاه العام:" + text.split("1. الاتجاه العام:")[-1]
    
    patterns = [
        r'\(Self-Correction.*?\)',
        r'Strict and professional\?.*?\n',
        r'Order followed\?.*?\n',
        r'No fluff\?.*?\n',
        r'Max 350 words\?.*?\n',
        r'Numbers accurate\?.*?\n',
        r'Wait, looking closer.*?\n',
        r'Final Polish.*?\n',
        r'Resulting analysis:?\n',
        r'Professional technical analysis system.*?\n',
        r'Institutional grade analysis.*?\n'
    ]
    cleaned = text
    for p in patterns:
        cleaned = re.sub(p, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    
    return cleaned.strip()

# === معالج إرسال الرسائل الطويلة ===
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

# === توليد التحليل الفني مع المداورة التلقائية للمفاتيح (API Key Rotation) ===
def generate_chart_analysis(prompt, img):
    if not API_KEYS:
        raise Exception("لم يتم إعداد مفاتيح GEMINI_API_KEYS في إعدادات البيئة.")

    last_error = None

    # التكرار على جميع المفاتيح لتجاوز أي مفتاح ينتهي حده
    for idx, key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=key)
            # تم تعديل اسم الموديل لتفادي خطأ 404
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = model.generate_content([prompt, img], safety_settings=safety_settings)
            
            if response and response.text:
                logger.info(f"✅ تم التحليل بنجاح باستخدام المفتاح رقم ({idx + 1})")
                return response.text

        except Exception as e:
            err_msg = str(e).lower()
            # تم تصحيح الخطأ الإملائي هنا: err_msg بدلاً من err_str
            if '429' in err_msg or 'quota' in err_msg or 'resourceexceeded' in err_msg:
                logger.warning(f"⚠️ المفتاح رقم ({idx + 1}) تجاوز الحد المسموح (429). جاري الانتقال للمفتاح التالي...")
                last_error = e
                continue
            else:
                logger.error(f"❌ خطأ في المفتاح رقم ({idx + 1}): {e}")
                last_error = e
                continue

    raise Exception(f"جميع مفاتيح API المتاحة ({len(API_KEYS)}) مشغولة حالياً أو تجاوزت الحد. التفاصيل: {last_error}")

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

@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return 
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "❌ خطأ: استخدم الصيغة الصحيحة تماماً:\n`/activate <USER_ID> <DAYS>`", parse_mode='Markdown')
            return

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
        bot.reply_to(message, f"❌ خطأ في معالجة الأمر: {e}")

# معالج الصور والتحليل الفني
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not API_KEYS:
        bot.reply_to(message, "❌ لم يتم ضبط مفاتيح الذكاء الاصطناعي (GEMINI_API_KEYS) في السيرفر.")
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
        
        analysis_result = generate_chart_analysis(TEXTS[lang]['prompt'], img)
        safe_send_long_text(message.chat.id, status_msg.message_id, analysis_result, target_lang=lang)
        
        if not is_sub:
            update_user(message.chat.id, 'trials', trials + 1)

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        safe_send_long_text(message.chat.id, status_msg.message_id, f"❌ تعذر استكمال التحليل.\nالسبب: `{e}`", target_lang=lang)

# === تشغيل السيرفر والـ Webhook ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI Pro Active & Operational!"

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
