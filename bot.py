import os
import time
import requests
import telebot
from flask import Flask, request
import google.generativeai as genai
from io import BytesIO
from PIL import Image

# === إعدادات المتغيرات البيئية ===
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'AQ.Ab8RN6KaUs0xXwn13AUPE3F2LS160HOaVTkVLfyIOU-NkbWhJw')
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL') 

# === تهيئة Google Gemini ===
genai.configure(api_key=GEMINI_API_KEY)

# 🏆 التعديل الأخير: استخدام أحدث نموذج متوفر حالياً بناءً على طلب سيرفر جوجل 🏆
model = genai.GenerativeModel('gemini-3.6-flash')

# === تهيئة البوت والسيرفر ===
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "TradeGuard AI is running perfectly with Gemini 3.6 Flash!"

@app.route('/' + TELEGRAM_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        try:
            json_string = request.get_data().decode('utf-8')
            update = telebot.types.Update.de_json(json_string)
            bot.process_new_updates([update])
        except Exception as e:
            print("Webhook Error:", e)
        return "OK", 200
    return "Forbidden", 403

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "أهلاً بك في TradeGuard AI 📈\nأرسل لي أي صورة لشارت وسأقوم بتحليلها فوراً!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status_msg = bot.reply_to(message, '⏳ جاري الفحص والتحليل الفني عبر نموذج Gemini 3.6 Flash...')
    
    try:
        # 1. جلب الصورة من تيليجرام
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
        
        image_response = requests.get(file_url, timeout=15)
        if image_response.status_code != 200:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ: لم أتمكن من تحميل الصورة من تيليجرام.")
            return
            
        # فتح الصورة باستخدام مكتبة PIL
        img = Image.open(BytesIO(image_response.content))

        # 2. إعداد نص الأمر (Prompt)
        prompt = """أنت محلل أسواق مالية صارم TradeGuard AI.
القاعدة الأولى: إذا لم تكن الصورة تحتوي على شموع يابانية وأسعار، توقف فوراً ورد بهذا النص فقط: "(Candlesticks) ⚠️ عذراً، هذه الصورة لا تطابق أي رسم بياني للشمعات اليابانية."
القاعدة الثانية: إذا كانت صورة شارت صحيح، استخرج التوصية بسرعة فائقة في 4 نقاط قصيرة ومباشرة فقط:
- الاتجاه العام: (صاعد/هابط/عرضي)
- أقوى مقاومة: (رقم)
- أقوى دعم: (رقم)
- نصيحة سريعة: (جملة واحدة فقط)
لا تكتب أي مقدمات أو خاتمات."""

        # 3. إرسال الصورة والنص إلى Gemini
        response = model.generate_content([prompt, img])
        
        # 4. إرسال النتيجة للمستخدم
        if response.text:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=response.text)
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text="❌ خطأ: استجابة فارغة من النموذج.")

    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=status_msg.message_id, text=f"❌ حدث خطأ داخلي:\n{str(e)}")

# === تشغيل البوت وربط الويب هوك ===
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    
    if RENDER_URL:
        clean_url = RENDER_URL.rstrip('/')
        bot.set_webhook(url=f"{clean_url}/{TELEGRAM_TOKEN}")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
