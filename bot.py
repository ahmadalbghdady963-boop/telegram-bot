import os
import threading
from datetime import datetime, timedelta
import requests
from flask import Flask, request, abort
from telebot import TeleBot, types

# === المتغيرات الأساسية ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))

# === إعدادات الإدارة ===
ADMIN_ID = "8655689754"
ADMIN_USERNAME = "@TradeGuard_Admin"
RENDER_APP_URL = "https://telegram-bot-pqy3.onrender.com"
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"

bot = TeleBot(TOKEN, threaded=False)
app = Flask(__name__)
USER_CACHE = {}

# === مسارات الويب هوك ===
@app.route("/")
def home():
    return "Bot is running!"

@app.route("/health")
def health():
    return "OK", 200

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = types.Update.de_json(json_string)
            bot.process_new_updates([update])
        except Exception as e:
            print(f"Webhook Error: {e}")
        return '', 200
    else:
        abort(403)

# === قواعد البيانات بطريقة آمنة لا توقف البوت ===
def get_user_data(user_id):
    if user_id not in USER_CACHE:
        USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}
    
    if FIREBASE_URL:
        try:
            res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=2)
            if res.status_code == 200 and res.json():
                USER_CACHE[user_id].update(res.json())
        except:
            pass # تجاهل أخطاء فايربيس كي لا يتوقف البوت
    return USER_CACHE[user_id]

def update_user_data(user_id, data):
    if user_id not in USER_CACHE:
        USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}
    USER_CACHE[user_id].update(data)
    
    if FIREBASE_URL:
        try:
            requests.patch(f"{FIREBASE_URL}/users/{user_id}.json", json=data, timeout=2)
        except:
            pass

# === أمر التفعيل ===
@bot.message_handler(commands=['activate'])
def activate_user(message):
    if str(message.from_user.id) != ADMIN_ID:
        return 
    try:
        parts = message.text.split()
        target_user_id = parts[1]
        days = int(parts[2])
        new_expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
        update_user_data(target_user_id, {"expiry_date": new_expiry_date, "trials": 0})
        bot.reply_to(message, f"✅ تم تفعيل المشترك `{target_user_id}` لمدة {days} يوم.", parse_mode="Markdown")
        bot.send_message(target_user_id, f"🎉 **تم تفعيل اشتراكك بنجاح لمدة {days} يوم!**", parse_mode="Markdown")
    except:
        bot.reply_to(message, "❌ خطأ. الاستخدام الصحيح: `/activate 123456789 30`", parse_mode="Markdown")

# === أمر البداية (وهنا نمسح الأزرار القديمة بقوة) ===
@bot.message_handler(commands=["start"])
def send_welcome(message):
    try:
        user_id = str(message.from_user.id)
        user_data = get_user_data(user_id)
        trials = user_data.get("trials", 0)
        
        is_subscribed = False
        expiry = user_data.get("expiry_date", "")
        if expiry:
            try:
                if datetime.now() < datetime.fromisoformat(expiry):
                    is_subscribed = True
            except:
                pass

        remaining_ar = "غير محدود ♾️" if is_subscribed else f"{max(0, 3 - trials)} من 3"
        
        # إنشاء الأزرار الشفافة
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_ar = types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
        btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        markup.add(btn_ar, btn_en)

        text = (f"مرحباً بك في TradeGuard AI!\n\n"
                f"📊 المحاولات المتبقية: {remaining_ar}\n\n"
                f"الرجاء اختيار اللغة / Select Language:")
        
        # إرسال الرسالة مع الأزرار الشفافة ومسح الأزرار السفلية في نفس الوقت!
        bot.send_message(message.chat.id, text, reply_markup=markup)
        
        # رسالة وهمية إضافية للتأكد من مسح الأزرار السفلية، ثم حذفها فوراً
        dummy = bot.send_message(message.chat.id, "جاري التحديث...", reply_markup=types.ReplyKeyboardRemove())
        bot.delete_message(message.chat.id, dummy.message_id)

    except Exception as e:
        print(f"Start Error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def set_language(call):
    user_id = str(call.from_user.id)
    lang = call.data.split("_")[1]
    update_user_data(user_id, {"lang": lang})
    
    text = "✅ تم اختيار العربية. أرسل لي الشارت الآن." if lang == "ar" else "✅ English selected. Send a chart."
    bot.answer_callback_query(call.id)
    bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=call.message.message_id)

# === معالجة الصور (مع كشف الأخطاء الحقيقية) ===
@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    threading.Thread(target=process_chart_image, args=(message,)).start()

def process_chart_image(message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    trials = user_data.get("trials", 0)
    lang = user_data.get("lang", "ar")
    is_subscribed = False
    
    expiry = user_data.get("expiry_date", "")
    if expiry:
        try:
            if datetime.now() < datetime.fromisoformat(expiry):
                is_subscribed = True
        except:
            pass

    if not is_subscribed and trials >= 3:
        sub_msg = (
            "⚠️ **انتهت محاولاتك المجانية!**\n\n"
            "للاشتراك:\n"
            "🥉 باقة 10 أيام (15$)\n"
            "🏆 باقة 30 يوم (40$)\n\n"
            "1️⃣ حول المبلغ لمحفظة TON:\n"
            f"`{WALLET_TON}`\n"
            "2️⃣ انسخ الـ ID الخاص بك:\n"
            f"`{user_id}`\n"
            "3️⃣ أرسل الإيصال والـ ID للإدارة:\n"
            f"👉 {ADMIN_USERNAME}"
        )
        bot.reply_to(message, sub_msg, parse_mode="Markdown")
        return

    msg = bot.reply_to(message, "⏳ جاري التحليل...")

    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        upload_url = "https://api.dify.ai/v1/files/upload"
        headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        files_data = {"file": ("chart.jpg", downloaded_file, "image/jpeg")}
        data_upload = {"user": user_id}

        upload_response = requests.post(upload_url, headers=headers_upload, files=files_data, data=data_upload, timeout=30)
        
        if upload_response.status_code not in [200, 201]:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ فشل رفع الصورة لـ Dify:\nCode: {upload_response.status_code}\n{upload_response.text}")
            return

        upload_result = upload_response.json()
        dify_file_id = upload_result.get("id")

        chat_url = "https://api.dify.ai/v1/chat-messages"
        query_text = "قم بتحليل هذا الشارت فنياً، وإذا لم تكن الصورة شارت اكتب فقط NOT_CHART" if lang == "ar" else "Analyze this chart technically. If not a chart, output NOT_CHART."
        
        payload = {
            "inputs": {},
            "query": query_text,
            "response_mode": "blocking",
            "user": user_id,
            "files": [{"type": "image", "transfer_method": "local_file", "upload_file_id": dify_file_id}]
        }
        
        headers_chat = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
        response = requests.post(chat_url, headers=headers_chat, json=payload, timeout=60)

        # === هنا التعديل الأهم لكشف سبب الخطأ ===
        if response.status_code != 200:
            error_details = response.text
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ خطأ من Dify (الكود {response.status_code}):\n`{error_details}`", parse_mode="Markdown")
            return

        result = response.json()
        if "answer" not in result:
             bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ Dify لم يرسل إجابة، أرسل هذا بدلاً من ذلك:\n`{result}`", parse_mode="Markdown")
             return
             
        answer = result["answer"]

        if "NOT_CHART" in answer:
            bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="⚠️ هذه ليست صورة شارت تداول!")
            return

        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=answer)

        if not is_subscribed:
            new_trials = trials + 1
            update_user_data(user_id, {"trials": new_trials})

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ خطأ في النظام:\n`{str(e)}`", parse_mode="Markdown")

# === ماسح الأزرار الشامل (أي رسالة نصية تمسح الأزرار القديمة) ===
@bot.message_handler(func=lambda message: True)
def clean_old_buttons(message):
    bot.send_message(
        message.chat.id, 
        "الرجاء الضغط على /start لتحديث البوت وإظهار القائمة الجديدة.", 
        reply_markup=types.ReplyKeyboardRemove()
    )

# === إعداد الويب هوك ===
def setup_webhook():
    try:
        bot.remove_webhook()
        bot.set_webhook(url=f"{RENDER_APP_URL}/{TOKEN}")
    except:
        pass

setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
