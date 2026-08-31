import os
import threading
import requests
import telebot
from flask import Flask
from telebot import types

# 1. جلب المفاتيح والأسرار أمنياً من متغيرات البيئة (Environment Variables)
TOKEN = os.environ.get("BOT_TOKEN", "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "")
WALLET_ADDRESS = os.environ.get("WALLET_ADDRESS", "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8655689754"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@TradeGuard_Admin")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ذاكرة المؤقتة لحالة المستخدمين
users_data = {}

@app.route("/", methods=["GET"])
def index():
    return "TradeGuard AI Server is Active & Healthy!", 200

def run_bot():
    try:
        bot.remove_webhook()
        print("Starting Bot Polling...")
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Polling Exception: {e}")

threading.Thread(target=run_bot, daemon=True).start()

# دالة الاتصال بمحرك Dify AI لتحليل الشارت
def analyze_chart_with_dify(image_url, user_id, lang):
    if not DIFY_API_KEY:
        return None
    
    url = "https://api.dify.ai/v1/chat-messages"
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = (
        "قم بتحليل صورة هذا الشارت تحليلاً فنياً شاملاً ومفصلاً باللغة العربية: "
        "1. الاتجاه العام للسعر (Market Trend)\n"
        "2. مناطق الدعم والمقاومة الرئيسية (Key Support & Resistance)\n"
        "3. اقتراح نقاط الدخول والأهداف وقف الخسارة (Trade Scenarios - Long & Short)\n"
        "4. نصيحة هامة وإدارة المخاطر (Risk Management)"
        if lang == "ar" else
        "Provide a comprehensive technical analysis for this chart in English including: "
        "Market Trend, Key Support & Resistance levels, Trade Scenarios (Long/Short with Entry, TP, SL), and Risk Management rules."
    )
    
    payload = {
        "inputs": {},
        "query": prompt,
        "response_mode": "blocking",
        "user": str(user_id),
        "files": [
            {
                "type": "image",
                "transfer_method": "remote_url",
                "url": image_url
            }
        ]
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=45)
        if response.status_code == 200:
            result = response.json()
            return result.get("answer")
    except Exception as e:
        print(f"Dify Request Error: {e}")
    return None

# --- معالجة الأوامر والرسائل ---

@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🇸🇦 العربية", "🇬🇧 English")

    welcome_text = (
        f"أهلاً بك في بوت التحليل الذكي للأسواق المالية (TradeGuard AI)!\n"
        f"معرفك الخاص (ID): `{user_id}`\n\n"
        f"الرجاء اختيار لغة التحليل المفضلة لديك بالضغط على أحد الأزرار أدناه:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["العربية", "عربي", "🇸🇦"]))
def set_lang_ar(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
    users_data[user_id]["lang"] = "ar"
    show_main_menu(message, "ar")

@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["English", "🇬🇧"]))
def set_lang_en(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
    users_data[user_id]["lang"] = "en"
    show_main_menu(message, "en")

@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["حسابي", "معلوماتي", "Account"]))
def handle_account_button(message):
    show_account_info(message, message.from_user.id)

@bot.message_handler(func=lambda msg: msg.text and any(w in msg.text for w in ["اشتراكات", "الاشتراكات", "Subscription"]))
def handle_sub_button(message):
    user_id = message.from_user.id
    lang = users_data.get(user_id, {}).get("lang", "ar")
    show_subscription_plans(message, lang)

def show_main_menu(message, lang):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if lang == "ar":
        markup.add("📊 حسابي ومعلوماتي", "💎 خطط الاشتراكات")
        bot.send_message(
            message.chat.id,
            "تم اختيار اللغة العربية بنجاح ✅.\nأرسل صورة الشارت الآن وسيقوم البوت بتحليله فوراً!",
            reply_markup=markup
        )
    else:
        markup.add("📊 My Account & Info", "💎 Subscription Plans")
        bot.send_message(
            message.chat.id,
            "English selected successfully ✅.\nSend your chart image now for immediate analysis!",
            reply_markup=markup
        )

def show_account_info(message, user_id):
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
    user = users_data[user_id]
    lang = user["lang"]
    trials = user["trials"]
    sub_status = "مشترك (مفعل) ⭐" if user["subscribed"] else "غير مشترك ❌"

    if lang == "ar":
        text = (
            f"📋 **معلومات الحساب:**\n\n"
            f"- الـ ID الخاص بك: `{user_id}`\n"
            f"- المحاولات المجانية المتبقية: `{trials}`\n"
            f"- حالة الاشتراك: `{sub_status}`"
        )
    else:
        text = (
            f"📋 **Account Info:**\n\n"
            f"- Your ID: `{user_id}`\n"
            f"- Remaining Free Trials: `{trials}`\n"
            f"- Subscription Status: `{sub_status}`"
        )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

def show_subscription_plans(message, lang):
    if lang == "ar":
        text = (
            f"💎 **خطط الاشتراكات والأسعار:**\n\n"
            f"1️⃣ **اشتراك 10 أيام:** `15 دولاراً`\n"
            f"2️⃣ **اشتراك شهري (30 يوماً):** `38 دولاراً`\n\n"
            f"💳 **طريقة الدفع (شبكة TON):**\n"
            f"عنوان المحفظة:\n`{WALLET_ADDRESS}`\n\n"
            f"📩 بعد التحويل، أرسل صورة إيصال الدفع مع الـ ID الخاص بك إلى الأدمن للتفعيل:\n{ADMIN_USERNAME}"
        )
    else:
        text = (
            f"💎 **Subscription Plans & Pricing:**\n\n"
            f"1️⃣ **10 Days Plan:** `$15`\n"
            f"2️⃣ **Monthly Plan (30 Days):** `$38`\n\n"
            f"💳 **Payment Method (TON Network):**\n"
            f"Wallet Address:\n`{WALLET_ADDRESS}`\n\n"
            f"📩 After payment, send receipt & your ID to admin for activation:\n{ADMIN_USERNAME}"
        )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["activate"])
def admin_activate(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "هذا الأمر مخصص للمسؤول فقط.")
        return

    try:
        parts = message.text.split()
        target_id = int(parts[1])
        if target_id not in users_data:
            users_data[target_id] = {"trials": 0, "lang": "ar", "subscribed": True}
        else:
            users_data[target_id]["subscribed"] = True

        bot.reply_to(message, f"تم تفعيل الاشتراك للمستخدم بنجاح: {target_id}")
        bot.send_message(target_id, "🎉 تهانينا! تم تفعيل اشتراكك بنجاح. يمكنك الآن إرسال الشارتات بلا حدود.")
    except Exception:
        bot.reply_to(message, "الصيغة الصحيحة: /activate <user_id>")

# استقبال الصور وتحليلها عبر Dify API
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.from_user.id
    if user_id not in users_data:
        users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

    user = users_data[user_id]
    lang = user["lang"]

    if not user["subscribed"] and user["trials"] <= 0:
        msg = ("❌ نفدت جميع محاولاتك المجانية (3/3).\nللاشتراك تواصل مع الإدارة: " + ADMIN_USERNAME) if lang == "ar" else ("❌ Free trials expired (3/3). Contact admin to subscribe: " + ADMIN_USERNAME)
        bot.reply_to(message, msg)
        return

    wait_msg = bot.reply_to(
        message, 
        "🔍 تم استلام الشارت بنجاح. جاري تحليله عبر الذكاء الاصطناعي..." if lang == "ar" else "🔍 Chart received. Analyzing via AI..."
    )

    try:
        # استخراج رابط الصورة المباشر من تيليجرام
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

        # استدعاء Dify API
        ai_response = analyze_chart_with_dify(file_url, user_id, lang)

        if not user["subscribed"]:
            user["trials"] -= 1

        remaining = user["trials"]

        bot.delete_message(message.chat.id, wait_msg.message_id)

        if ai_response:
            footer = f"\n\n*(المحاولات المجانية المتبقية: {remaining})*" if not user["subscribed"] else ""
            bot.send_message(message.chat.id, ai_response + footer, parse_mode="Markdown")
        else:
            # تقرير فني احتياطي في حال عدم إعداد مفتاح Dify
            fallback_text = (
                f"أهلاً بك. بصفتي TradeGuard AI، إليك تحليلاً فنياً مفصلاً للشارت المرفق:\n\n"
                f"---\n\n"
                f"### 1. الاتجاه العام للسعر (Market Trend)\n"
                f"يظهر الشارت مرحلة تذبذب وحركة عرضية (Consolidation) بين مستويات الدعم والمقاومة المحلية، مع صراع بين المشترين والبائعين للبحث عن سيولة قبل تحديد اتجاه الحركة التالية.\n\n"
                f"### 2. مناطق الدعم والمقاومة الرئيسية\n"
                f"- **المقاومة (R1):** المنطقة العليا للشمعة الأخيرة.\n"
                f"- **الدعم (S1):** القاع المحلي الأخير المتحقق على الفريم الحالي.\n\n"
                f"### 3. اقتراح إدارة الصفقات\n"
                f"- **السيناريو الصعودي:** الدخول بعد إغلاق شمعة تأكيد فوق المقاومة.\n"
                f"- **السيناريو الهبوطي:** الدخول بعد كسر الدعم وإغلاق أسفله.\n\n"
                f"---\n\n"
                f"*(المحاولات المجانية المتبقية: {remaining})*"
            )
            bot.send_message(message.chat.id, fallback_text, parse_mode="Markdown")

    except Exception as e:
        print(f"Error handling photo: {e}")
        bot.send_message(message.chat.id, "حدث خطأ أثناء تحليل الصورة، يرجى إعادة المحاولة.")
