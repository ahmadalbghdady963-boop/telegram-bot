import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, abort
import requests
from telebot import TeleBot, types

# جلب المتغيرات البيئية من ريندر
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))

# البيانات الإدارية
ADMIN_ID = "8655689754"
RENDER_APP_URL = "https://telegram-bot-pqy3.onrender.com"
WALLET_TON = "UQClWc3pSNcpxdYrRstljCDLKYcTY760blJnIElyieA"
ADMIN_USERNAME = "@TradeGuard_Admin"

bot = TeleBot(TOKEN)
app = Flask(__name__)
USER_CACHE = {}
PROCESSED_TON_TXS = set()

# ---------------------------------------------------------
# 1. نظام الفحص التلقائي لمدفوعات شبكة TON (الخيار 1)
# ---------------------------------------------------------
def check_ton_payments_loop():
    """خلفية تعقب تحويلات شبكة TON وتفعيل الاشتراكات تلقائياً عند التطابق"""
    while True:
        try:
            url = f"https://toncenter.com/api/v2/getTransactions?address={WALLET_TON}&limit=20"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("ok"):
                    txs = data.get("result", [])
                    for tx in txs:
                        tx_hash = tx.get("transaction_id", {}).get("hash")
                        if not tx_hash or tx_hash in PROCESSED_TON_TXS:
                            continue
                        
                        in_msg = tx.get("in_msg", {})
                        comment = in_msg.get("message", "").strip()
                        
                        # التأكد من أن الملاحظة تحتوي على آيدي المستخدم
                        if comment.isdigit():
                            target_user_id = comment
                            # تفعيل الاشتراك تلقائياً لمدة 30 يوم
                            new_expiry = (datetime.now() + timedelta(days=30)).isoformat()
                            update_user_data(target_user_id, {"expiry_date": new_expiry})
                            PROCESSED_TON_TXS.add(tx_hash)
                            
                            try:
                                bot.send_message(
                                    target_user_id,
                                    "🎉 **تم تأكيد استلام التحويل تلقائياً عبر شبكة TON!**\n\n"
                                    "✅ تم تفعيل حسابك بنجاح لمدة 30 يوماً.\n"
                                    "يمكنك الآن إرسال الشارتات والحصول على تحليلات غير محدودة!",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                print(f"Error sending activation notification to {target_user_id}: {e}")
        except Exception as e:
            print(f"TON Payment verification loop error: {e}")
        
        time.sleep(30)

# تشغيل خيط التحقق التلقائي في الخلفية
threading.Thread(target=check_ton_payments_loop, daemon=True).start()

# ---------------------------------------------------------
# المسارات المساعدة والذاكرة
# ---------------------------------------------------------
@app.route("/")
def home():
    return "TradeGuard AI Bot is active and running!"

@app.route("/health")
def health():
    return "OK", 200

@app.route(f"/{TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        abort(403)

def get_user_data(user_id):
    user_id = str(user_id)
    if user_id not in USER_CACHE:
        USER_CACHE[user_id] = {
            "trials": 0,
            "expiry_date": "",
            "lang": "ar",
            "referrals_count": 0
        }
        if FIREBASE_URL:
            try:
                res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=5)
                if res.status_code == 200 and res.json():
                    USER_CACHE[user_id].update(res.json())
            except Exception as e:
                print(f"Firebase fetch error: {e}")
    return USER_CACHE[user_id]

def update_user_data(user_id, data):
    user_id = str(user_id)
    if user_id not in USER_CACHE:
        get_user_data(user_id)
    USER_CACHE[user_id].update(data)
    if FIREBASE_URL:
        try:
            requests.patch(f"{FIREBASE_URL}/users/{user_id}.json", json=data, timeout=5)
        except Exception as e:
            print(f"Firebase update error: {e}")

# ---------------------------------------------------------
# الأوامر الإدارية والترحيبية
# ---------------------------------------------------------
@bot.message_handler(commands=['activate'])
def activate_user(message):
    if str(message.from_user.id) != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        target_user_id = parts[1]
        days = int(parts[2])
        
        new_expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
        update_user_data(target_user_id, {"expiry_date": new_expiry_date})
        
        bot.reply_to(message, f"✅ تم تفعيل الاشتراك للمستخدم `{target_user_id}` لمدة {days} يوم بنجاح.", parse_mode="Markdown")
        bot.send_message(target_user_id, f"🎉 **تم تفعيل حسابك بنجاح لمدة {days} يوم!**\nاستمتع بتحليل الشارتات بلا حدود 🚀", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ في الصيغة.\nالاستخدام الصحيح:\n`/activate <user_id> <days>`", parse_mode="Markdown")

# ---------------------------------------------------------
# 2. نظام الإحالة والرابط الدعائي (الخيار 4) + Start
# ---------------------------------------------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = str(message.from_user.id)
        text_parts = message.text.split()
        
        is_new_user = False
        if user_id not in USER_CACHE:
            if FIREBASE_URL:
                res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=3)
                if not (res.status_code == 200 and res.json()):
                    is_new_user = True
            else:
                is_new_user = True

        user_data = get_user_data(user_id)
        
        # كود معالجة الإحالة
        if len(text_parts) > 1 and is_new_user:
            referrer_id = text_parts[1].strip()
            if referrer_id != user_id:
                ref_data = get_user_data(referrer_id)
                current_trials = ref_data.get("trials", 0)
                new_trials = max(0, current_trials - 1) # خصم محاولة مُستهلكة يمنح محاولة إضافية
                ref_count = ref_data.get("referrals_count", 0) + 1
                update_user_data(referrer_id, {"trials": new_trials, "referrals_count": ref_count})
                
                try:
                    bot.send_message(
                        referrer_id,
                        "🎁 **مكافأة إحالة جديدة!**\n\nقام مستخدم جديد بالانضمام عبر رابطك. حصلت على **+1 محاولة تحليل مجانية إضافية**!",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Error notifying referrer: {e}")

        trials = user_data.get("trials", 0)
        expiry_date_str = user_data.get("expiry_date", "")
        
        is_subscribed = False
        if expiry_date_str:
            try:
                if datetime.now() < datetime.fromisoformat(expiry_date_str):
                    is_subscribed = True
            except Exception:
                pass
        
        remaining_trials = max(0, 3 - trials)
        remaining_ar = "♾️ غير محدود (مشترك)" if is_subscribed else f"{remaining_trials} محاولات"
        remaining_en = "Unlimited (Subscribed) ♾️" if is_subscribed else f"{remaining_trials} trials"
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_ar = types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
        btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        markup.add(btn_ar, btn_en)
        
        welcome_text = (
            f"مرحباً بك في TradeGuard AI!\n"
            f"Welcome to TradeGuard AI!\n\n"
            f"📊 المحاولات المتبقية: {remaining_ar}\n"
            f"📊 Remaining trials: {remaining_en}\n\n"
            f"الرجاء اختيار لغتك المفضلة:\n"
            f"Please select your preferred language:"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=markup)
    except Exception as e:
        print(f"Error in start command: {e}")

# ---------------------------------------------------------
# 3. لوحة تحكم ملف المستخدم (الخيار 3)
# ---------------------------------------------------------
@bot.message_handler(commands=['profile'])
def show_profile(message):
    try:
        user_id = str(message.from_user.id)
        user_data = get_user_data(user_id)
        lang = user_data.get("lang", "ar")
        trials = user_data.get("trials", 0)
        expiry_date_str = user_data.get("expiry_date", "")
        ref_count = user_data.get("referrals_count", 0)
        
        is_subscribed = False
        if expiry_date_str:
            try:
                if datetime.now() < datetime.fromisoformat(expiry_date_str):
                    is_subscribed = True
            except Exception:
                pass
        
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        remaining_trials = max(0, 3 - trials)
        
        if lang == "ar":
            status = "✅ مشترك مدفوع" if is_subscribed else "🆓 حساب مجاني"
            expiry_info = expiry_date_str[:10] if is_subscribed else "لا يوجد"
            profile_msg = (
                f"👤 **الملف الشخصي للمستخدم**\n\n"
                f"🆔 **الآيدي الخاص بك:** `{user_id}`\n"
                f"📌 **حالة الاشتراك:** {status}\n"
                f"📅 **تاريخ الانتهاء:** {expiry_info}\n"
                f"📊 **المحاولات المجانية المتبقية:** {remaining_trials} من 3\n"
                f"👥 **عدد الإحالات:** {ref_count}\n\n"
                f"🔗 **رابط الدعوة الخاص بك:**\n`{ref_link}`\n"
                f"_(شارك الرابط مع أصدقائك للحصول على +1 محاولة تحليل مجانية لكل شخص ينضم!)_"
            )
        else:
            status = "✅ Subscribed" if is_subscribed else "🆓 Free Account"
            expiry_info = expiry_date_str[:10] if is_subscribed else "N/A"
            profile_msg = (
                f"👤 **User Profile**\n\n"
                f"🆔 **Your User ID:** `{user_id}`\n"
                f"📌 **Status:** {status}\n"
                f"📅 **Expiry Date:** {expiry_info}\n"
                f"📊 **Remaining Free Trials:** {remaining_trials} of 3\n"
                f"👥 **Referrals Count:** {ref_count}\n\n"
                f"🔗 **Your Referral Link:**\n`{ref_link}`\n"
                f"_(Share this link to earn +1 free trial for every friend who joins!)_"
            )
        bot.reply_to(message, profile_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in profile command: {e}")

# ---------------------------------------------------------
# معالجة اللغات ومعالجة الصور وتحليل Dify
# ---------------------------------------------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
def set_language(call):
    try:
        user_id = str(call.from_user.id)
        lang = call.data.split("_")[1]
        update_user_data(user_id, {"lang": lang})
        
        if lang == "ar":
            text = "✅ تم اختيار اللغة العربية.\nأرسل لي الآن صورة لأي شارت وسأقوم بتحليله فنياً لك."
        else:
            text = "✅ English language selected successfully.\nSend me a chart photo now to analyze it for you."
        
        bot.answer_callback_query(call.id)
        bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=call.message.message_id)
    except Exception as e:
        print(f"Error in callback: {e}")

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    threading.Thread(target=process_chart_image, args=(message,)).start()

def process_chart_image(message):
    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    
    trials = user_data.get("trials", 0)
    expiry_date_str = user_data.get("expiry_date", "")
    lang = user_data.get("lang", "ar")
    
    is_subscribed = False
    if expiry_date_str:
        try:
            if datetime.now() < datetime.fromisoformat(expiry_date_str):
                is_subscribed = True
        except Exception:
            pass
            
    if not is_subscribed and trials >= 3:
        if lang == "ar":
            sub_msg = (
                f"⚠️ **انتهت المحاولات المجانية!**\n\n"
                f"للاشتراك والحصول على تحليلات غير محدودة:\n"
                f"🥇 **بااقة 10 أيام ($15)** | 🏆 **الباقة الشهرية ($38)**\n"
                f"💳 **الدفع عبر شبكة TON:**\n`{WALLET_TON}`\n\n"
                f"✅ **للتفعيل:**\n"
                f"قم بنسخ هذا الرقم (الآيدي الخاص بك)\n`{user_id}`\n"
                f"وضعه في ملاحظة التحويل (Memo/Comment) ليتفعل حسابك تلقائياً، أو أرسل صورة التحويل للإدارة: {ADMIN_USERNAME}"
            )
        else:
            sub_msg = (
                f"⚠️ **Your free trials have ended!**\n\n"
                f"To subscribe and get unlimited chart analysis:\n"
                f"🥇 **10-Day Plan ($15)** | 🏆 **Monthly Plan ($38)**\n"
                f"💳 **Pay via TON network:**\n`{WALLET_TON}`\n\n"
                f"✅ **To Activate:**\n"
                f"Copy this ID: `{user_id}`\n"
                f"And include it in the transfer memo/comment for auto-activation, or send the receipt to support: {ADMIN_USERNAME}"
            )
        bot.reply_to(message, sub_msg, parse_mode="Markdown")
        return

    msg = bot.reply_to(message, "⏳ جاري تحميل الصورة..." if lang == "ar" else "⏳ Uploading image...")
    
    try:
        file_id = message.photo[-1].file_id
        file_info_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
        file_res = requests.get(file_info_url, timeout=10).json()
        
        if not file_res.get("ok"):
            raise Exception("Failed to fetch file info from Telegram")
            
        file_path = file_res["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        
        img_res = requests.get(download_url, timeout=30)
        downloaded_file = img_res.content
        
        bot.edit_message_text(
            chat_id=message.chat.id, 
            message_id=msg.message_id, 
            text="⏳ جاري رفع الصورة إلى الخادم..." if lang == "ar" else "⏳ Uploading image to server..."
        )
        
        upload_url = "https://api.dify.ai/v1/files/upload"
        headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
        files_data = {"file": ("chart.jpg", downloaded_file, "image/jpeg")}
        data_upload = {"user": user_id}
        
        upload_response = requests.post(upload_url, headers=headers_upload, files=files_data, data=data_upload)
        
        if upload_response.status_code not in [200, 201]:
            raise Exception("Upload failed")
            
        upload_result = upload_response.json()
        dify_file_id = upload_result.get("id")
        
        bot.edit_message_text(
            chat_id=message.chat.id, 
            message_id=msg.message_id, 
            text="⏳ جاري تحليل الشارت فنياً..." if lang == "ar" else "⏳ Analyzing chart..."
        )
        
        chat_url = "https://api.dify.ai/v1/chat-messages"
        
        if lang == "ar":
            query_text = "حلل هذا الشارت تحليلاً فنياً مفصلاً باللغة العربية حصراً"
        else:
            query_text = (
                "CRITICAL INSTRUCTION: Respond strictly and entirely in English.\n"
                "Analyze this chart in detail including: Trend, Support/Resistance, and Candlestick patterns."
            )
            
        payload = {
            "inputs": {},
            "query": query_text,
            "response_mode": "blocking",
            "user": user_id,
            "files": [{"type": "image", "transfer_method": "local_file", "upload_file_id": dify_file_id}]
        }
        
        headers_chat = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
        
        response = requests.post(chat_url, headers=headers_chat, json=payload)
        
        if response.status_code != 200:
            raise Exception("Chat API failed")
            
        result = response.json()
        answer = result.get("answer", "عذراً، حدث خطأ في القراءة." if lang == "ar" else "Sorry, reading error occurred.")
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=answer)
        
        if not is_subscribed:
            new_trials = trials + 1
            update_user_data(user_id, {"trials": new_trials})
            remaining = max(0, 3 - new_trials)
            rem_msg = f"ℹ️ لديك {remaining} محاولات مجانية متبقية." if lang == "ar" else f"ℹ️ You have {remaining} free trials remaining."
            bot.send_message(message.chat.id, rem_msg)
            
    except Exception as e:
        bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=f"❌ حدث خطأ أثناء التحليل: {e}")

# ---------------------------------------------------------
# ضبط الـ Webhook وتطبيق Flask
# ---------------------------------------------------------
def setup_webhook():
    try:
        bot.remove_webhook()
        bot.set_webhook(url=f"{RENDER_APP_URL}/{TOKEN}")
    except Exception as e:
        print(f"Failed to set Webhook: {e}")

setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
