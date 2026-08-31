import os
import re
import requests
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

def log(msg):
    print(msg, flush=True)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY") or os.getenv("GEMINI_API_KEY")
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1").rstrip('/')
FIREBASE_URL = os.getenv("FIREBASE_DB_URL", "").rstrip('/')

user_conversations = {}

def clean_text_for_telegram(text):
    """دالة لتنظيف النص من رموز ### و --- التي تشوه محاذاة النص العربي في تليجرام"""
    if not text:
        return ""
    # إزالة رموز العناوين ###
    text = re.sub(r'#{1,6}\s*', '', text)
    # إزالة الخطوط الفاصلة ---
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # تنظيف الأسطر الفارغة المكررة
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def save_to_firebase(path, data):
    if not FIREBASE_URL:
        return
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        requests.patch(url, json=data, timeout=10)
    except Exception as e:
        log(f"Firebase Error: {e}")

def send_telegram_message(chat_id, text):
    """إرسال الرسالة مع التنظيف وإعادة المحاولة التلقائية"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    # تنظيف النص قبل إرساله
    clean_text = clean_text_for_telegram(text)
    
    payload = {
        "chat_id": chat_id,
        "text": clean_text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        log(f"Telegram response status: {r.status_code}")
        
        # إذا فشل التنسيق (400)، نرسل النص كـ Plain Text نقي تماماً
        if r.status_code != 200:
            log(f"Markdown failed ({r.status_code}). Retrying plain text...")
            payload.pop("parse_mode", None)
            r_retry = requests.post(url, json=payload, timeout=10)
            log(f"Retry status code: {r_retry.status_code}")
            
    except Exception as e:
        log(f"Telegram Send Error: {e}")

def send_telegram_action(chat_id, action="typing"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    try:
        requests.post(url, json={"chat_id": chat_id, "action": action}, timeout=5)
    except Exception:
        pass

def upload_photo_to_dify(file_id, user_id):
    try:
        res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}", timeout=15).json()
        if not res.get("ok"):
            return None, "⚠️ فشل جلب الصورة من تليجرام."
        
        file_path = res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        img_bytes = requests.get(download_url, timeout=30).content
        
        upload_url = f"{DIFY_API_URL}/files/upload"
        headers = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        files = {"file": ("chart.jpg", img_bytes, "image/jpeg")}
        data = {"user": str(user_id)}
        
        up_res = requests.post(upload_url, headers=headers, files=files, data=data, timeout=60)
        
        if up_res.status_code in [200, 201]:
            return up_res.json().get("id"), None
        else:
            return None, f"❌ فشل رفع الصورة إلى Dify [{up_res.status_code}]"
            
    except Exception as e:
        return None, f"❌ خطأ أثناء رفع الصورة: {str(e)}"

def call_dify_api(user_id, prompt, upload_file_id=None):
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    files = []
    if upload_file_id:
        files.append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": upload_file_id
        })

    payload = {
        "inputs": {},
        "query": prompt if prompt else "قم بتحليل الشارت المرفق واستخراج الاتجاه والدعوم والمقاومات.",
        "response_mode": "blocking",
        "user": str(user_id),
        "files": files
    }

    try:
        res = requests.post(f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload, timeout=240)
        
        if res.status_code == 200:
            data = res.json()
            answer = data.get("answer", "لم يتم استلام رد من النموذج.")
            return answer
        else:
            return f"❌ خطأ من الذكاء الاصطناعي [{res.status_code}]"
    except Exception as e:
        return f"❌ حدث خطأ عند الاتصال بـ Dify: {str(e)}"

def process_message_async(chat_id, user_id, text, photos, caption, first_name, username):
    try:
        send_telegram_action(chat_id, "typing")
        
        save_to_firebase(f"users/{user_id}", {
            "first_name": first_name,
            "username": username,
            "chat_id": chat_id
        })

        upload_file_id = None
        if photos:
            send_telegram_message(chat_id, "⏳ جاري استلام الشارت وتحليله، قد يستغرق الأمر بضع ثوانٍ...")
            file_id = photos[-1]["file_id"]
            upload_file_id, err_msg = upload_photo_to_dify(file_id, user_id)
            if err_msg:
                send_telegram_message(chat_id, err_msg)
                return
            prompt = caption if caption else "قم بتحليل الشارت المرفق."
        else:
            prompt = text

        if not prompt and not upload_file_id:
            return

        reply = call_dify_api(user_id, prompt, upload_file_id)
        send_telegram_message(chat_id, reply)
    except Exception as main_e:
        send_telegram_message(chat_id, f"❌ حدث خطأ: {str(main_e)}")

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def webhook(path):
    if request.method == 'GET':
        return "TradeGuard AI Service Ready", 200

    update = request.get_json(force=True, silent=True)
    if not update or "message" not in update:
        return jsonify({"status": "ignored"}), 200

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    first_name = msg["from"].get("first_name", "")
    username = msg["from"].get("username", "")

    text = msg.get("text", "")
    photos = msg.get("photo", None)
    caption = msg.get("caption", "")

    if text == "/start":
        welcome = "أهلاً بك في TradeGuard AI 📈\nأنا مساعدك الذكي لتحليل الأسواق المالية.\n\nأرسل لي أي صورة لشارت وسأقوم بتحليلها فوراً!"
        send_telegram_message(chat_id, welcome)
        return jsonify({"status": "ok"}), 200

    threading.Thread(
        target=process_message_async, 
        args=(chat_id, user_id, text, photos, caption, first_name, username)
    ).start()

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
