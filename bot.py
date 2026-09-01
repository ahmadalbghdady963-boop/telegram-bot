import os
import sqlite3
import requests
import threading
import time
import traceback
from flask import Flask, request
import google.generativeai as genai
from PIL import Image
import io

# ==================== 1. التكوين والتهيئات ====================
# استخدمنا strip() لمنع أي مشاكل بسبب المسافات الفارغة عند نسخ المفاتيح
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()
SERVER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-bot-pqy3.onrender.com")

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

# ==================== 3. ميزة البقاء مستيقظاً ====================
def keep_alive():
    while True:
        time.sleep(600)
        try:
            if SERVER_URL:
                requests.get(SERVER_URL, timeout=10)
                print("[Keep-Alive] Pinged server successfully.")
        except Exception as e:
            pass # نتجاهل أخطاء البينغ الصامتة

threading.Thread(target=keep_alive, daemon=True).start()

# ==================== 4. نظام المراسلة الدقيق (HTML) ====================
def send_telegram_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"  # تم التغيير إلى HTML لمنع أعطال تيليجرام نهائياً
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(url, json=payload, timeout=15)
        # هذا السطر سيكشف لنا أي خطأ مخفي في سجلات Render
        if res.status_code != 200:
            print(f"❌ Telegram API Error [{res.status_code}]: {res.text}")
    except Exception as e:
        print(f"❌ Network Error sending message: {e}")

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
            "💎 <b>باقات الاشتراك في TradeGuard AI</b>\n\n"
            "📌 <b>الباقات المتاحة:</b>\n"
            "▫️ <b>باقة 10 أيام:</b> 20$ (تحليل غير محدود)\n"
            "▫️ <b>الباقة الشهرية (30 يوم):</b> 50$ (تحليل غير محدود)\n\n"
            "💳 <b>عنوان محفظة الدفع (USDT - TRC20):</b>\n"
            "<code>TQxYourTRC20WalletAddressHereID</code>\n\n"
            "📩 <b>طريقة التفعيل:</b>\n"
            "بعد إتمام عملية التحويل، يرجى إرسال لقطة شاشة لإشعار الدفع مع معرف حسابك إلى الإدارة لتفعيل الاشتراك فوراً:\n"
            "👤 <b>الدعم الفني والاشتراكات:</b> @Ahmad_Admin"
        )
    else:
        msg = (
            "💎 <b>TradeGuard AI Subscription Plans</b>\n\n"
            "📌 <b>Available Plans:</b>\n"
            "▫️ <b>10-Day Pass:</b> $20 (Unlimited)\n"
            "▫️ <b>Monthly Pass (30 Days):</b> $50 (Unlimited)\n\n"
            "💳 <b>USDT (TRC20) Payment Address:</b>\n"
            "<code>TQxYourTRC20WalletAddressHereID</code>\n\n"
            "📩 <b>How to Activate:</b>\n"
            "After completing the transfer, please send a screenshot of the transaction receipt along with your User ID to Admin for instant activation:\n"
            "👤 <b>Support & Subscriptions:</b> @Ahmad_Admin"
        )
    send_telegram_message(chat_id, msg)

# ==================== 5. تحليل الشارت والتوجيهات الصارمة ====================
def analyze_chart_with_gemini(image_bytes, lang='en'):
    prompt_ar = """
    أنت خبير تحليل فني وتداول محترف. قم بتحليل صورة الشارت المرفقة وقدم التقرير الفني حصراً بالتنسيق التالي:

    <b>1. اتجاه السوق (Market Trend):</b> شرح مختصر للهيكل.
    <b>2. المستويات الرئيسية:</b>
       - المقاومات (Key Resistances): حدد الأرقام بدقة.
       - الدعوم (Key Supports): حدد الأرقام بدقة.
    <b>3. تفاصيل الصفقة المقترحة (Trade Setup):</b>
       - نقطة الدخول (Entry Point): حدد السعر أو المنطقة.
       - وقف الخسارة (Stop Loss): حدد مستوى إيقاف الخسارة بدقة.
       - المكسب الأول (Take Profit 1): الهدف الأول.
       - المكسب الثاني (Take Profit 2): الهدف الثاني.
    <b>4. نسبة نجاح الصفقة (Probability):</b> نسبة مئوية (مثل 65%).
    <b>5. الخلاصة والنصيحة (Advice):</b> (انتظار / شراء / بيع).

    تحذير هام جداً: يجب تنسيق التقرير باستخدام لغة HTML فقط (استخدم <b> للنص العريض). يمنع استخدام علامات Markdown مثل (**) أو (#) نهائياً.
    """

    prompt_en = """
    You are a professional technical analysis trader. Analyze the chart and format the reply strictly as follows:

    <b>1. Market Trend:</b> Structure and momentum analysis.
    <b>2. Key Levels:</b>
       - Key Resistances: Exact levels.
       - Key Supports: Exact levels.
    <b>3. Trade Setup Details:</b>
       - Entry Point: Precise entry price or zone.
       - Stop Loss: Precise stop loss level.
       - Take Profit 1 (TP1): First target.
       - Take Profit 2 (TP2): Second target.
    <b>4. Probability of Success:</b> Estimated percentage (e.g., 65%).
    <b>5. Conclusion & Advice:</b> Action recommendation (WAIT / BUY / SELL).

    CRITICAL WARNING: You must format the response using standard HTML tags only (use <b> for bold). DO NOT use any Markdown syntax like (**) or (#).
    """

    prompt = prompt_ar if lang == 'ar' else prompt_en

    try:
        image = Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content([prompt, image])
        return response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content([prompt, image])
            return response.text
        except Exception as e2:
            print(f"Gemini Fallback Error: {e2}")
            return None

def process_photo_async(chat_id, user_id, photo_file_id, lang):
    wait_msg = "⏳ Please wait, performing accurate technical analysis..." if lang != 'ar' else "⏳ جاري تحليل الشارت بدقة، يرجى الانتظار..."
    send_telegram_message(chat_id, wait_msg)

    try:
        file_info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={photo_file_id}"
        res = requests.get(file_info_url).json()
        file_path = res['result']['file_path']
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        img_data = requests.get(file_url).content

        analysis = analyze_chart_with_gemini(img_data, lang)

        if analysis:
            send_telegram_message(chat_id, analysis, reply_markup=get_main_keyboard(lang))
        else:
            err_msg = "❌ فشل تحليل الصورة، يرجى إعادة المحاولة بنوع صورة أوضح." if lang == 'ar' else "❌ Failed to analyze image. Please try again."
            send_telegram_message(chat_id, err_msg)
    except Exception as e:
        print(f"Error processing photo: {e}")
        err_msg = "❌ حدث خطأ أثناء المعالجة، يرجى المحاولة لاحقاً." if lang == 'ar' else "❌ Error occurred. Please try again."
        send_telegram_message(chat_id, err_msg)

# ==================== 6. معالجة الـ Webhook المقاومة للأخطاء ====================
@app.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def webhook(path):
    if request.method == "GET":
        return "TradeGuard AI Bot is Running 24/7!", 200

    try:
        update = request.get_json(silent=True)
        if not update:
            return "OK", 200

        # دعم الرسائل المعدلة والرسائل العادية لتجنب الأعطال
        message = update.get("message") or update.get("edited_message")
        if not message or "chat" not in message:
            return "OK", 200

        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        username = message["from"].get("username", "")

        user = get_or_create_user(user_id, username)
        lang = user["language"]
        trials = user["trials"]
        is_vip = user["is_vip"]

        # معالجة الصور
        if "photo" in message:
            if not is_vip and trials <= 0:
                msg_out = "⚠️ لقد استنفذت جميع المحاولات المجانية.\nيرجى الاشتراك للاستمرار في استخدام البوت." if lang == 'ar' else "⚠️ You have reached the limit of your free trial requests.\nPlease subscribe to continue using the bot."
                send_telegram_message(chat_id, msg_out)
                send_subscription_info(chat_id, lang)
                return "OK", 200

            if not is_vip:
                new_trials = trials - 1
                update_user_trials(user_id, new_trials)

            photo = message["photo"][-1]
            threading.Thread(target=process_photo_async, args=(chat_id, user_id, photo['file_id'], lang)).start()
            return "OK", 200

        # معالجة النصوص والأوامر
        if "text" in message:
            text = message["text"].strip()

            if text.startswith("/start"):
                welcome_msg = (
                    "👋 <b>أهلاً بك في TradeGuard AI</b>\nقم بإرسال صورة الشارت للحصول على تحليل فني دقيق وإشارات الدخول والأهداف."
                    if lang == 'ar' else
                    "👋 <b>Welcome to TradeGuard AI</b>\nSend any chart image to get instant technical analysis."
                )
                send_telegram_message(chat_id, welcome_msg, reply_markup=get_main_keyboard(lang))

            elif text in ["👤 حسابي", "👤 My Account"]:
                status_str = "VIP ⭐" if is_vip else f"{trials} محاولات مجانية متبقية" if lang == 'ar' else f"{trials} free trials remaining"
                if lang == 'ar':
                    acc_msg = f"👤 <b>معلومات الحساب:</b>\n▫️ <b>المعرف (ID):</b> <code>{user_id}</code>\n▫️ <b>الرصيد/الحالة:</b> {status_str}"
                else:
                    acc_msg = f"👤 <b>Account Info:</b>\n▫️ <b>User ID:</b> <code>{user_id}</code>\n▫️ <b>Status:</b> {status_str}"
                send_telegram_message(chat_id, acc_msg)

            elif text in ["💎 الاشتراك", "💎 Subscription", "/subscribe"]:
                send_subscription_info(chat_id, lang)

            elif text in ["🌐 تغيير اللغة", "🌐 Change Language"]:
                new_lang = 'en' if lang == 'ar' else 'ar'
                set_user_language(user_id, new_lang)
                confirm_msg = "تم تغيير اللغة إلى العربية 🇸🇦" if new_lang == 'ar' else "Language changed to English 🇬🇧"
                send_telegram_message(chat_id, confirm_msg, reply_markup=get_main_keyboard(new_lang))

            # لوحة تحكم الآدمين لتفعيل الـ VIP
            elif text.startswith("/vip") and str(user_id) == str(ADMIN_ID):
                parts = text.split()
                if len(parts) > 1:
                    target_user_id = parts[1]
                    with get_db() as conn:
                        conn.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_user_id,))
                        conn.commit()
                    send_telegram_message(chat_id, f"✅ تم تفعيل الاشتراك VIP للمستخدم <code>{target_user_id}</code> بنجاح!")
                    send_telegram_message(target_user_id, "🎉 <b>مبروك! تم تفعيل اشتراكك الـ VIP بنجاح. يمكنك الآن التمتع بتحليل لا محدود!</b>")

    except Exception as e:
        print(f"❌ Error in webhook: {e}")
        traceback.print_exc()

    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
