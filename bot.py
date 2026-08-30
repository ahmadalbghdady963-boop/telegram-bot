from datetime import datetime, timedelta
import json
import os
import threading
from flask import Flask
import requests
from telebot import TeleBot, types

TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL")
PORT = int(os.getenv("PORT", 10000))

bot = TeleBot(TOKEN)
DIFY_URL = "https://api.dify.ai/v1/chat-messages"
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"

app = Flask(__name__)


@app.route("/")
def home():
  return "TradeGuard AI Bot is active and running!"


def run_flask():
  app.run(host="0.0.0.0", port=PORT)


def get_user_data(user_id):
  try:
    res = requests.get(f"{FIREBASE_URL}/users/{user_id}.json")
    if res.status_code == 200 and res.json():
      return res.json()
  except Exception:
    pass
  return {"trials": 0, "expiry_date": "", "lang": "ar"}


def update_user_data(user_id, data):
  try:
    requests.patch(f"{FIREBASE_URL}/users/{user_id}.json", json=data)
  except Exception:
    pass


@bot.message_handler(commands=["start"])
def send_welcome(message):
  markup = types.InlineKeyboardMarkup(row_width=2)
  btn_ar = types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar")
  btn_en = types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
  markup.add(btn_ar, btn_en)

  bot.send_message(
      message.chat.id,
      "مرحباً بك في TradeGuard AI!\nWelcome to TradeGuard AI!\n\nالرجاء"
      " اختيار لغتك المفضلة:\nPlease select your preferred language:",
      reply_markup=markup,
  )


@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def set_language(call):
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
      text=text, chat_id=call.message.chat.id, message_id=call.message.message_id
  )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
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

  loading_text = (
      "⏳ جاري رفع الصورة وتحليل الشارت بدقة..."
      if lang == "ar"
      else "⏳ Uploading image and analyzing chart..."
  )
  msg = bot.reply_to(message, loading_text)

  try:
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    query_text = (
        "قم بتحليل هذا الشارت تحليلاً فنياً مفصلاً باللغة العربية."
        if lang == "ar"
        else "Analyze this chart in detail with technical indicators in English."
    )

    data_json = {
        "inputs": {},
        "query": query_text,
        "response_mode": "blocking",
        "user": user_id,
    }

    files = {"files": ("chart.jpg", downloaded_file, "image/jpeg")}
    data = {"data": json.dumps(data_json)}

    headers = {"Authorization": f"Bearer {DIFY_API_KEY}"}

    response = requests.post(
        DIFY_URL, headers=headers, data=data, files=files, timeout=60
    )
    result = response.json()

    if response.status_code == 200:
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

      if not is_subscribed:
        new_trials = trials + 1
        update_user_data(user_id, {"trials": new_trials})
        remaining = 3 - new_trials
        if remaining > 0:
          rem_msg = (
              f"ℹ️ لديك {remaining} محاولات مجانية متبقية."
              if lang == "ar"
              else f"ℹ️ You have {remaining} free trials remaining."
          )
          bot.send_message(message.chat.id, rem_msg)
    else:
      err_msg = (
          f"❌ فشل الرفع: {result.get('message', 'خطأ')}"
          if lang == "ar"
          else f"❌ Error: {result.get('message', 'Unknown error')}"
      )
      bot.edit_message_text(
          chat_id=message.chat.id, message_id=msg.message_id, text=err_msg
      )

  except Exception as e:
    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"❌ Error: {str(e)}",
    )


if __name__ == "__main__":
  threading.Thread(target=run_flask).start()
  bot.infinity_polling()
