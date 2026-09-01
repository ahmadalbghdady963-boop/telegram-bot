import os
import requests
import base64
import telebot
from flask import Flask
from threading import Thread

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "TradeGuard AI is running perfectly!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في TradeGuard AI 📈\nأرسل لي أي صورة لشارت وسأقوم بتحليلها فوراً عبر الذكاء الاصطناعي!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status_msg = bot.reply_to(message, '⏳ جاري الفحص والتحليل بدقة، يرجى الانتظار...')
    
    try:
        if not GEMINI_API_KEY:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ: مفتاح GEMINI_API_KEY غير موجود في إعدادات Render.")
            return

        # 1. جلب الصورة من تليجرام
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        image_response = requests.get(file_url)
        base64_image = base64.b64encode(image_response.content).decode('utf-8')

        # 2. الطلب المباشر من Gemini (تم حل مشكلة 404 بإضافة -latest)
        prompt = """أنت محلل أسواق مالية صارم TradeGuard AI.
القاعدة الأولى: إذا لم تكن الصورة تحتوي على شموع يابانية وأسعار، توقف فوراً ورد بهذا النص فقط: "(Candlesticks) ⚠️ عذراً، هذه الصورة لا تطابق أي رسم بياني للشمعات اليابانية. يرجى إرسال شارت صحيح."
القاعدة الثانية: إذا كانت صورة شارت صحيح، استخرج التوصية بسرعة فائقة في 4 نقاط قصيرة ومباشرة فقط:
- الاتجاه العام: (صاعد/هابط/عرضي)
- أقوى مقاومة: (رقم)
- أقوى دعم: (رقم)
- نصيحة سريعة: (جملة واحدة فقط)
لا تكتب أي مقدمات أو خاتمات."""

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={GEMINI_API_KEY.strip()}"
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
            }]
        }

        headers = {'Content-Type': 'application/json'}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            result_json = response.json()
            try:
                result_text = result_json['candidates'][0]['content']['parts'][0]['text']
                bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=result_text)
            except (KeyError, IndexError):
                bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ: استجابة غير متوقعة من الخادم.")
        else:
            bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=status_msg.message_id, 
                text=f"❌ خطأ من الخادم (رمز {response.status_code}):\n{response.text}"
            )

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ حدث خطأ داخلي:\n{str(e)}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    # الحل الجذري لمشكلة 409 Conflict: حذف التحديثات المعلقة واستخدام infinity_polling
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    bot.infinity_polling(timeout=10, long_polling_timeout=5)
