from datetime import datetime, timedelta
import os
import threading
from flask import Flask, request, abort
import requests
from telebot import TeleBot, types

# === المتغيرات الأساسية ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))

# === إعدادات الإدارة والتطبيق ===
ADMIN_ID = "8655689754"
ADMIN_USERNAME = "@TradeGuard_Admin"
RENDER_APP_URL = "https://telegram-bot-pqy3.onrender.com"
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"

bot = TeleBot(TOKEN)
app = Flask(__name__)
USER_CACHE = {}

# === مسارات الويب هوك ===
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

# === قواعد البيانات ===
def get_user_data(user_id):
  if user_id not in USER_CACHE:
    USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}

  if FIREBASE_URL:
    try:
      res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=3)
      if res.status_code == 200 and res.json():
        USER_CACHE[user_id].update(res.json())
    except Exception as e:
      print(f"Firebase fetch error: {e}")

  return USER_CACHE[user_id]

def update_user_data(user_id, data):
  if user_id not in USER_CACHE:
    USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}

  USER_CACHE[user_id].update(data)

  if FIREBASE_URL:
    try:
      requests.patch(f"{FIREBASE_URL}/users/{user_id}.json", json=data, timeout=3)
    except Exception as e:
      print(f"Firebase update error: {e}")

# === أمر التفعيل الخاص بك (للإدارة فقط) ===
@bot.message_handler(commands=['activate'])
def activate_user(message):
  if str(message.from_user.id) != ADMIN_ID:
    return 

  try:
    parts = message.text.split()
    target_user_id = parts[1]
    days = int(parts[2])

    new_expiry_date = (datetime.now() + timedelta(days=days)).isoformat()
    update_user_data(target_user_id, {"expiry_date": new_expiry_date, "trials": 0})
    
    bot.reply_to(message, f"✅ تم تفعيل المشترك `{target_user_id}` لمدة {days} يوم بنجاح.", parse_mode="Markdown")
    bot.send_message(target_user_id, f"🎉 **تم تفعيل اشتراكك بنجاح لمدة {days} يوم!**\nيمكنك الآن إرسال الشارتات بلا حدود.", parse_mode="Markdown")
    
  except Exception as e:
    bot.reply_to(message, "❌ **خطأ في الصيغة.**\nالاستخدام الصحيح:\n`/activate <آيدي_المشترك> <عدد_الأيام>`\nمثال: `/activate 123456789 30`", parse_mode="Markdown")

# === واجهة المستخدم والأزرار الشفافة ===
@bot.message_handler(commands=["start"])
def send_welcome(message):
  try:
    # هذا السطر يحذف الأزرار السفلية القديمة التي وضعها صديقك
    dummy = bot.send_message(message.chat.id, "🔄...", reply_markup=types.ReplyKeyboardRemove())
    bot.delete_message(message.chat.id, dummy.message_id)

    user_id = str(message.from_user.id)
    user_data = get_user_data(user_id)
    trials = user_data.get("trials", 0)
    expiry_date_str = user_data.get("expiry_date", "")

    is_subscribed = False
    if expiry_date_str:
      try:
        if datetime.now() < datetime.fromisoformat(expiry_date_str):
          is_subscribed = True
      except Exception:
        pass

    remaining_ar = "غير محدود (مشترك) ♾️" if is_subscribed else f"{max(0, 3 - trials)} من 3"
    remaining_en = "Unlimited (Subscribed) ♾️" if is_subscribed else f"{max(0, 3 - trials)} of 3"

    # الأزرار الشفافة الأصلية
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def set_language(call):
  try:
    user_id = str(call.from_user.id)
    lang = call.data.split("_")[1]
    update_user_data(user_id, {"lang": lang})

    if lang == "ar":
      text = "✅ تم اختيار اللغة العربية بنجاح.\nأرسل لي الآن صورة لأي شارت وسأقوم بتحليله فنياً لك."
    else:
      text = "✅ English language selected successfully.\nNow send me any chart image and I will analyze it for you."

    bot.answer_callback_query(call.id)
    bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=call.message.message_id)
  except Exception as e:
    print(f"Error in callback: {e}")

# === معالجة الصور والذكاء الاصطناعي ===
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

  # رسالة الاشتراك مفصلة بالأسعار الجديدة
  if not is_subscribed and trials >= 3:
    if lang == "ar":
      sub_msg = (
          "⚠️ **انتهت محاولاتك المجانية!**\n\n"
          "للاشتراك والحصول على تحليلات غير محدودة دقيقة، اختر إحدى الباقات:\n\n"
          "🥉 **باقة 10 أيام (15$)**\n"
          "🏆 **باقة 30 يوم (40$)**\n\n"
          "💳 **خطوات الاشتراك:**\n"
          "1️⃣ قم بتحويل المبلغ عبر شبكة TON إلى المحفظة التالية:\n"
          f"`{WALLET_TON}`\n"
          "*(اضغط على عنوان المحفظة لنسخه)*\n\n"
          "2️⃣ انسخ الرقم التعريفي الخاص بك (ID):\n"
          f"`{user_id}`\n\n"
          "3️⃣ أرسل صورة إيصال الدفع مع الرقم التعريفي للإدارة لتفعيل حسابك فوراً:\n"
          f"👉 {ADMIN_USERNAME}"
      )
    else:
      sub_msg = (
          "⚠️ **Your free trials have ended!**\n\n"
          "To subscribe for unlimited analysis, choose a plan:\n\n"
          "🥉 **10-Day Plan ($15)**\n"
          "🏆 **30-Day Plan ($40)**\n\n"
          "💳 **How to subscribe:**\n"
          "1️⃣ Transfer the amount via TON network to this wallet:\n"
          f"`{WALLET_TON}`\n"
          "*(Tap the wallet address to copy)*\n\n"
          "2️⃣ Copy your ID:\n"
          f"`{user_id}`\n\n"
          "3️⃣ Send the payment receipt and your ID to the admin to activate your account:\n"
          f"👉 {ADMIN_USERNAME}"
      )
    bot.reply_to(message, sub_msg, parse_mode="Markdown")
    return

  msg = bot.reply_to(message, "⏳ جاري فحص وتحليل الصورة..." if lang == "ar" else "⏳ Inspecting and analyzing image...")

  try:
    file_id = message.photo[-1].file_id
    file_info_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
    file_res = requests.get(file_info_url, timeout=10).json()

    if not file_res.get("ok"):
      raise Exception("Failed to fetch file info")

    file_path = file_res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    
    img_res = requests.get(download_url, timeout=30)
    downloaded_file = img_res.content

    upload_url = "https://api.dify.ai/v1/files/upload"
    headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
    files_data = {"file": ("chart.jpg", downloaded_file, "image/jpeg")}
    data_upload = {"user": user_id}

    upload_response = requests.post(upload_url, headers=headers_upload, files=files_data, data=data_upload, timeout=30)
    
    if upload_response.status_code not in [200, 201]:
      raise Exception("Upload failed")

    upload_result = upload_response.json()
    dify_file_id = upload_result.get("id")

    chat_url = "https://api.dify.ai/v1/chat-messages"
    
    # الفحص الذكي للصور
    if lang == "ar":
        query_text = (
            "قم بفحص هذه الصورة بدقة. إذا كانت الصورة لا تحتوي على شارت تداول، أو رسوم بيانية مالية، أو منصة تداول (مثل صورة شخصية، إيصال دفع، لقطة شاشة عادية)، "
            "فلا تقم بتحليلها واكتب بالحرف الواحد فقط: 'NOT_CHART'.\n"
            "أما إذا كانت شارت تداول، فقم بتحليلها فنياً بشكل مفصل، وفي النهاية أضف تحذير أن التداول مسؤولية شخصية."
        )
    else:
        query_text = (
            "Inspect this image. If it DOES NOT contain a trading chart (e.g., selfie, receipt), output exactly: 'NOT_CHART'.\n"
            "If it is a valid chart, analyze it technically in ENGLISH ONLY, and add a risk warning."
        )

    payload = {
        "inputs": {},
        "query": query_text,
        "response_mode": "blocking",
        "user": user_id,
        "files": [{"type": "image", "transfer_method": "local_file", "upload_file_id": dify_file_id}]
    }
    
    headers_chat = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    response = requests.post(chat_url, headers=headers_chat, json=payload, timeout=120)

    if response.status_code != 200:
      raise Exception("API Error")

    result = response.json()
    answer = result.get("answer", "Error.")

    # رفض الصور العشوائية
    if "NOT_CHART" in answer:
      warning_text = (
          "⚠️ **عذراً، هذه ليست صورة شارت تداول!**\n"
          "الرجاء إرسال رسوم بيانية صحيحة للتحليل.\n\n"
          f"💡 *ملاحظة:* إذا كنت ترسل إيصال الدفع، أرسله مباشرة للإدارة: {ADMIN_USERNAME}"
      ) if lang == "ar" else (
          "⚠️ **Sorry, this is not a trading chart!**\n"
          "Please send a valid chart.\n\n"
          f"💡 *Note:* Send payment receipts directly to: {ADMIN_USERNAME}"
      )
      bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=warning_text, parse_mode="Markdown")
      return

    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=answer)

    # خصم محاولة فقط عند النجاح
    if not is_subscribed:
      new_trials = trials + 1
      update_user_data(user_id, {"trials": new_trials})
      remaining = max(0, 3 - new_trials)
      rem_msg = f"ℹ️ لديك {remaining} محاولات مجانية متبقية." if lang == "ar" else f"ℹ️ You have {remaining} free trials remaining."
      bot.send_message(message.chat.id, rem_msg)

  except Exception as e:
    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text="❌ عذراً، حدث خطأ في النظام. يرجى المحاولة لاحقاً.")

# === إعداد الويب هوك ===
def setup_webhook():
  try:
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_APP_URL}/{TOKEN}")
  except Exception as e:
    pass

setup_webhook()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=PORT)
