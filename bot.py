import os
import sqlite3
import requests
import telebot

# Read environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1")

MAX_FREE_TRIALS = 3

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Initialize SQLite database for storing trial counts
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            trials_used INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user_trials(user_id: int) -> int:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT trials_used FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def increment_user_trials(user_id: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, trials_used) 
        VALUES (?, 1)
        ON CONFLICT(user_id) DO UPDATE SET trials_used = trials_used + 1
    """, (user_id,))
    conn.commit()
    conn.close()

# Upload image to Dify API
def upload_file_to_dify(file_bytes: bytes, filename: str, user_id: str) -> str:
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}"}
    files = {"file": (filename, file_bytes, "image/jpeg")}
    data = {"user": user_id}
    
    response = requests.post(f"{DIFY_BASE_URL}/files/upload", headers=headers, files=files, data=data)
    if response.status_code in [200, 201]:
        return response.json().get("id")
    return None

# Send query or chart to Dify workflow/agent
def query_dify(query_text: str, user_id: str, file_id: str = None) -> str:
    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "inputs": {},
        "query": query_text or "حلل هذا الشارت الفني وحدد اتجاه السعر، مستويات الدعم والمقاومة، ونقاط الدخول/الخروج المقترحة.",
        "response_mode": "blocking",
        "user": user_id,
        "files": []
    }

    if file_id:
        payload["files"].append({
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": file_id
        })

    response = requests.post(f"{DIFY_BASE_URL}/chat-messages", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json().get("answer", "لم يتم إرجاع تحليل من Dify.")
    else:
        return f"حدث خطأ أثناء التواصل مع سيرفر التحليل: {response.status_code}"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    user_id = message.from_user.id
    trials_used = get_user_trials(user_id)
    remaining = MAX_FREE_TRIALS - trials_used

    welcome_text = (
        "🤖 **أهلاً بك في TradeGuard AI**\n\n"
        "مساعدك الذكي لتحليل شارتات التداول وتحديد الفرص بدقة.\n\n"
        f"📊 **التجارب المجانية المتبقية:** {max(0, remaining)} من {MAX_FREE_TRIALS}\n\n"
        "أرسل صورة الشارت أو اكتب سؤالك الفني للبدء مباشرة!"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(content_types=['photo', 'text'])
def handle_analysis_request(message):
    user_id = message.from_user.id
    trials_used = get_user_trials(user_id)

    # Check trial limit
    if trials_used >= MAX_FREE_TRIALS:
        paywall_text = (
            "⚠️ **انتهت التجارب المجانية الثلاث (3/3).**\n\n"
            "للحصول على تحليل غير محدود للشارتات وتوصيات يومية حصريّة، يرجى الاشتراك في الباقة المدفوعة.\n\n"
            "💳 **للتواصل والتفعيل:** راسل الدعم على @TradeGuard_Support"
        )
        bot.reply_to(message, paywall_text, parse_mode="Markdown")
        return

    status_msg = bot.reply_to(message, "⏳ جاري جلب الشارت ومعالجته بواسطة TradeGuard AI...")

    upload_file_id = None
    prompt_text = ""

    # Process image if sent
    if message.content_type == 'photo':
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        upload_file_id = upload_file_to_dify(downloaded_file, "chart.jpg", str(user_id))
        prompt_text = message.caption or "حلل هذا الشارت الفني وحدد النقاط المفتاحية للتداول."
    else:
        prompt_text = message.text

    # Execute Dify Analysis
    analysis_result = query_dify(prompt_text, str(user_id), upload_file_id)
    
    # Increment used trials
    increment_user_trials(user_id)
    new_remaining = MAX_FREE_TRIALS - (trials_used + 1)

    footer = f"\n\n⚙️ *ملاحظة:* المتبقي لديك {max(0, new_remaining)} تجربة مجانية."
    bot.edit_message_text(analysis_result + footer, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")

if __name__ == "__main__":
    init_db()
    print("Bot is running...")
    bot.infinity_polling()
