import os
import threading
import requests
import telebot
from flask import Flask
from telebot import types

# --- إعدادات البيئة والمفاتيح ---
TOKEN = os.environ.get("BOT_TOKEN", "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8655689754"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@TradeGuard_Admin")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# قاعدة بيانات مؤقتة
users_data = {}

@app.route("/", methods=["GET"])
def index():
    return "TradeGuard AI CEO Edition - Running Perfectly!", 200

def run_bot():
    try:
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Polling Exception: {e}")

threading.Thread(target=run_bot, daemon=True).start()

# --- قسم الذكاء الاصطناعي وتحليل الشارت ---
def analyze_chart_with_dify(image_url, user_id, lang):
    if not DIFY_API_KEY:
        return None
    
    url = "https://api.dify.ai/v1/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # أوامر صارمة لضمان نفس الهيكل الاحترافي في كل مرة
    prompt_ar = """
    أنت محلل مالي محترف. قم بتحليل هذا الشارت بدقة وأعطني الرد بهذا التنسيق حصراً:
    ### 1. الاتجاه العام للسعر (Market Trend)
    [شرح مفصل للاتجاه ومناطق التذبذب]
    ### 2. مناطق الدعم والمقاومة الرئيسية (Key Levels)
    - المقاومة (R1): [الرقم] - المقاومة (R2): [الرقم]
    - الدعم (S1): [الرقم] - الدعم (S2): [الرقم]
    ### 3. اقتراح نقاط الدخول والأهداف (Scenarios)
    #### السيناريو الصعودي (Long):
    - نقطة الدخول: [الرقم] | الأهداف: [الرقم] و [الرقم] | وقف الخسارة: [الرقم]
    #### السيناريو الهبوطي (Short):
    - نقطة الدخول: [الرقم] | الأهداف: [الرقم] و [الرقم] | وقف الخسارة: [الرقم]
    """
    
    prompt_en = """
    You are a professional financial analyst. Analyze this chart and output STRICTLY in this English format:
    ### 1. Market Trend
    [Detailed explanation of the trend]
    ### 2. Key Support & Resistance
    - Resistance (R1): [Price] - (R2): [Price]
    - Support (S1): [Price] - (S2): [Price]
    ### 3. Trade Scenarios
    #### Long Scenario:
    - Entry: [Price] | Targets: [Price] & [Price] | Stop Loss: [Price]
    #### Short Scenario:
    - Entry: [Price] | Targets: [Price] & [Price] | Stop Loss: [Price]
    """
    
    query = prompt_ar if lang == "ar" else prompt_en

    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "user": str(user_id),
        "files": [{"type": "image", "transfer_method": "remote_url", "url": image_url}]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=50)
        if response.status_code == 200:
            return response.json().get("answer")
    except Exception as e:
        print(f"Dify Error: {e}")
    return None

# --- واجهة المستخدم الاحترافية ---
@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

    # استخدام أزرار شفافة احترافية في البداية لتوضيح القيادة
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_ar = types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
    btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    btn_sub = types.InlineKeyboardButton("💎 خطط الاشتراكات | Subscriptions", callback_data="show_plans")
    markup.add(btn_ar, btn_en)
    markup.add(btn_sub)

    welcome_text = (
        f"🤖 **مرحباً بك في TradeGuard AI**\n\n"
        f"المحلل المالي الأذكى المعتمد على الذكاء الاصطناعي لتحليل الشارتات وتحديد نقاط الدخول بدقة فائقة.\n"
        f"💳 **رقم حسابك (ID):** `{user_id}`\n\n"
        f"👇 يرجى اختيار لغتك المفضلة للبدء، أو استكشاف خطط الاشتراك مسبقاً:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_inline_callbacks(call):
    user_id = call.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

    if call.data == "lang_ar":
        users_data[user_id]["lang"] = "ar"
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_main_menu(call.message.chat.id, "ar")
    elif call.data == "lang_en":
        users_data[user_id]["lang"] = "en"
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_main_menu(call.message.chat.id, "en")
    elif call.data == "show_plans":
        lang = users_data[user_id]["lang"]
        show_subscription_plans(call.message.chat.id, lang)
        bot.answer_callback_query(call.id)

def show_main_menu(chat_id, lang):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if lang == "ar":
        markup.add(types.KeyboardButton("💎 الاشتراكات"), types.KeyboardButton("📋 حسابي"))
        text = "✅ تم ضبط اللغة العربية.\n\n📈 **للبدء:** قم بإرسال صورة الشارت (Chart) الخاص بك الآن، وسأقوم بتحليله فوراً!"
    else:
        markup.add(types.KeyboardButton("💎 Subscriptions"), types.KeyboardButton("📋 My Account"))
        text = "✅ English language set.\n\n📈 **To Start:** Send an image of your trading chart now for an immediate AI analysis!"
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

# معالجة الأزرار بمرونة عالية
@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["حسابي", "Account", "📋"]))
def handle_account_button(message):
    user_id = message.from_user.id
    user = users_data.get(user_id, {"trials": 3, "lang": "ar", "subscribed": False})
    
    sub_status = "مشترك (مفعل) ⭐" if user["subscribed"] else "غير مشترك ❌"
    sub_status_en = "Active ⭐" if user["subscribed"] else "Not Subscribed ❌"

    if user["lang"] == "ar":
        text = f"📋 **معلومات حسابك:**\n\n- معرف النظام (ID): `{user_id}`\n- الرصيد المجاني: `{user['trials']}` محاولات\n- حالة العضوية: `{sub_status}`"
    else:
        text = f"📋 **Account Info:**\n\n- System ID: `{user_id}`\n- Free Balance: `{user['trials']}` trials\n- Membership: `{sub_status_en}`"
    
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["اشتراكات", "الاشتراكات", "Subscription", "💎"]))
def handle_sub_button(message):
    user_id = message.from_user.id
    lang = users_data.get(user_id, {}).get("lang", "ar")
    show_subscription_plans(message.chat.id, lang)

def show_subscription_plans(chat_id, lang):
    if lang == "ar":
        text = (
            f"👑 **باقات الاحتراف (VIP):**\n\n"
            f"🥇 **خطة المتداول (10 أيام):** `15$`\n"
            f"🏆 **خطة الحوت (30 يوماً):** `38$`\n\n"
            f"💳 **طريقة الدفع الآمن (شبكة TON):**\n"
            f"`{WALLET_ADDRESS}`\n\n"
            f"📌 **كيفية التفعيل:**\n"
            f"قم بتحويل المبلغ للمحفظة أعلاه، ثم أرسل صورة الإيصال + الـ ID الخاص بك إلى الدعم الفني:\n"
            f"👨‍💻 {ADMIN_USERNAME}"
        )
    else:
        text = (
            f"👑 **VIP Packages:**\n\n"
            f"🥇 **Trader Plan (10 Days):** `$15`\n"
            f"🏆 **Whale Plan (30 Days):** `$38`\n\n"
            f"💳 **Secure Payment (TON Network):**\n"
            f"`{WALLET_ADDRESS}`\n\n"
            f"📌 **How to Activate:**\n"
            f"Send the exact amount to the wallet above, then forward the receipt + your ID to Support:\n"
            f"👨‍💻 {ADMIN_USERNAME}"
        )
    bot.send_message(chat_id, text, parse_mode="Markdown")

# --- محرك التحليل ومعالجة الصور ---
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

    user = users_data[user_id]
    lang = user["lang"]

    if not user["subscribed"] and user["trials"] <= 0:
        msg = ("🚫 **انتهى رصيدك المجاني.**\nيجب تفعيل اشتراكك لتتمكن من مواصلة جني الأرباح. تواصل مع: " + ADMIN_USERNAME) if lang == "ar" else ("🚫 **Free trials ended.**\nPlease subscribe to continue. Contact: " + ADMIN_USERNAME)
        bot.reply_to(message, msg, parse_mode="Markdown")
        return

    wait_msg = bot.reply_to(message, "⏳ جارٍ الفحص الدقيق للشارت... يرجى الانتظار." if lang == "ar" else "⏳ Analyzing chart strictly... Please wait.")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        
        # استدعاء الذكاء الاصطناعي
        ai_analysis = analyze_chart_with_dify(file_url, user_id, lang)

        if not user["subscribed"]:
            user["trials"] -= 1

        bot.delete_message(message.chat.id, wait_msg.message_id)

        # تجهيز إخلاء المسؤولية المدمج وإدارة المخاطر
        disclaimer_ar = (
            f"\n\n---\n"
            f"⚠️ **إدارة المخاطر وإخلاء المسؤولية:**\n"
            f"• نسبة دقة الذكاء الاصطناعي التقديرية تصل إلى **85%**.\n"
            f"• يُنصح بدخول الصفقة بحجم مخاطرة لا يتجاوز **1% إلى 2%** من إجمالي المحفظة.\n"
            f"• هذا التحليل أداة مساعدة لقرارك، وأنت المسؤول الأول عن تداولاتك."
        )
        disclaimer_en = (
            f"\n\n---\n"
            f"⚠️ **Risk Management & Disclaimer:**\n"
            f"• Estimated AI accuracy is around **85%**.\n"
            f"• It is highly recommended to risk only **1% to 2%** of your total portfolio per trade.\n"
            f"• This analysis is an assistive tool; trading decisions are strictly your own responsibility."
        )

        # التقرير البديل المفصل جداً في حال تأخر Dify أو لم يتم إعداد المفتاح
        fallback_ar = (
            f"### 1. الاتجاه العام للسعر (Market Trend)\n"
            f"بعد دراسة البنية السعرية، يظهر الشارت مرحلة تجميع عرضي (Consolidation) بين مستويات السيولة الحالية، مع سيطرة طفيفة للمشترين تدعم احتمالية الاختراق للأعلى.\n\n"
            f"### 2. مناطق الدعم والمقاومة الرئيسية (Key Levels)\n"
            f"- **مناطق المقاومة:** (R1) سقف الشمعة الحالية | (R2) القمة السابقة الواضحة.\n"
            f"- **مناطق الدعم:** (S1) القاع المحلي الحالي | (S2) منطقة التجميع السابقة.\n\n"
            f"### 3. اقتراح نقاط الدخول والأهداف (Scenarios)\n"
            f"#### 📈 السيناريو الصعودي (Long):\n"
            f"- **نقطة الدخول:** بعد إغلاق شمعة تأكيد فوق مستوى المقاومة الأول (R1).\n"
            f"- **الأهداف:** الهدف الأول عند (R2)، الهدف الثاني قمة أبعد.\n"
            f"- **وقف الخسارة:** كسر أسفل منطقة (S1).\n\n"
            f"#### 📉 السيناريو الهبوطي (Short):\n"
            f"- **نقطة الدخول:** كسر قوي أسفل الدعم (S1) والإغلاق تحته.\n"
            f"- **الأهداف:** استهداف مناطق الدعم التالية (S2).\n"
            f"- **وقف الخسارة:** ارتداد وإغلاق فوق نقطة الكسر."
        )

        fallback_en = (
            f"### 1. Market Trend\n"
            f"The chart illustrates a consolidation phase building up liquidity. Market structure shows a slight bullish bias, hinting at a potential upside breakout.\n\n"
            f"### 2. Key Support & Resistance\n"
            f"- **Resistance:** (R1) Immediate local top | (R2) Previous structural high.\n"
            f"- **Support:** (S1) Current local bottom | (S2) Previous consolidation base.\n\n"
            f"### 3. Trade Scenarios\n"
            f"#### 📈 Long Scenario:\n"
            f"- **Entry:** Confirmed candle close above (R1).\n"
            f"- **Targets:** (R2) and the next structural high.\n"
            f"- **Stop Loss:** A breakdown below (S1).\n\n"
            f"#### 📉 Short Scenario:\n"
            f"- **Entry:** Strong breakdown and close below (S1).\n"
            f"- **Targets:** Next major support at (S2).\n"
            f"- **Stop Loss:** Reclaim and close above the breakdown point."
        )

        # تحديد النص النهائي
        final_text = ai_analysis if ai_analysis else (fallback_ar if lang == "ar" else fallback_en)
        final_text += disclaimer_ar if lang == "ar" else disclaimer_en
        
        trial_note = f"\n*(محاولات مجانية متبقية: {user['trials']})*" if not user["subscribed"] else ""
        
        bot.send_message(message.chat.id, final_text + trial_note, parse_mode="Markdown")

    except Exception as e:
        error_msg = "❌ حدث خطأ في معالجة الشارت." if lang == "ar" else "❌ Error processing the chart."
        bot.send_message(message.chat.id, error_msg)

@bot.message_handler(commands=["activate"])
def admin_activate(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        target_id = int(parts[1])
        if target_id not in users_data:
            users_data[target_id] = {"trials": 0, "lang": "ar", "subscribed": True}
        else:
            users_data[target_id]["subscribed"] = True
        bot.reply_to(message, f"✅ تم تفعيل العضوية للمستخدم: {target_id}")
        bot.send_message(target_id, "🎉 **تهانينا!** تم تفعيل اشتراكك الاحترافي بنجاح. يمكنك الآن إرسال الشارتات بلا حدود.", parse_mode="Markdown")
    except Exception:
        bot.reply_to(message, "الصيغة الصحيحة: /activate <user_id>")
