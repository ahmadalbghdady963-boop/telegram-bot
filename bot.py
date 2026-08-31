import os
import requests
import threading
from flask import Flask, request, jsonify

app = Flask(__name__)

# دالة لطباعة السجلات بشكل فوري في Render
def log(msg):
    print(msg, flush=True)

# المتغيرات البيئية
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY") or os.getenv("GEMINI_API_KEY")
DIFY_API_URL = os.getenv("DIFY_API_URL", "https://api.dify.ai/v1").rstrip('/')
FIREBASE_URL = os.getenv("FIREBASE_DB_URL", "").rstrip('/')

user_conversations = {}

def save_to_firebase(path, data):
    if not FIREBASE_URL:
        return
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        requests.patch(url, json=data, timeout=10) # تم زيادة وقت الانتظار قليلاً
    except Exception as e:
        log(f"Firebase Error: {e}")

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        log(f"Telegram response status: {r.status_code}")
    except Exception as e:
        log(f"Telegram Send Error: {e}")

def upload_photo_to_dify(file_id, user_id):
    """رفع صورة الشارت لـ Dify واسترجاع رقم الملف"""
    try:
        log(f"1. Fetching file info from Telegram for file_id: {file_id}")
        res = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}", timeout=15).json()
        if not res.get("ok"):
            log(f"Telegram getFile error: {res}")
            return None, f"⚠️ فشل جلب الصورة من تليجرام: {res.get('description')}"
        
        file_path = res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        log(f"2. Downloading image bytes...")
        img_bytes = requests.get(download_url, timeout=30).content
        
        upload_url = f"{DIFY_API_URL}/files/upload"
        headers = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        files = {"file": ("chart.jpg", img_bytes, "image/jpeg")}
        data = {"user": str(user_id)}
        
        log(f"3. Uploading image to Dify: {upload_url}")
        up_res = requests.post(upload_url, headers=headers, files=files, data=data, timeout=60) # زيادة الوقت للرفع
        log(f"Dify upload response [{up_res.status_code}]: {up_res.text}")
        
        if up_res.status_code in [200, 201]:
            up_json = up_res.json()
            return up_json.get("id"), None
        else:
            return None, f"❌ فشل رفع الصورة إلى Dify [{up_res.status_code}]:\n`{up_res.text}`"
            
    except Exception as e:
        log(f"Upload Photo Exception: {e}")
        return None, f"❌ خطأ أثناء رفع الصورة: {str(e)}"

def call_dify_api(user_id, prompt, upload_file_id=None):
    """إرسال الطلب إلى Dify API"""
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
        "query": prompt if prompt else "قم بتحليل الشارت المرفق وتحديد الاتجاه والدعوم والمقاومات وفرص التداول.",
        "response_mode": "blocking",
        "user": str(user_id),
        "conversation_id": conv_id,
        "files": files
    }

    try:
        log("4. Sending request to Dify chat-messages API...")
        # 💡 الحل الأهم هنا: تم رفع الـ timeout إلى 240 ثانية (4 دقائق) بدلاً من 120
        res = requests.post(f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload, timeout=240)
        log(f"Dify Chat Response [{res.status_code}]: {res.text}")
        
        if res.status_code == 200:
            data = res.json()
            new_conv_id = data.get("conversation_id", "")
            user_conversations[user_id] = new_conv_id
            
            answer = data.get("answer", "لم يتم استلام رد من النموذج.")
            
            save_to_firebase(f"logs/{user_id}", {
                "last_prompt": prompt,
                "last_response": answer,
                "conversation_id": new_conv_id
            })
            
            return answer
        else:
            return f"❌ خطأ من محرك الذكاء الاصطناعي [{res.status_code}]:\n`{res.text}`"
    except requests.exceptions.Timeout:
        return "⚠️ استغرق الذكاء الاصطناعي وقتاً أطول من اللازم في تحليل الشارت (Timeout). يرجى المحاولة بصورة أوضح أو في وقت لاحق."
    except Exception as e:
        log(f"Dify Exception: {e}")
        return f"❌ حدث خطأ عند الاتصال بـ Dify: {str(e)}"

# تم تمرير معلومات المستخدم لهذه الدالة لتخزينها في الخلفية
def process_message_async(chat_id, user_id, text, photos, caption, first_name, username):
    try:
        log(f"Start async processing for user {user_id}")
        
        # حفظ بيانات المستخدم في الخلفية لتجنب بطء الـ Webhook
        save_to_firebase(f"users/{user_id}", {
            "first_name": first_name,
            "username": username,
            "chat_id": chat_id
        })

        upload_file_id = None
        if photos:
            log("Photo detected in message.")
            # إرسال رسالة تطمين للمستخدم
            send_telegram_message(chat_id, "⏳ جاري استلام الشارت وتحليله بالذكاء الاصطناعي، قد يستغرق الأمر بضع دقائق...")
            
            file_id = photos[-1]["file_id"]
            upload_file_id, err_msg = upload_photo_to_dify(file_id, user_id)
            if err_msg:
                log(f"Upload failed: {err_msg}")
                send_telegram_message(chat_id, err_msg)
                return
            prompt = caption if caption else "قم بتحليل الشارت المرفق في الصورة."
        else:
            send_telegram_message(chat_id, "⏳ جاري التفكير...")
            prompt = text

        if not prompt and not upload_file_id:
            return

        reply = call_dify_api(user_id, prompt, upload_file_id)
        send_telegram_message(chat_id, reply)
    except Exception as main_e:
        log(f"Main Async Exception: {main_e}")
        send_telegram_message(chat_id, f"❌ حدث خطأ غير متوقع: {str(main_e)}")

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def webhook(path):
    if request.method == 'GET':
        return "TradeGuard AI is Live!", 200

    update = request.get_json(force=True, silent=True)
    if not update or "message" not in update:
        return jsonify({"status": "ignored"}), 200

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    first_name = msg["from"].get("first_name", "")
    username = msg["from"].get("username", "")

    log(f"Received webhook request from user {user_id}")

    text = msg.get("text", "")
    photos = msg.get("photo", None)
    caption = msg.get("caption", "")

    if text == "/start":
        welcome = "أهلاً بك في **TradeGuard AI** 📈\nأنا مساعدك الذكي لتحليل الأسواق المالية والشارتات.\n\nأرسل لي أي استفسار أو صورة للشارت وسأقوم بتحليله فوراً!"
        send_telegram_message(chat_id, welcome)
        
        # حفظ بيانات المستخدم في الخلفية عند الـ start
        threading.Thread(target=save_to_firebase, args=(f"users/{user_id}", {
            "first_name": first_name,
            "username": username,
            "chat_id": chat_id
        })).start()
        
        return jsonify({"status": "ok"}), 200

    # معالجة الطلب في الخلفية لتسريع الرد على تليغرام
    threading.Thread(target=process_message_async, args=(chat_id, user_id, text, photos, caption, first_name, username)).start()

    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
