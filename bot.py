import os
import requests
import base64
import time
import telebot
from telebot.apihelper import ApiTelegramException
from flask import Flask
from threading import Thread

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "TradeGuard AI is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في TradeGuard AI 📈\nأرسل لي أي صورة لشارت وسأقوم بتحليلها فوراً عبر Groq!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status_msg = bot.reply_to(message, '⏳ جاري الفحص والتحليل عبر Groq...')
    
    try:
        if not GROQ_API_KEY:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ: متغير GROQ_API_KEY غير معرف في Render.")
            return

        # 1. جلب الصورة وتحويلها إلى Base64
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        image_response = requests.get(file_url)
        base64_image = base64.b64encode(image_response.content).decode('utf-8')
        data_url = f"data:image/jpeg;base64,{base64_image}"

        # 2. إعداد الطلب لـ Groq
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
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

        # قائمة النماذج المتاحة للرؤية في Groq
        models_to_try = [
            "llama-3.2-90b-vision-preview",
            "llama-3.2-11b-vision-preview"
        ]

        last_error_msg = ""
        success = False

        for model in models_to_try:
            payload = {
                "model": model,
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

            try:
                groq_response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
                if groq_response.status_code == 200:
                    result_text = groq_response.json()['choices'][0]['message']['content']
                    bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=result_text)
                    success = True
                    break
                else:
                    err_json = groq_response.json() if groq_response.headers.get('content-type') == 'application/json' else {}
                    err_detail = err_json.get('error', {}).get('message', groq_response.text)
                    last_error_msg = f"رمز {groq_response.status_code} ({model}): {err_detail}"
            except Exception as req_err:
                last_error_msg = f"فشل الاتصال: {str(req_err)}"

        if not success:
            bot.edit_message_text(
                chat_id=message.chat.id, 
                message_id=status_msg.message_id, 
                text=f"❌ خطأ من Groq:\n{last_error_msg}"
            )

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ حدث خطأ أثناء معالجة الصورة:\n{str(e)}")

if __name__ == "__main__":
    Thread(target=run_flask).start()
    
    # تنظيف الـ Webhook وإسقاط التحديثات المعلقة لتجنب تعارض 409
    try:
        bot.remove_webhook(drop_pending_updates=True)
        time.sleep(2)
    except Exception as e:
        print(f"Webhook cleanup note: {e}")

    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except ApiTelegramException as e:
            if e.error_code == 409:
                print("409 Conflict detected. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)
