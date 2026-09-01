import os
import time
import requests
import sqlite3
import datetime
import pytz
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask, request
import google.generativeai as genai
from io import BytesIO
from PIL import Image

# === إعدادات النظام (مع دعم جميع الاحتمالات لأسماء المتغيرات في ريندر) ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_TOKEN') or os.environ.get('BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')
ADMIN_ID = os.environ.get('ADMIN_ID', '0')

# التحقق من وجود التوكن لمنع انهيار السيرفر
if not TELEGRAM_TOKEN:
    raise ValueError("❌ خطأ حرج: متغير التوكن غير موجود أو تم تسميته بشكل خاطئ في Environment Variables بـ Render.")

# === تهيئة Gemini ===
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
# استخدام نموذج مستقر ومعتمد
model = genai.GenerativeModel('gemini-1.5-flash')

# === تهيئة البوت والسيرفر ===
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# === قاعدة البيانات المحلية (SQLite) ===
def init_db():
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, 
                  is_sub INTEGER, start_date TEXT, end_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)", (user_id, 'ar', 0, 0, '', ''))
        conn.commit()
        user = (user_id, 'ar', 0, 0, '', '')
    conn.close()
    return user

def update_user(user_id, field, value):
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

# === نصوص اللغات ===
TEXTS = {
    'ar': {
        'wait': '⏳ الرجاء الانتظار، جاري التحليل الفني الدقيق...',
        'no_trials': '⚠️ عذراً، لقد استنفدت محاولاتك المجانية (3/3).\n\nللاستمرار في الاستفادة من تحليلات TradeGuard الدقيقة، يرجى الاشتراك.',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المجانية: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك في TradeGuard AI**\n\n🔹 **اشتراك 10 أيام:** 20 دولار\n🔹 **اشتراك شهري:** 50 دولار\n\n📥 **طريقة الدفع (USDT - TON):**\nعنوان المحفظة:\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 **للتفعيل:** أرسل صورة إشعار التحويل مع الـ ID الخاص بك (`{user_id}`) إلى الإدارة:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي في {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'prompt': """أنت محلل أسواق مالية صارم TradeGuard AI.
إذا لم تكن الصورة لشارت مالي، قل فقط: "⚠️ عذراً، هذه الصورة لا تطابق رسماً بيانياً لشموع يابانية."
إذا كانت صحيحة، أعطني تحليلاً احترافياً مفصلاً جداً بدون أي مقدمات أو خاتمات، بالترتيب التالي:
1. الاتجاه العام: (شرح دقيق لحالة السوق الحالية)
2. أقوى المقاومات: (أرقام دقيقة مع ذكر السبب التقني)
3. أقوى الدعوم: (أرقام دقيقة مع ذكر السبب التقني)
4. نسبة حدوث التوقع: (أعطني نسبة مئوية % لنجاح الحركة المتوقعة بناءً على الشارت)
5. الخلاصة والنصيحة: (قرار استثماري واضح ومباشر)."""
    },
    'en': {
        'wait': '⏳ Please wait, performing accurate technical analysis...',
        'no_trials': '⚠️ Sorry, your free trials have ended (3/3).\n\nTo continue using TradeGuard insights, please subscribe.',
        'account': '👤 **Your Account**\n\n🆔 Your ID: `{user_id}`\n📊 Free Trials: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **TradeGuard AI Subscriptions**\n\n🔹 **10 Days:** $20\n🔹 **1 Month:** $50\n\n📥 **Payment Method (USDT - TON):**\nWallet Address:\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 **To Activate:** Send the payment receipt and your ID (`{user_id}`) to Admin:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Ends: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 My Account',
        'btn_sub': '💎 Subscription',
        'prompt': """You are a strict financial analyst, TradeGuard AI.
If the image is not a financial chart, reply ONLY with: "⚠️ Sorry, this image is not a candlestick chart."
If valid, provide a highly detailed professional analysis with NO intro/outro, in this exact format:
1. Market Trend: (Detailed explanation of current state)
2. Key Resistances: (Precise numbers with technical reasoning)
3. Key Supports: (Precise numbers with technical reasoning)
4. Probability of Success: (Provide a percentage % for the expected move based on the chart)
5. Conclusion & Advice: (Clear, direct investment decision)."""
    }
}

# === لوحات المفاتيح (القوائم) ===
def get_main_keyboard(lang):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton(TEXTS[lang]['btn_acc']), KeyboardButton(TEXTS[lang]['btn_sub']))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"), 
               InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"))
    bot.reply_to(message, "Welcome to TradeGuard AI 📈\nPlease choose your language / الرجاء اختيار لغتك:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_language(call):
    lang = call.data.split('_')[1]
    update_user(call.message.chat.id, 'lang', lang)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    welcome_msg = "أهلاً بك في TradeGuard AI! أرسل أي صورة لشارت للتحليل." if lang == 'ar' else "Welcome to TradeGuard AI! Send any chart image for analysis."
    bot.send_message(call.message.chat.id, welcome_msg, reply_markup=get_main_keyboard(lang))

@bot.message_handler(func=lambda message: message.text in [TEXTS['ar']['btn_acc'], TEXTS['en']['btn_acc'], '/my_account'])
def account_info(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, _, end_date = user[1], user[2], user[3], user[4], user[5]
    
    if is_sub:
        sub_status = TEXTS[lang]['active'].format(end=end_date)
    else:
        sub_status = TEXTS[lang]['inactive']
        
    msg = TEXTS[lang]['account'].format(user_id=message.chat.id, trials=trials, sub_status=sub_status)
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text in [TEXTS['ar']['btn_sub'], TEXTS['en']['btn_sub'], '/subscribe'])
def sub_info(message):
    user = get_user(message.chat.id)
    lang = user[1]
    msg = TEXTS[lang]['sub_info'].format(user_id=message.chat.id)
    bot.reply_to(message, msg, parse_mode='Markdown')

# === لوحة تحكم الإدارة (تفعيل الاشتراكات) ===
@bot.message_handler(commands=['activate'])
def admin_activate(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return 
    
    try:
        parts = message.text.split()
        target_user = int(parts[1])
        days = int(parts[2])
        
        tz = pytz.timezone('Asia/Riyadh')
        start_date = datetime.datetime.now(tz)
        end_date = start_date + datetime.timedelta(days=days)
        
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        update_user(target_user, 'is_sub', 1)
        update_user(target_user, 'start_date', start_str)
        update_user(target_user, 'end_date', end_str)
        
        bot.reply_to(message, f"✅ تم تفعيل الاشتراك للمستخدم {target_user} بنجاح لمدة {days} يوم.")
        
        t_user = get_user(target_user)
        lang = t_user[1]
        if lang == 'ar':
            notif = f"🎉 **مبارك! تم تفعيل اشتراكك بنجاح**\n\n📅 يبدأ من: {start_str}\n⏳ ينتهي في: {end_str}\n\nيمكنك الآن إرسال الشارتات بحرية تامة 🚀"
        else:
            notif = f"🎉 **Subscription Activated!**\n\n📅 Starts: {start_str}\n⏳ Ends: {end_str}\n\nYou can now send charts freely 🚀"
        bot.send_message(target_user, notif, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, "❌ خطأ في الصيغة. استخدم:\n/activate <رقم_المستخدم> <عدد_الأيام>")

# === معالجة الصور والتحليل ===
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user = get_user(message.chat.id)
    lang, trials, is_sub, end_date_str = user[1], user[2], user[3], user[5]
    
    if is_sub:
        tz = pytz.timezone('Asia/Riyadh')
        try:
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').replace(tzinfo=tz)
            if datetime.datetime.now(tz) > end_date:
                update_user(message.chat.id, 'is_sub', 0)
                is_sub = 0
        except:
            pass

    if not is_sub and trials >= 3:
        bot.reply_to(message, TEXTS[lang]['no_trials'] + "\n\n" + TEXTS[lang]['sub_info'].format(user_id=message.chat.id), parse_mode='Markdown')
        return

    status_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        
        image_response = requests.get(file_url, timeout=15)
        if image_response.status_code != 200:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ Error downloading image.")
            return
            
        img = Image.open(BytesIO(image_response.content))
        prompt = TEXTS[lang]['prompt']

        response = model.generate_content([prompt, img])
        
        if response.text:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=response.text, parse_mode='Markdown')
            if not is_sub:
                update_user(message.chat.id, 'trials', trials + 1)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ Error: Empty response.")

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ Error occurred. Please try again.")
        print(f"Internal Error: {e}")

# === مسار الويب هوك الخاص بـ Render ===
@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI V2.0 is live and running!"

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
        except Exception as e:
            print("Webhook Error:", e)
        return "OK", 200
    return "Forbidden", 403

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    
    if RENDER_URL:
        clean_url = RENDER_URL.rstrip('/')
        bot.set_webhook(url=f"{clean_url}/{TELEGRAM_TOKEN}")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, threaded=True)
