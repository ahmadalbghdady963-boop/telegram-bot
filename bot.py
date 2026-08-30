from datetime import datetime
import os
import threading
from flask import Flask
import requests
from telebot import TeleBot, types

# جلب المتغيرات
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))

bot = TeleBot(TOKEN)
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"

app = Flask(__name__)

# ذاكرة محلية لحفظ حالة المستخدمين فورياً
USER_CACHE = {}


@app.route("/")
def home():
  return "TradeGuard AI Bot is active and running!"


@app.route("/health")
def health():
  return "OK", 200


def get_user_data(user_id):
  # التحقق أولاً من الذاكرة المحلية
  if user_id not in USER_CACHE:
    USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}

  # جلب البيانات من Firebase إن وجد
  if FIREBASE_URL:
    try:
      res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json", timeout=3)
      if res.status_code == 200 and res.json():
        USER_CACHE[user_id].update(res.json())
    except Exception as e:
      print(f"Firebase fetch error: {e}")

  return USER_CACHE[user_id]


def update_user_data(user_id, data):
  # تحديث الذاكرة المحلية فوراً
  if user_id not in USER_CACHE:
    USER_CACHE[user_id] = {"trials": 0, "expiry_date": "", "lang": "ar"}

  USER_CACHE[user_id].update(data)

  # تحديث Firebase إن وجد
  if FIREBASE_URL:
    try:
      requests.patch(
          f"{FIREBASE_URL}/users/{user_id}.json", json=data, timeout=3
      )
    except Exception as e:
      print(f"Firebase update error: {e}")


@bot.message_handler(commands=["start"])
def send_welcome(message):
  try:
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

    remaining_ar = (
        "غير محدود (مشترك) ♾️" if is_subscribed else f"{max(0, 3 - trials)} من 3"
    )
    remaining_en = (
        "Unlimited (Subscribed) ♾️"
        if is_subscribed
        else f"{max(0, 3 - trials)} of 3"
    )

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
      text = (
          "✅ تم اختيار اللغة العربية بنجاح.\nأرسل لي الآن صورة لأي شارت وسأقوم"
          " بتحليله فنياً لك."
      )
    else:
      text = (
          "✅ English language selected successfully.\nNow send me any chart"
          " image and I will analyze it for you."
      )

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        text=text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
    )
  except Exception as e:
    print(f"Error in callback language: {e}")


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
          "⚠️ **انتهت محاولاتك المجانية الثلاث!**\n\nللاستمرار في تلقي تحليلات"
          " غير محدودة، اختر إحدى باقاتنا:\n🥉 **باقة 10 أيام (15$)**\n🏆"
          " **الباقة الشهرية (38$)**\n\n💳 **الدفع عبر TON:**\n"
          f"`{WALLET_TON}`\n\nأرسل لقطة شاشة للتحويل هنا لتفعيل حسابك."
      )
    else:
      sub_msg = (
          "⚠️ **Your 3 free trials have ended!**\n\nTo continue receiving"
          " unlimited analysis, choose a plan:\n🥉 **10-Day Plan ($15)**\n🏆"
          " **Monthly Plan ($38)**\n\n💳 **Pay via TON:**\n"
          f"`{WALLET_TON}`\n\nSend a screenshot of the transfer here to activate"
          " your account."
      )
    bot.reply_to(message, sub_msg, parse_mode="Markdown")
    return

  msg = bot.reply_to(
      message,
      "⏳ جاري تحميل الصورة..."
      if lang == "ar"
      else "⏳ Downloading image...",
  )

  try:
    file_id = message.photo[-1].file_id
    file_info_url = (
        f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
    )
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
        text=(
            "⏳ جاري رفع الصورة إلى الخادم..."
            if lang == "ar"
            else "⏳ Uploading image...",
        ),
    )

    upload_url = "https://api.dify.ai/v1/files/upload"
    headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
    files_data = {"file": ("chart.jpg", downloaded_file, "image/jpeg")}
    data_upload = {"user": user_id}

    upload_response = requests.post(
        upload_url,
        headers=headers_upload,
        files=files_data,
        data=data_upload,
        timeout=30,
    )

    if upload_response.status_code not in [200, 201]:
      raise Exception(
          f"Upload failed [{upload_response.status_code}]:"
          f" {upload_response.text}"
      )

    upload_result = upload_response.json()
    dify_file_id = upload_result.get("id")

    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=(
            "⏳ جاري تحليل الشارت فنياً..."
            if lang == "ar"
            else "⏳ Analyzing chart technically...",
        ),
    )

    chat_url = "https://api.dify.ai/v1/chat-messages"

    if lang == "ar":
      query_text = (
          "قم بتحليل هذا الشارت تحليلاً فنياً مفصلاً باللغة العربية حصراً."
      )
    else:
      query_text = (
          "CRITICAL INSTRUCTION: Respond strictly and entirely in ENGLISH."
          " Do NOT use any Arabic words.\nAnalyze this chart in detail"
          " including: Trend, Key Support & Resistance, Entry, Take Profit, and"
          " Stop Loss."
      )

    payload = {
        "inputs": {},
        "query": query_text,
        "response_mode": "blocking",
        "user": user_id,
        "files": [{
            "type": "image",
            "transfer_method": "local_file",
            "upload_file_id": dify_file_id,
        }],
    }

    headers_chat = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        chat_url, headers=headers_chat, json=payload, timeout=90
    )

    if response.status_code != 200:
      raise Exception(
          f"Chat API failed [{response.status_code}]: {response.text}"
      )

    result = response.json()
    answer = result.get(
        "answer",
        (
            "عذراً، لم يتمكن النظام من قراءة التحليل."
            if lang == "ar"
            else "Sorry, the system couldn't read the analysis."
        ),
    )
    bot.edit_message_text(
        chat_id=message.chat.id, message_id=msg.message_id, text=answer
    )

    # خصم المحاولة وتحديث البيانات
    if not is_subscribed:
      new_trials = trials + 1
      update_user_data(user_id, {"trials": new_trials})
      remaining = max(0, 3 - new_trials)

      rem_msg = (
          f"ℹ️ لديك {remaining} محاولات مجانية متبقية."
          if lang == "ar"
          else f"ℹ️ You have {remaining} free trials remaining."
      )
      bot.send_message(message.chat.id, rem_msg)

  except Exception as e:
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"❌ Error: {str(e)}",
    )


# دالة تشغيل البوت في الخلفية
def start_bot_polling():
  try:
    bot.remove_webhook()
  except Exception as e:
    print(f"Webhook remove warning: {e}")
  print("Starting Telegram Bot Polling...")
  bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)


# تفعيل البوت مباشرة
threading.Thread(target=start_bot_polling, daemon=True).start()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=PORT)
