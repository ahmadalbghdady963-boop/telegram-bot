import os
import telebot
from flask import Flask, request
import google.generativeai as genai

# جلب المتغيرات
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
# منصة Render توفر هذا المتغير التلقائي الذي يحتوي على رابط موقعك
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# إعداد مكتبة جوجل الرسمية للذكاء الاصطناعي
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI Webhook is Running Perfectly!"

# مسار الـ Webhook المخصص لتليجرام
@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK", 200

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

        # 1. تحميل الصورة كبيانات مباشرة باستخدام المكتبة
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        image_part = {
            "mime_type": "image/jpeg",
            "data": downloaded_file
        }

        # 2. إعداد نص التحليل
        prompt = """أنت محلل أسواق مالية صارم TradeGuard AI.
القاعدة الأولى: إذا لم تكن الصورة تحتوي على شموع يابانية وأسعار، توقف فوراً ورد بهذا النص فقط: "(Candlesticks) ⚠️ عذراً، هذه الصورة لا تطابق أي رسم بياني للشمعات اليابانية."
القاعدة الثانية: إذا كانت صورة شارت صحيح، استخرج التوصية بسرعة فائقة في 4 نقاط قصيرة ومباشرة فقط:
- الاتجاه العام: (صاعد/هابط/عرضي)
- أقوى مقاومة: (رقم)
- أقوى دعم: (رقم)
- نصيحة سريعة: (جملة واحدة فقط)
لا تكتب أي مقدمات أو خاتمات."""

        # 3. الطلب المباشر والآمن عبر SDK
        response = model.generate_content([prompt, image_part])
        
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=response.text)

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ حدث خطأ داخلي أثناء المعالجة:\n{str(e)}")

if __name__ == "__main__":
    # تنظيف أي اتصال قديم وربط البوت بنظام Webhook تلقائياً
    bot.remove_webhook()
    if RENDER_URL:
        bot.set_webhook(url=f"{RENDER_URL}/{TELEGRAM_TOKEN}")
    
    # تشغيل السيرفر
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
