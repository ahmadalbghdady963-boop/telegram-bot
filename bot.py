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

# === إعداد نظام المراقبة وتسجيل الأخطاء ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات البيئة والمفاتيح ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

# قراءة مفاتيح API وتطبيق الفلتر لاستبعاد المفاتيح التالفة
raw_keys = os.environ.get('GEMINI_API_KEYS') or os.environ.get('GEMINI_API_KEY') or ''
API_KEYS = [
    k.strip() for k in raw_keys.split(',') 
    if k.strip() and not k.strip().lower().startswith('aiza_invalid')
]

if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: توكن تليجرام مفقود في إعدادات Render.")

# إعدادات الأمان المطلقة
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

# === القوالب والبرومبت ===
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI Pro 📈\nالمحرك الذكي المتقدم لتحليل الشارتات المالية بدقة مؤسسية فائقة.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي شارت مالي (فوركس، ذهب، مؤشرات، كريبتو) للتحليل المؤسسي الآن.",
        'wait': '⏳ جاري فحص بنية الشارت، تدفق السيولة، والمحاور السعرية بدقة خبير مالية... برجاء الانتظار.',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في استخدام التحليل المؤسسي، يرجى الاشتراك للحصول على وصول غير محدود.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI Pro**\n\n🔹 **اشتراك 10 أيام:** 20 دولار (USDT)\n🔹 **اشتراك شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان محفظة الدفع (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 بعد التحويل، أرسل صورة الإشعار والـ ID الخاص بك (`{user_id}`) للتفعيل الفوري:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nاشتراكك فعال ولغاية: `{end_date}`.\nيمكنك الآن إرسال الشارتات للتحليل المتقدم. بالتوفيق! 📈',
        'prompt': """أنت خبير اقتصادي عالمي ومحلل كمي حاصل على شهادة Master CMT مع خبرة 25 عاماً في إدارة صناديق التحوط والتداول المؤسسي المتقدم (Smart Money Concepts & Price Action).
مهمتك إجراء تحليل فني رياضي وحسابي حقيقي للرسم البياني المرفق دون أي تخمين أو استنتاج وهمي.

التعليمات والقواعد الصارمة للغاية:
1. الفحص الهيكلي الإجباري: قم بمطابقة المحور السعري الرأسي والمحور الزمني الأفقي. إذا لم تكن الصورة عبارة عن رسم بياني مالي واضح يضم شموعاً يابانية ومحور أسعار مرئي، أرجع الرسالة التالية حصراً:
"⚠️ عذراً، هذه الصورة لا تطابق رسم بياني لشموع يابانية أو سوق مالي مرئي المحاور."

2. الدقة الرقمية الصارمة: يمنع منعاً باتاً تخمين أو افتراض أي أسعار. يجب أن تعتمد كافة الأرقام والمستويات (الدعوم، المقاومات، الأهداف، ووقف الخسارة) حصرياً على الأرقام الظاهرة صراحة على المحور السعري للشارت.

3. معايير التحليل المؤسسي (SMC / Price Action):
- تحديد بنية السوق: كسر الهيكل (BOS) أو تغيير الطبيعة (CHOCH).
- صيد السيولة (Liquidity Sweep): تقييم الذرى والتيارات الذيلية (Spikes/Wicks) والرفض السعري.
- كتل الطلبات Order Blocks والفجوات السعرية (FVG): تحديد مناطق العرض والطلب الناتجة عن السيولة الذكية.

4. صيغة التقرير المطلوبة (التزام كامل بالقالب التالي بدون أي مقدمات أو مسودات تفكير):

1. هيكل السوق والاتجاه المسيطر:
- الإطار الزمني المقدر والاتجاه (صاعد/هابط/عرضي) مع التبرير الهيكلي الدقيق المعتمد على حركة الشموع والسيولة.

2. بنية السيولة ومناطق العرض والطلب (Order Blocks & FVG):
- مناطق العرض الرئيسية: (الأسعار الدقيقة الظاهرة على المحور مع السبب)
- مناطق الطلب الرئيسية: (الأسعار الدقيقة الظاهرة على المحور مع السبب)
- نقاط صيد السيولة (Liquidity Sweeps): (إن وجدت، مع تحديد مستواها السعري)

3. المستويات المحورية (Pivot Points):
- المقاومة المحورية الرئيسية: (السعر المباشر من الشارت)
- الدعم المحوري الرئيسي: (السعر المباشر من الشارت)

4. تقييم الاحتمالية والزخم (Probability Score):
- نسبة النجاح المئوية بناءً على توافق الاتجاه، السيولة، ومناطق الرفض.

5. صفقة التداول التنفيذية (Institutional Trade Setup):
- القرار الاستثماري: (شراء Buy / بيع Sell / انتظار ومراقبة Wait)
- نقطة الدخول المثالية (Entry Zone): (السعر المحدد بدقة)
- وقف الخسارة الحصين (Stop Loss - SL): (السعر المحدد لحماية رأس المال)
- أهداف جني الأرباح (Take Profit Targets):
  • الهدف الأول (TP1):
  • الهدف الثاني (TP2):
  • الهدف الثالث (TP3):
- نسبة المخاطرة إلى العائد (Risk-to-Reward Ratio): (مثال 1:2.5)
- توجيه إدارة المخاطر: (إرشادات حازمة لحجم العقود وتجنب الانزلاق السعري)"""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI Pro 📈\nYour elite AI institutional advisor for Forex and Financial Markets.\n\nChoose your language / اختر لغتك:",
        'lang_selected': "English language selected successfully ✅\nSend any financial chart image (Forex, Gold, Indices, Crypto) for professional analysis now.",
        'wait': '⏳ Analyzing chart structure, liquidity pools, and order blocks with institutional precision... Please wait.',
        'no_trials': '⚠️ Free trials ended (3/3). Please subscribe for unlimited institutional-grade analysis.',
        'account': '👤 **Your Account Details**\n\n🆔 User ID: `{user_id}`\n📊 Free Trials Used: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Pro Subscription Plans**\n\n🔹 **10-Day Plan:** $20 (USDT)\n🔹 **Monthly Plan (30 Days):** $50 (USDT)\n\n📥 **Payment Address (USDT - TON Network):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send transfer receipt & User ID (`{user_id}`) to Admin for instant activation:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Expires: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nActive until: `{end_date}`.\nEnjoy unlimited professional chart analysis! 📈',
        'prompt': """You are a world-class financial market economist and Master CMT technical analyst with 25+ years of institutional hedge fund experience in Smart Money Concepts (SMC) & Price Action.
Your objective is to provide a purely factual, mathematical, and non-speculative analysis of the attached financial chart.

Strict Instructions:
1. First Validation: Check vertical price axis & horizontal time axis. If the image is NOT a valid candlestick price chart, reply ONLY:
"⚠️ Sorry, this image is not a valid financial candlestick chart with visible price axes."

2. Absolute Price Accuracy: DO NOT hallucinate or guess price levels. Every single price level (highs, lows, supports, resistances, SL, TPs) MUST be derived directly from the visible numbers on the price scale.

3. Institutional SMC & Price Action Rules:
- Identify BOS (Break of Structure) or CHOCH (Change of Character).
- Spot Liquidity Sweeps (long wicks, spikes, price rejection).
- Locate Order Blocks (Demand/Supply) and Fair Value Gaps (FVG).

4. Required Output Format (Output ONLY this structured report with zero preambles or chain-of-thought):

1. Market Structure & Dominant Trend:
- Estimated Timeframe and Direction (Bullish/Bearish/Ranging) supported by visible price structure.

2. Liquidity & Supply/Demand Zones (Order Blocks & FVG):
- Key Supply Zones: (Exact prices visible on the axis & rationale)
- Key Demand Zones: (Exact prices visible on the axis & rationale)
- Liquidity Sweeps: (If present, specify price level)

3. Core Pivot Levels:
- Pivot Resistance: (Exact price from axis)
- Pivot Support: (Exact price from axis)

4. Trade Probability Score:
- Success Probability (%): Based on confluence of trend, liquidity, and rejection setups.

5. Institutional Trade Setup:
- Action Decision: (Buy / Sell / Wait)
- Optimal Entry Zone: (Exact price)
- Protected Stop Loss (SL): (Exact price)
- Take Profit Targets (TP):
  • Target 1 (TP1):
  • Target 2 (TP2):
  • Target 3 (TP3):
- Risk-to-Reward Ratio (R:R): (e.g., 1:2.5)
- Risk Management Directive: (Strict position sizing & slippage advice)"""
    }
}

def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

def clean_analysis_output(text, target_lang):
    if not text:
        return text
    
    if target_lang == 'ar':
        if "1. هيكل السوق والاتجاه المسيطر:" in text:
            text = "1. هيكل السوق والاتجاه المسيطر:" + text.split("1. هيكل السوق والاتجاه المسيطر:")[-1]
    else:
        if "1. Market Structure & Dominant Trend:" in text:
            text = "1. Market Structure & Dominant Trend:" + text.split("1. Market Structure & Dominant Trend:")[-1]

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

# === تحديث النموذج إلى الإصدار المعين في API الحديثة ===
STABLE_MODELS = ['gemini-3.6-flash']

def generate_chart_analysis(prompt, img):
    if not API_KEYS:
        raise Exception("لم يتم العثور على مفاتيح API صالحة.")

    last_error = None

    # التدوير عبر مفاتيح API
    for key_idx, key in enumerate(API_KEYS):
        try:
            genai.configure(api_key=key)
        except Exception as config_err:
            continue

        for model_name in STABLE_MODELS:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([prompt, img], safety_settings=safety_settings)
                
                if response and response.text:
                    logger.info(f"✅ تم التحليل بنجاح عبر النموذج [{model_name}] بالمفتاح #{key_idx + 1}")
                    return response.text
            except Exception as err:
                err_str = str(err)
                logger.warning(f"فشل النموذج [{model_name}] للمفتاح #{key_idx + 1}: {err_str}")
                last_error = err
                
                # إذا تجاوز الحصة السريعة (429) ننتقل مباشرة للمفتاح التالي
                if "429" in err_str or "quota" in err_str.lower() or "resource_exhausted" in err_str.lower():
                    logger.warning(f"تجاوز الحصة للمفتاح #{key_idx + 1}، الانتقال للمفتاح التالي...")
                    break

    raise Exception(f"تعذر استكمال التحليل عبر كافة المفاتيح. آخر خطأ: {last_error}")

# === المعالجات والأوامر ===
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
        bot.reply_to(message, f"❌ خطأ: {e}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
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
    return "TradeGuard AI Pro Institutional Edition Active!"

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
