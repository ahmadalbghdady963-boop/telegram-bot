import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
import requests

# --- 1. خادم وهمي لإبقاء الخدمة مجانية على Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# تشغيل الخادم في الخلفية
threading.Thread(target=run_health_server, daemon=True).start()

# --- 2. إعدادات بوت التليجرام و Dify ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DIFY_API_KEY = os.environ.get("DIFY_API_KEY")
DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "https://api.dify.ai/v1")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك! أرسل لي أي استفسار أو صورة شارت للتحليل.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    try:
        headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "inputs": {},
            "query": message.text,
            "response_mode": "blocking",
            "user": str(message.chat.id)
        }
        res = requests.post(f"{DIFY_BASE_URL}/chat-messages", json=payload, headers=headers)
        if res.status_code == 200:
            data = res.json()
            answer = data.get("answer", "لم أستطع الحصول على إجابة.")
            bot.reply_to(message, answer)
        else:
            bot.reply_to(message, "حدث خطأ أثناء التواصل مع الذكاء الاصطناعي.")
    except Exception as e:
        bot.reply_to(message, f"حدث خطأ: {str(e)}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_path = file_info.file_path
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        
        img_data = requests.get(file_url).content
        
        files = {'file': ('image.jpg', img_data, 'image/jpeg')}
        upload_res = requests.post(
            f"{DIFY_BASE_URL}/files/upload",
            headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
            files=files,
            data={"user": str(message.chat.id)}
        )
        
        if upload_res.status_code in [200, 201]:
            file_id = upload_res.json().get("id")
            
            payload = {
                "inputs": {},
                "query": "قم بتحليل هذه الصورة أو الشارت بالتفصيل.",
                "response_mode": "blocking",
                "user": str(message.chat.id),
                "files": [
                    {
                        "type": "image",
                        "transfer_method": "local_file",
                        "upload_file_id": file_id
                    }
                ]
            }
            chat_res = requests.post(
                f"{DIFY_BASE_URL}/chat-messages",
                json=payload,
                headers={"Authorization": f"Bearer {DIFY_API_KEY}"}
            )
            if chat_res.status_code == 200:
                answer = chat_res.json().get("answer", "تم تحليل الصورة.")
                bot.reply_to(message, answer)
            else:
                bot.reply_to(message, "حدث خطأ أثناء تحليل الصورة.")
        else:
            bot.reply_to(message, "فشل رفع الصورة إلى الذكاء الاصطناعي.")
    except Exception as e:
        bot.reply_to(message, f"حدث خطأ: {str(e)}")

if __name__ == '__main__':
    bot.infinity_polling()
    
