import os
import requests
import base64
import telebot
from flask import Flask
from threading import Thread

# جلب المفاتيح من متغيرات البيئة في Render
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# سيرفر وهمي لإبقاء تطبيق Render نشطاً
@app.route('/')
def home():
    return "TradeGuard AI with Groq is running smoothly!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# رسالة الترحيب
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في TradeGuard AI 📈\nأرسل لي أي صورة لشارت وسأقوم بتحليلها فوراً عبر Groq!")

# التعامل مع الصور
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status_msg = bot.reply_to(message, '⏳ جاري الفحص والتحليل، قد يستغرق الأمر بضع ثوانٍ...')
    
    try:
        # 1. جلب الصورة من تليجرام
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        
        image_response = requests.get(file_url)
        base64_image = base64.b64encode(image_response.content).decode('utf-8')
        data_url = f"data:image/jpeg;base64,{base64_image}"

        # 2. إرسال الصورة والتعليمات إلى Groq
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        prompt = """أنت محلل أسواق مالية صارم TradeGuard AI.
القاعدة الأولى: إذا لم تكن الصورة تحتوي على شموع يابانية وأسعار، توقف فوراً ورد بهذا النص فقط: "(Candlesticks) ⚠️ عذراً، هذه الصورة لا تطابق أي رسم بياني للشمعات اليابانية. يرجى إرسال شارت صحيح."
القاعدة الثانية: إذا كانت صورة شارت صحيح، استخرج التوصية بسرعة فائقة في 4 نقاط قصيرة ومباشرة فقط:
- الاتجاه العام: (صاعد/هابط/عرضي)
- أقوى مقاومة: (رقم)
- أقوى دعم: (رقم)
- نصيحة سريعة: (جملة واحدة فقط)
لا تكتب أي مقدمات أو خاتمات."""

        payload = {
            "model": "llama-3.2-11b-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                }
            ],
            "max_tokens": 400
        }

        groq_response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        
        if groq_response.status_code == 200:
            result_text = groq_response.json()['choices'][0]['message']['content']
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=result_text)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ من الخادم، يرجى المحاولة لاحقاً.")

    except Exception as e:
        print("Error:", e)
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ حدث خطأ داخلي أثناء معالجة الصورة.")

# إغلاق Webhook وتفعيل Polling
if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    bot.polling(none_stop=True)
