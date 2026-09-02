import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import google.generativeai as genai
import PIL.Image
import io
import sqlite3
from datetime import datetime, timedelta

# --- 1. إعداد المتغيرات البيئية والمفاتيح ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "ضع_توكن_التلغرام_هنا")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "ضع_مفتاح_جيميني_هنا")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# استخدام نموذج Gemini الداعم للرؤية (Vision)
model = genai.GenerativeModel('gemini-1.5-pro')

# --- 2. إعداد قاعدة البيانات للمستخدمين ---
def init_db():
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, lang TEXT, trials INTEGER, sub_end_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    c.execute("SELECT lang, trials, sub_end_date FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'lang': row[0], 'trials': row[1], 'sub_end': row[2]}
    else:
        # إنشاء مستخدم جديد بـ 3 محاولات مجانية
        conn = sqlite3.connect('tradeguard.db')
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, lang, trials, sub_end_date) VALUES (?, ?, ?, ?)", 
                  (user_id, 'ar', 3, None))
        conn.commit()
        conn.close()
        return {'lang': 'ar', 'trials': 3, 'sub_end': None}

def update_user(user_id, **kwargs):
    conn = sqlite3.connect('tradeguard.db')
    c = conn.cursor()
    for key, value in kwargs.items():
        if key == 'lang':
            c.execute("UPDATE users SET lang=? WHERE user_id=?", (value, user_id))
        elif key == 'trials':
            c.execute("UPDATE users SET trials=? WHERE user_id=?", (value, user_id))
        elif key == 'sub_end':
            c.execute("UPDATE users SET sub_end_date=? WHERE user_id=?", (value, user_id))
    conn.commit()
    conn.close()

# --- 3. القاموس والنصوص (كما تم الاتفاق عليها) ---
TEXTS = {
    'ar': {
        'welcome': "مرحباً بك في TradeGuard AI 📈\nمستشارك الذكي والاحترافي لتحليل الشارتات المالية.\n\nالرجاء اختيار لغتك / Choose your language:",
        'lang_selected': "تم اختيار اللغة العربية بنجاح ✅\nأرسل أي صورة لشارت مالي للتحليل المؤسسي الآن.",
        'wait': '⏳ جاري القياس الدقيق للمحاور السعرية وتحديد خطة تداول مطابقة للسعر الحالي...',
        'no_trials_msg': '⚠️ **لقد تم إنهاء محاولاتك المجانية.**\n\nللاستمرار، رجاءً شحن حسابك:\n🔹 **20 دولار** (10 أيام)\n🔹 **50 دولار** (شهري)\n\n📥 **عنوان الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 للتفعيل راسل:\n@TradeGuard_Admin',
        'account': '👤 **معلومات حسابك**\n\n🆔 الـ ID الخاص بك: `{user_id}`\n📊 المحاولات المستخدمة: {trials}/3\n💎 حالة الاشتراك: {sub_status}',
        'sub_info': '💎 **باقات الاشتراك**\n\n🔹 **10 أيام:** 20 دولار (USDT)\n🔹 **شهري (30 يوم):** 50 دولار (USDT)\n\n📥 **عنوان الدفع (USDT - TON):**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 للتفعيل راسل:\n@TradeGuard_Admin',
        'active': 'فعال ✅ (ينتهي: {end})',
        'inactive': 'غير فعال ❌',
        'btn_acc': '👤 حسابي',
        'btn_sub': '💎 الاشتراك',
        'activate_success_user': '🎉 **تم تفعيل اشتراكك بنجاح!**\n\nصالح لغاية: `{end_date}`. بالتوفيق! 📈',
        'prompt': """أنت الآن خبير مالي مخضرم ونظام تدقيق رياضي وحاسوب تداول فائق الدقة، تفكيرك يتجاوز العقل البشري ويعتمد حصرياً على الحقائق والوقائع الرياضية المرئية في الصورة المرفقة فقط. يمنع منعاً باتاً إعطاء تحليلات كاذبة، افتراضية، أو تخمين أي أرقام غير موجودة في الشارت.

البروتوكول الإجباري الصارم (نسبة الخطأ المسموح 0%):
1. اقرأ السعر الحالي (Current Price) المكتوب بجوار الخط الأفقي بدقة مطلقة شاملة الفواصل العشرية.
2. نقطة الدخول (Entry Price) يجب أن تكون مطابقة تماماً للسعر الحالي الظاهر في الشارت (تنفيذ فوري Market Execution). لا تقترح نقاط دخول بعيدة إطلاقاً.
3. المستويات (دعم/مقاومة/أهداف/وقف خسارة) يجب أن تستخرج حصراً من النطاق السعري المرئي على المحور الأيمن (Y-axis). لا تخترع أرقاماً غير مرئية في الصورة.
4. اعتمد "التحليل الذهبي" القائم على قراءة الشموع الواضحة والاتجاه الفعلي دون أي استنتاجات خيالية.

أخرج التحليل بهذا التنسيق فقط (بدون أي مقدمات أو إضافات):

1. 📌 بيانات التدقيق السعري (دقة 100%):
- الأصل/الزوج: [استخرج اسم الزوج من الشارت]
- السعر الحالي الفعلي: [السعر الظاهر بدقة]
- النطاق السعري المرئي: من [أقل سعر بالصورة] إلى [أعلى سعر بالصورة]

2. 🚧 المستويات المفتاحية المرئية:
- أقرب مقاومة مرئية: (السعر الدقيق للقمة السابقة المرئية)
- أقرب دعم مرئي: (السعر الدقيق للقاع السابق المرئي)

3. 🎯 التوصية المباشرة (Market Execution):
- القرار: (شراء / بيع من السعر الحالي بناءً على حركة الشموع الأخيرة)
- نقطة الدخول (Entry): (مطابقة للسعر الحالي المذكور في النقطة الأولى)
- وقف الخسارة (SL): (رقم منطقي قريب لحماية رأس المال ويجب أن يكون داخل النطاق المرئي)
- الهدف (TP): (رقم منطقي داخل النطاق المرئي ومبني على الدعم/المقاومة)

4. 💎 3 نقاط ذهبية مقترحة لتحقيق الربح الصحيح:
- [نقطة 1: استراتيجية الدخول الفوري والتعامل مع السعر الحالي]
- [نقطة 2: إدارة المخاطر وتأمين الصفقة (مثل حجز الأرباح أو نقل وقف الخسارة)]
- [نقطة 3: كيفية تعظيم العائد بناءً على معطيات الشارت الحالية]

⚠️ تنبيه حرج للنظام: أي تخمين أو إعطاء مسافة غير منطقية بين الدخول والسعر الحالي سيؤدي إلى تدمير التحليل. التزم بالواقع والأرقام الظاهرة فقط."""
    },
    'en': {
        'welcome': "Welcome to TradeGuard AI 📈\nChoose your language / اختر لغتك:",
        'lang_selected': "English selected successfully ✅\nSend any chart image now.",
        'wait': '⏳ Scanning exact price coordinates and calculating realistic entry...',
        'no_trials_msg': '⚠️ **Trials Expired.**\n\nTop up your account:\n🔹 **$20** (10 Days)\n🔹 **$50** (Monthly)\n\n📥 **USDT - TON Network:**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Send receipt & ID `{user_id}` to:\n@TradeGuard_Admin',
        'account': '👤 **Account Details**\n\n🆔 ID: `{user_id}`\n📊 Trials: {trials}/3\n💎 Subscription: {sub_status}',
        'sub_info': '💎 **Subscriptions**\n\n🔹 **10-Day:** $20 (USDT)\n🔹 **Monthly:** $50 (USDT)\n\n📥 **USDT - TON Network:**\n`UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK`\n\n📞 Contact Admin:\n@TradeGuard_Admin',
        'active': 'Active ✅ (Ends: {end})',
        'inactive': 'Inactive ❌',
        'btn_acc': '👤 Account',
        'btn_sub': '💎 Subscription',
        'activate_success_user': '🎉 **Subscription Activated!**\n\nValid until: `{end_date}`. Enjoy! 📈',
        'prompt': """You are a highly advanced financial expert and a strict mathematical trading computer. Your logic surpasses human emotion and relies exclusively on visible visual facts and mathematical realities in the provided chart. It is strictly forbidden to provide false, hypothetical, or guessed numbers not present on the chart.

Strict Protocol (0% Error Tolerance):
1. Read the Current Price (CP) exactly as shown on the horizontal line, including decimals.
2. The Entry Price MUST perfectly match the Current Price (Market Execution). NEVER suggest distant entry points.
3. Levels (Support/Resistance/TP/SL) must be extracted exclusively from the visible price range on the Y-axis. Do not invent invisible numbers.
4. Apply "Golden Analysis" based on clear candlestick reading and actual trend, without imaginary assumptions.

Output format (No introductions, strict format only):

1. 📌 Price Verification (100% Accuracy):
- Asset: [Pair Name]
- Exact Current Price: [Visible Price]
- Visible Y-Axis Range: [Min] to [Max]

2. 🚧 Key Visual Levels:
- Nearest Resistance: [Exact price of previous visible peak]
- Nearest Support: [Exact price of previous visible trough]

3. 🎯 Immediate Setup (Market Execution):
- Decision: (Buy/Sell based on recent candles)
- Entry Price: (MUST match Current Price exactly)
- Stop Loss (SL): (Logical nearby level to protect capital, within visible range)
- Take Profit (TP): (Logical level within visible range based on S/R)

4. 💎 3 Golden Points for Correct Profit-Making:
- [Point 1: Immediate entry strategy based on current price]
- [Point 2: Risk management and securing the trade (e.g., trailing stop)]
- [Point 3: Maximizing returns based on current chart data]

⚠️ CRITICAL ALERT: Guessing or providing an illogical distance between Entry and Current Price is a system failure. Stick to reality and visible numbers only."""
    }
}

# --- 4. دوال التلغرام (Handlers) ---

# قائمة البداية واختيار اللغة
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    get_user(user_id) # لضمان تسجيل المستخدم
    
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"),
        InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")
    )
    bot.send_message(message.chat.id, TEXTS['ar']['welcome'], reply_markup=markup)

# التعامل مع أزرار اللغة
@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def callback_query(call):
    user_id = call.from_user.id
    selected_lang = call.data.split('_')[1]
    
    update_user(user_id, lang=selected_lang)
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text(chat_id=call.message.chat.id, 
                          message_id=call.message.message_id, 
                          text=TEXTS[selected_lang]['lang_selected'])

# عرض الحساب
@bot.message_handler(commands=['account'])
def account_info(message):
    user_id = message.from_user.id
    user_data = get_user(user_id)
    lang = user_data['lang']
    
    is_active = False
    sub_status_text = TEXTS[lang]['inactive']
    
    if user_data['sub_end']:
        end_date = datetime.strptime(user_data['sub_end'], '%Y-%m-%d')
        if datetime.now() <= end_date:
            is_active = True
            sub_status_text = TEXTS[lang]['active'].format(end=user_data['sub_end'])

    msg = TEXTS[lang]['account'].format(
        user_id=user_id,
        trials=(3 - user_data['trials']) if not is_active else '∞',
        sub_status=sub_status_text
    )
    bot.send_message(message.chat.id, msg, parse_mode='Markdown')

# التعامل مع الصور المرسلة (التحليل)
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    user_data = get_user(user_id)
    lang = user_data['lang']
    
    # التحقق من الاشتراك والمحاولات
    is_active = False
    if user_data['sub_end']:
        end_date = datetime.strptime(user_data['sub_end'], '%Y-%m-%d')
        if datetime.now() <= end_date:
            is_active = True
            
    if not is_active and user_data['trials'] <= 0:
        bot.send_message(message.chat.id, TEXTS[lang]['no_trials_msg'].format(user_id=user_id), parse_mode='Markdown')
        return

    # إرسال رسالة الانتظار
    wait_msg = bot.reply_to(message, TEXTS[lang]['wait'])
    
    try:
        # تحميل الصورة
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        image = PIL.Image.open(io.BytesIO(downloaded_file))
        
        # استدعاء Gemini مع الصورة والـ Prompt الصارم
        system_prompt = TEXTS[lang]['prompt']
        response = model.generate_content([system_prompt, image])
        
        # خصم محاولة إذا لم يكن مشتركاً
        if not is_active:
            update_user(user_id, trials=user_data['trials'] - 1)
            
        # إرسال التحليل
        bot.edit_message_text(chat_id=message.chat.id, message_id=wait_msg.message_id, 
                              text=response.text, parse_mode='Markdown')
                              
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=wait_msg.message_id, 
                              text=f"❌ Error / خطأ: {str(e)}")

# أمر تفعيل الاشتراك (للاستخدام من قبل الإدمن أو يمكن ربطه بـ API الدفع مستقبلاً)
@bot.message_handler(commands=['activate'])
def admin_activate(message):
    # يُفضل إضافة شرط للتحقق من أن المرسل هو الأدمن (عبر التأكد من user_id)
    try:
        args = message.text.split()
        target_user = int(args[1])
        days = int(args[2])
        
        end_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')
        update_user(target_user, sub_end=end_date)
        
        user_lang = get_user(target_user)['lang']
        bot.send_message(target_user, TEXTS[user_lang]['activate_success_user'].format(end_date=end_date), parse_mode='Markdown')
        bot.reply_to(message, f"✅ User {target_user} activated for {days} days.")
    except Exception:
        bot.reply_to(message, "⚠️ Format: /activate <user_id> <days>")

# --- بدء تشغيل البوت ---
if __name__ == "__main__":
    print("TradeGuard AI Bot is Running...")
    bot.infinity_polling()
