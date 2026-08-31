import os
import threading
from datetime import datetime
from flask import Flask, request, abort
import requests
from telebot import TeleBot, types

# جلب المتغيرات الأساسية
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))
RENDER_APP_URL = "https://telegram-bot-pqy3.onrender.com"
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"

bot = TeleBot(TOKEN, threaded=False)
app = Flask(__name__)
USER_CACHE = {}

@app.route("/")
def home():
    return "TradeGuard AI CEO Edition - Active & Stable!"

@app.route("/health")
def health():
    return "OK", 200

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

def get_user_data(user_id):
    if user_id not in USER_CACHE:
        USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}
    if FIREBASE_URL:
        try:
            res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=3)
            if res.status_code == 200 and res.json():
                USER_CACHE[user_id].update(res.json())
        except Exception as e:
            print(f"Firebase fetch error: {e}")
    return USER_CACHE[user_id]

def update_user_data(user_id, data):
    if user_id not in USER_CACHE:
        USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}
    USER_CACHE[user_id].update(data)
    if FIREBASE_URL:
        try:
            requests.patch(f"{FIREBASE_URL}/users/{user_id}.json", json=data, timeout=3)
        except Exception as e:
            print(f"Firebase update error: {e}")

@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    trials = user_data.get("trials", 0)
    expiry_date_str = user_data.get("expiry_date", "")

    is_subscribed = False
    if expiry_date_str:
        try:
            if datetime.now() < datetime.fromisoformat(expiry_date_str):
                is_subscribed = True
        except Exception:
            pass

    # عرض أزرار الاشتراكات واللغة منذ البداية
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_ar = types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
    btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    btn_sub_ar = types.InlineKeyboardButton("💎 خطط الاشتراكات", callback_data="plans_ar")
    btn_sub_en = types.InlineKeyboardButton("💎 Subscriptions", callback_data="plans_en")
    
    markup.add(btn_ar, btn_en)
    markup.add(btn_sub_ar, btn_sub_en)

    welcome_text = (
        f"🤖 **مرحباً بك في TradeGuard AI | Welcome!**\n\n"
        f"اكتشف أقوى أداة ذكاء اصطناعي لتحليل أسواق المال بدقة عالية.\n"
        f"Discover the most powerful AI tool for financial market analysis.\n\n"
        f"يرجى اختيار لغتك للبدء، أو تصفح خطط الاشتراك:\n"
        f"Please select your language to start, or view subscription plans:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_") or call.data.startswith("plans_"))
def handle_callbacks(call):
    user_id = str(call.from_user.id)
    
    if call.data.startswith("lang_"):
        lang = call.data.split("_")[1]
        update_user_data(user_id, {"lang": lang})
        if lang == "ar":
            text = "✅ **تم التفعيل باللغة العربية.**\nأرسل صورة الشارت الآن لبدء التحليل الفني الدقيق."
        else:
            text = "✅ **English Activated.**\nSend a chart image now to start the precise technical analysis."
        bot.answer_callback_query(call.id)
        bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")
        
    elif call.data.startswith("plans_"):
        lang = call.data.split("_")[1]
        if lang == "ar":
            text = (
                "👑 **باقات TradeGuard AI الاحترافية:**\n\n"
                "🥉 **باقة المتداول (10 أيام):** `15$`\n"
                "🏆 **الباقة الشهرية (30 يوماً):** `40$`\n\n"
                f"💳 **الدفع الآمن عبر شبكة TON:**\n`{WALLET_TON}`\n\n"
                "📌 لتحويل حسابك إلى VIP، قم بإرسال المبلغ ثم أرسل إيصال الدفع هنا."
            )
        else:
            text = (
                "👑 **TradeGuard AI Pro Plans:**\n\n"
                "🥉 **Trader Plan (10 Days):** `$15`\n"
                "🏆 **Monthly Plan (30 Days):** `$40`\n\n"
                f"💳 **Secure Payment via TON:**\n`{WALLET_TON}`\n\n"
                "📌 To upgrade to VIP, send the amount and forward the payment receipt here."
            )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    # تشغيل التحليل في مسار منفصل لمنع توقف Webhook
    threading.Thread(target=process_chart_image, args=(message,), daemon=True).start()

def process_chart_image(message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    trials = user_data.get("trials", 0)
    expiry_date_str = user_data.get("expiry_date", "")
    lang = user_data.get("lang", "ar")

    is_subscribed = False
    if expiry_date_str:
        try:
            if datetime.now() < datetime.fromisoformat(expiry_date_str):
                is_subscribed = True
        except Exception:
            pass

    if not is_subscribed and trials >= 3:
        sub_msg = (
            "⚠️ **انتهت محاولاتك المجانية (3/3).**\nاشترك الآن بـ 40$ شهرياً للحصول على تحليلات غير محدودة!\nاضغط /start لعرض طرق الدفع."
            if lang == "ar" else
            "⚠️ **Free trials exhausted (3/3).**\nSubscribe for $40/Month for unlimited access!\nPress /start to view payment methods."
        )
        bot.reply_to(message, sub_msg, parse_mode="Markdown")
        return

    msg = bot.reply_to(message, "⏳ جارٍ مسح الشارت ضوئياً..." if lang == "ar" else "⏳ Scanning chart...")

    try:
        # جلب الصورة
        file_id = message.photo[-1].file_id
        file_info_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        file_res = requests.get(file_info_url, timeout=10).json()
        file_path = file_res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        downloaded_file = requests.get(download_url, timeout=30).content

        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, 
                              text="🧠 الذكاء الاصطناعي يقوم بالتحليل..." if lang == "ar" else "🧠 AI is analyzing...")

        # رفع الصورة لـ Dify
        upload_url = "https://api.dify.ai/v1/files/upload"
        headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        upload_response = requests.post(upload_url, headers=headers_upload, 
                                        files={"file": ("chart.jpg", downloaded_file, "image/jpeg")}, 
                                        data={"user": user_id}, timeout=30)
        dify_file_id = upload_response.json().get("id")

        # هندسة الأوامر (Prompt Engineering) لضمان الشكل المطلوب وإجبار اللغة
        prompt_ar = """
        أنت محلل مالي محترف. قم بتحليل الشارت وأعطني الرد باللغة العربية حصراً بهذا التنسيق الدقيق:
        ### 1. الاتجاه العام للسعر (Market Trend)
        [شرح مفصل هنا]
        ### 2. مناطق الدعم والمقاومة الرئيسية
        - المقاومة الأولى (R1): [رقم] | المقاومة الثانية (R2): [رقم]
        - الدعم الأول (S1): [رقم] | الدعم الثاني (S2): [رقم]
        ### 3. اقتراح نقاط الدخول
        - **شراء (Long):** دخول [رقم] | الأهداف [رقم] | وقف الخسارة [رقم]
        - **بيع (Short):** دخول [رقم] | الأهداف [رقم] | وقف الخسارة [رقم]
        """

        prompt_en = """
        CRITICAL: YOU MUST RESPOND ENTIRELY IN ENGLISH. NO ARABIC.
        You are an expert financial analyst. Output EXACTLY in this format:
        ### 1. Market Trend
        [Detailed explanation]
        ### 2. Key Support & Resistance
        - Resistance (R1): [Price] | (R2): [Price]
        - Support (S1): [Price] | (S2): [Price]
        ### 3. Trade Scenarios
        - **Long:** Entry [Price] | Targets [Price] | SL [Price]
        - **Short:** Entry [Price] | Targets [Price] | SL [Price]
        """

        query_text = prompt_ar if lang == "ar" else prompt_en

        chat_url = "https://api.dify.ai/v1/chat-messages"
        payload = {
            "inputs": {},
            "query": query_text,
            "response_mode": "blocking",
            "user": user_id,
            "files": [{"type": "image", "transfer_method": "local_file", "upload_file_id": dify_file_id}]
        }
        
        headers_chat = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
        response = requests.post(chat_url, headers=headers_chat, json=payload, timeout=90)
        answer = response.json().get("answer", "Error.")

        # إخلاء المسؤولية وإدارة المخاطر
        disclaimer = (
            "\n\n---\n⚠️ **إدارة المخاطر:** دقة التحليل تصل لـ 85%. يُنصح بعدم المخاطرة بأكثر من 1% إلى 2% من رأس مالك في الصفقة الواحدة. التداول مسؤوليتك الشخصية."
            if lang == "ar" else
            "\n\n---\n⚠️ **Risk Management:** Accuracy is ~85%. Do not risk more than 1% to 2% of your capital per trade. Trading is your own responsibility."
        )

        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=answer + disclaimer, parse_mode="Markdown")

        # خصم المحاولة
        if not is_subscribed:
            new_trials = trials + 1
            update_user_data(user_id, {"trials": new_trials})

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ خطأ تقني / Technical Error: {str(e)}")

try:
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_APP_URL}/{TOKEN}")
except Exception as e:
    pass

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
