import os
import sqlite3
import requests
import threading
import time
from flask import Flask, request
import google.generativeai as genai
from PIL import Image
import io

# ==================== 1. التكوين والتهيئات ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ADMIN_ID = os.environ.get("ADMIN_ID")  # معرف الآدمين بالتيليجرام (مثال: 123456789)
SERVER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-bot-pqy3.onrender.com")

# إعداد Gemini
genai.configure(api_key=GEMINI_API_KEY)

app = Flask(__name__)

# ==================== 2. قاعدة البيانات ====================
DB_NAME = "tradeguard.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                language TEXT DEFAULT 'en',
                trials INTEGER DEFAULT 3,
                is_vip INTEGER DEFAULT 0,
                vip_expiry TIMESTAMP
            )
        ''')
        conn.commit()

init_db()

def get_or_create_user(user_id, username):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            conn.execute(
                "INSERT INTO users (user_id, username, trials, language) VALUES (?, ?, 3, 'en')",
                (user_id, username or "User")
            )
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return user

def update_user_trials(user_id, trials):
    with get_db() as conn:
        conn.execute("UPDATE users SET trials = ? WHERE user_id = ?", (trials, user_id))
        conn.commit()

def set_user_language(user_id, lang):
    with get_db() as conn:
        conn.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        conn.commit()

# ==================== 3. ميزة البقاء مستيقظاً (Self-Ping Keep-Alive) ====================
def keep_alive():
    """تمنع استضافة Render المجانية من حالة النوم باستدعاء السيرفر كل 10 دقائق"""
    while True:
        time.sleep(600) # كل 10 دقائق
        try:
            if SERVER_URL:
                requests.get(SERVER_URL, timeout=10)
                print("[Keep-Alive] Pinged server successfully.")
        except Exception as e:
            print(f"[Keep-Alive] Ping failed: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

# ==================== 4. إرسال الرسائل لتيليجرام ====================
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_main_keyboard(lang='en'):
    if lang == 'ar':
        return {
            "keyboard": [
                [{"text": "👤 حسابي"}, {"text": "💎 الاشتراك"}],
                [{"text": "🌐 تغيير اللغة"}]
            ],
            "resize_keyboard": True
        }
    else:
        return {
            "keyboard": [
                [{"text": "👤 My Account"}, {"text": "💎 Subscription"}],
                [{"text": "🌐 Change Language"}]
            ],
            "resize_keyboard": True
        }

def send_subscription_info(chat_id, lang='en'):
    if lang == 'ar':
        msg = (
            "💎 **باقات الاشتراك في TradeGuard AI**\n\n"
            "📌 **الباقات المتاحة:**\n"
            "▫️ **باقة 10 أيام:** 20$ (تحليل غير محدود)\n"
            "▫️ **الباقة الشهرية (30 يوم):** 50$ (تحليل غير محدود)\n\n"
            "💳 **عنوان محفظة الدفع (USDT - TRC20):**\n"
            "`TQxYourTRC20WalletAddressHereID`\n\n"
            "📩 **طريقة التفعيل:**\n"
            "بعد إتمام عملية التحويل، يرجى إرسال لقطة شاشة لإشعار الدفع مع معرف حسابك إلى الإدارة لتفعيل الاشتراك فوراً:\n"
            "👤 **الدعم الفني والاشتراكات:** @Ahmad_Admin"
        )
    else:
        msg = (
            "💎 **TradeGuard AI Subscription Plans**\n\n"
            "📌 **Available Plans:**\n"
            "▫️ **10-Day Pass:** $20 (Unlimited Analyses)\n"
            "▫️ **Monthly Pass (30 Days):** $50 (Unlimited Analyses)\n\n"
            "💳 **USDT (TRC20) Payment Address:**\n"
            "`TQxYourTRC20WalletAddressHereID`\n\n"
            "📩 **How to Activate:**\n"
            "After completing the transfer, please send a screenshot of the transaction receipt along with your User ID to Admin for instant activation:\n"
            "👤 **Support & Subscriptions:** @Ahmad_Admin"
        )
    send_telegram_message(chat_id, msg)

# ==================== 5. تحليل الشارت بواسطة الذكاء الاصطناعي ====================
def analyze_chart_with_gemini(image_bytes, lang='en'):
    prompt_ar = """
    أنت خبير تحليل فني وتداول عملات وأسهم محترف. قم بتحليل صورة الشارت المرفقة بدقة عالية وقدم تقريراً فنياً باللغة العربية بالتنسيق التالي حصراً:

    1. اتجاه السوق (Market Trend): شرح مختصر لاتجاه الحركة الحالية والهيكلية.
    2. المستويات الرئيسية:
       - المقاومات (Key Resistances): حدد النقاط بدقة.
       - الدعوم (Key Supports): حدد النقاط بدقة.
    3. تفاصيل الصفقة المقترحة (Trade Setup):
       - نقطة الدخول للصفقة (Entry Point): حدد السعر أو المنطقة المناسبة للدخول.
       - مكان وقف الخسارة (Stop Loss): حدد مستوى إيقاف الخسارة بدقة لحماية رأس المال.
       - مكان المكسب الأول (Take Profit 1): الهدف الأول لربح الصفقة.
       - مكان المكسب الثاني (Take Profit 2): الهدف الثاني لربح الصفقة.
    4. نسبة نجاح الصفقة (Probability of Success): اذكر النسبة المئوية المتوقعة (مثال 65%).
    5. الخلاصة والنصيحة (Conclusion & Advice): نصيحة صريحة (انتظار / شراء / بيع) مع التوجيه المتزن.
    """

    prompt_en = """
    You are a professional technical analysis trader. Analyze the attached chart image with precision and provide a technical report in English strictly following this structure:

    1. Market Trend: Concise structure and current momentum breakdown.
    2. Key Levels:
       - Key Resistances: Exact levels.
       - Key Supports: Exact levels.
    3. Trade Setup Details:
       - Entry Point: Precise entry price or buy/sell zone.
       - Stop Loss: Precise level to stop losses and manage risk.
       - Take Profit 1 (TP1): First target for taking profits.
       - Take Profit 2 (TP2): Second target for taking profits.
    4. Probability of Success: Estimated percentage (e.g., 65%).
    5. Conclusion & Advice: Direct action recommendation (WAIT / BUY / SELL) with clear context.
    """

    prompt = prompt_ar if lang == 'ar' else prompt_en

    try:
        image = Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        # تجربة نموذج بديل في حال وجود ضغط على النموذج الرئيسي
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content([prompt, image])
            return response.text
        except Exception as e2:
            print(f"Gemini Fallback Error: {e2}")
            return None

def process_photo_async(chat_id, user_id, photo_file_id, lang):
    # إرسال رسالة انتظار للمستخدم
    wait_msg = "⏳ Please wait, performing accurate technical analysis..." if lang != 'ar' else "⏳ جاري تحليل الشارت بدقة، يرجى الانتظار..."
    send_telegram_message(chat_id, wait_msg)

    try:
        # جلب الصورة من سرفرات تيليجرام
        file_info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={photo_file_id}"
        res = requests.get(file_info_url).json()
        file_path = res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        img_data = requests.get(file_url).content

        # التحليل بواسطة الذكاء الاصطناعي
        analysis = analyze_chart_with_gemini(img_data, lang)

        if analysis:
            send_telegram_message(chat_id, analysis, reply_markup=get_main_keyboard(lang))
        else:
            err_msg = "❌ فشل تحليل الصورة، يرجى إعادة المحاولة بنوع صورة أوضح." if lang == 'ar' else "❌ Failed to analyze image. Please try again with a clearer chart."
            send_telegram_message(chat_id, err_msg)
    except Exception as e:
        print(f"Error processing photo: {e}")
        err_msg = "❌ حدث خطأ أثناء المعالجة، يرجى المحاولة لاحقاً." if lang == 'ar' else "❌ Error occurred. Please try again."
        send_telegram_message(chat_id, err_msg)

# ==================== 6. معالجة تحديثات تيليجرام ====================
@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return "TradeGuard AI Bot is Running 24/7!", 200

    update = request.get_json()
    if not update or "message" not in update:
        return "OK", 200

    message = update["message"]
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    username = message["from"].get("username", "")

    user = get_or_create_user(user_id, username)
    lang = user["language"]
    trials = user["trials"]
    is_vip = user["is_vip"]

    # --- معالجة الصور المرسلة ---
    if "photo" in message:
        # التحقق من المحاولات أو اشتراك VIP
        if not is_vip and trials <= 0:
            msg_out = "⚠️ لقد استنفذت جميع المحاولات المجانية.\nيرجى الاشتراك للاستمرار في استخدام البوت." if lang == 'ar' else "⚠️ You have reached the limit of your free trial requests.\nPlease subscribe to continue using the bot."
            send_telegram_message(chat_id, msg_out)
            send_subscription_info(chat_id, lang)
            return "OK", 200

        # خصم محاولة وتحديث قاعدة البيانات فوراً
        if not is_vip:
            new_trials = trials - 1
            update_user_trials(user_id, new_trials)

        photo = message["photo"][-1] # أكبر حجم للصورة
        threading.Thread(target=process_photo_async, args=(chat_id, user_id, photo['file_id'], lang)).start()
        return "OK", 200

    # --- معالجة النصوص والأوامر ---
    if "text" in message:
        text = message["text"].strip()

        if text == "/start":
            welcome_msg = (
                "👋 **أهلاً بك في TradeGuard AI**\nقم بإرسال صورة الشارت للحصول على تحليل فني دقيق وإشارات الدخول والأهداف."
                if lang == 'ar' else
                "👋 **Welcome to TradeGuard AI**\nSend any chart image to get instant technical analysis, entry points, and targets."
            )
            send_telegram_message(chat_id, welcome_msg, reply_markup=get_main_keyboard(lang))

        elif text in ["👤 حسابي", "👤 My Account"]:
            status_str = "VIP ⭐" if is_vip else f"{trials} free trials remaining"
            if lang == 'ar':
                acc_msg = f"👤 **معلومات الحساب:**\n▫️ **المعرف (ID):** `{user_id}`\n▫️ **الرصيد/الحالة:** {status_str}"
            else:
                acc_msg = f"👤 **Account Info:**\n▫️ **User ID:** `{user_id}`\n▫️ **Status:** {status_str}"
            send_telegram_message(chat_id, acc_msg)

        elif text in ["💎 الاشتراك", "💎 Subscription", "/subscribe"]:
            send_subscription_info(chat_id, lang)

        elif text in ["🌐 تغيير اللغة", "🌐 Change Language"]:
            new_lang = 'en' if lang == 'ar' else 'ar'
            set_user_language(user_id, new_lang)
            confirm_msg = "تم تغيير اللغة إلى العربية 🇸🇦" if new_lang == 'ar' else "Language changed to English 🇬🇧"
            send_telegram_message(chat_id, confirm_msg, reply_markup=get_main_keyboard(new_lang))

        # --- لوحة التحكم الخاصة بك كآدمين لتفعيل الاشتراكات ---
        # استخدام الأمر: /vip USER_ID (مثال: /vip 12345678)
        elif text.startswith("/vip") and str(user_id) == str(ADMIN_ID):
            parts = text.split()
            if len(parts) > 1:
                target_user_id = parts[1]
                with get_db() as conn:
                    conn.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_user_id,))
                    conn.commit()
                send_telegram_message(chat_id, f"✅ تم تفعيل الاشتراك VIP للمستخدم `{target_user_id}` بنجاح!")
                send_telegram_message(target_user_id, "🎉 **مبروك! تم تفعيل اشتراكك الـ VIP بنجاح. يمكنك الآن تحليل عدد لا محدود من الشارتات!**")

    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
