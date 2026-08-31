import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# استدعاء المتغيرات البيئية
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY") or os.getenv("GEMINI_API_KEY")
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1")

# تخزين رقم المحادثة لكل مستخدم للحفاظ على السياق
user_conversations = {}

def send_telegram_message(chat_id, text):
    """إرسال نص إلى مستخدم تليجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"خطأ في إرسال الرسالة لتليجرام: {e}")

def send_telegram_action(chat_id, action="typing"):
    """إظهار حالة جاري الكتابة للمستخدم"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    requests.post(url, json={"chat_id": chat_id, "action": action})

def upload_photo_to_dify(file_id, user_id):
    """تحميل الصورة من تليجرام ورفعها إلى Dify"""
    try:
        # 1. جلب مسار الصورة من تليجرام
        res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}").json()
        if not res.get("ok"):
            return None
        
        file_path = res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        
        # 2. تنزيل بيانات الصورة
        img_bytes = requests.get(download_url).content
        
        # 3. رفع الصورة إلى Dify API
        upload_url = f"{DIFY_API_URL}/files/upload"
        headers = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        files = {"file": ("chart.jpg", img_bytes, "image/jpeg")}
        data = {"user": str(user_id)}
        
        up_res = requests.post(upload_url, headers=headers, files=files, data=data, timeout=30).json()
        return up_res.get("id")
    except Exception as e:
        print(f"خطأ في رفع الصورة إلى Dify: {e}")
        return None

def call_dify_api(user_id, prompt, upload_file_id=None):
    """إرسال الطلب إلى Dify واستلام التحليل"""
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    conv_id = user_conversations.get(user_id, "")
    
    files = []
    if upload_file_id:
        files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": upload_file_id
        })

    payload = {
        "inputs": {},
        "query": prompt if prompt else "قم بتحليل هذا الشارت المرفق وتحديد الاتجاه والدعوم والمقاومات وفرص التداول.",
        "response_mode": "blocking",
        "user": str(user_id),
        "conversation_id": conv_id,
        "files": files
    }

    try:
        res = requests.post(f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            data = res.json()
            user_conversations[user_id] = data.get("conversation_id", "")
            return data.get("answer", "لم يتم استلام رد من النموذج.")
        else:
            print(f"Dify Error {res.status_code}: {res.text}")
            return "حدث خطأ أثناء الاتصال بسيرفر الذكاء الاصطناعي."
    except Exception as e:
        print(f"Exception during Dify API call: {e}")
        return "تأخر الرد من السيرفر، يرجى المحاولة مرة أخرى."

@app.route('/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        return "TradeGuard AI Bot is Running Live!", 200

    update = request.get_json(force=True, silent=True)
    if not update or "message" not in update:
        return jsonify({"status": "ignored"}), 200

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    
    text = msg.get("text", "")
    photos = msg.get("photo", None)
    caption = msg.get("caption", "")

    # الرد على أمر /start
    if text == "/start":
        welcome = "أهلاً بك في **TradeGuard AI** 📈\nأنا مساعدك الذكي لتحليل الأسواق المالية والشارتات.\n\nأرسل لي أي استفسار أو صورة للشارت وسأقوم بتحليله فوراً!"
        send_telegram_message(chat_id, welcome)
        return jsonify({"status": "ok"}), 200

    send_telegram_action(chat_id, "typing")

    upload_file_id = None
    if photos:
        # اختيار الصورة بأعلى دقة
        file_id = photos[-1]["file_id"]
        upload_file_id = upload_photo_to_dify(file_id, user_id)
        prompt = caption if caption else "قم بتحليل الشارت المرفق في الصورة."
    else:
        prompt = text

    if not prompt and not upload_file_id:
        return jsonify({"status": "ok"}), 200

    # جلب التحليل من Dify وإرساله للمستخدم
    reply = call_dify_api(user_id, prompt, upload_file_id)
    send_telegram_message(chat_id, reply)

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
