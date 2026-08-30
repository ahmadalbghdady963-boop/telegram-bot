import os
import requests
import telebot
from flask import Flask, request

# --- الإعدادات الأساسية ---
# جلب توكن تيليجرام من Render
TOKEN = os.getenv("TELEGRAM_TOKEN")
# مفتاح Dify الذي قمت بإنشائه (تم دمجه مباشرة)
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "app-cVpzuk9YXOYx0fdvV5l5xbxD") 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- قاعدة بيانات مبسطة (في الذاكرة) ---
users_db = {}

def get_user(user_id):
    if user_id not in users_db:
        # إعطاء كل مستخدم جديد 5 محاولات مجانية
        users_db[user_id] = {"trials": 5}
    return users_db[user_id]

# --- أوامر البوت ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.chat.id
    user_data = get_user(user_id)
    
    welcome_text = (
        "🤖 مرحباً بك في TradeGuard AI!\n\n"
        "أنا المساعد الذكي الخاص بك لتحليل أسواق التداول وحمايتك من المخاطر.\n"
        "📸 قم بإرسال صورة لأي شارت (مخطط بياني)، وسأقوم بتحليله فوراً.\n\n"
        f"🎁 الرصيد المجاني المتبقي: {user_data['trials']} محاولات."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.chat.id
    user_data = get_user(user_id)
    
    if user_data['trials'] <= 0:
        bot.reply_to(message, "⚠️ لقد استنفدت رصيدك المجاني من التحليلات.")
        return

    wait_msg = bot.reply_to(message, "⏳ جاري قراءة الشارت وتحليله، يرجى الانتظار ثواني...")

    try:
        # 1. الحصول على الصورة من تيليجرام
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

        # 2. إعداد طلب Dify
        dify_url = "https://api.dify.ai/v1/chat-messages"
        headers = {
            "Authorization": f"Bearer {DIFY_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "inputs": {},
            "query": "قم بتحليل هذا الشارت المرفق بناءً على تعليماتك كخبير تداول.",
            "response_mode": "blocking",
            "user": str(user_id),
            "files": [
                {
                    "type": "image",
                    "transfer_method": "remote_url",
                    "url": file_url
                }
            ]
        }

        # 3. إرسال الصورة إلى Dify
        response = requests.post(dify_url, headers=headers, json=payload)
        
        if response.status_code == 200:
            response_data = response.json()
            answer = response_data.get('answer', 'لم يتم العثور على إجابة.')
            
            # خصم محاولة من الرصيد
            user_data['trials'] -= 1
            
            # إرسال التحليل النهائي للمستخدم
            bot.edit_message_text(f"{answer}\n\n📉 المحاولات المتبقية: {user_data['trials']}", 
                                  chat_id=user_id, message_id=wait_msg.message_id)
        else:
            bot.edit_message_text(f"❌ عذراً، فشل الاتصال بالذكاء الاصطناعي (Dify Error: {response.status_code})", 
                                  chat_id=user_id, message_id=wait_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ حدث خطأ غير متوقع: {str(e)}", 
                              chat_id=user_id, message_id=wait_msg.message_id)


# --- إعدادات خادم Flask للعمل مع منصة Render ---
@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    # جلب رابط الاستضافة تلقائياً لربط البوت
    render_url = os.environ.get('RENDER_EXTERNAL_URL')
    if render_url:
        bot.set_webhook(url=f"{render_url}/{TOKEN}")
        return f"Webhook is live on {render_url}", 200
    else:
        return "Server is running, but RENDER_EXTERNAL_URL is not set.", 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
