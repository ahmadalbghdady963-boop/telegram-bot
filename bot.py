import os
import telebot
from flask import Flask, request

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN", "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w"
)
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)


@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
  if request.headers.get("content-type") == "application/json":
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "", 200
  else:
    return "Forbidden", 403


@app.route("/", methods=["GET"])
def index():
  return "Bot is alive and running!", 200


@bot.message_handler(commands=["start"])
def send_welcome(message):
  bot.reply_to(
      message,
      "أهلاً بك! بوت تحليل الشارتات جاهز. أرسل صورة الشارت لنبدأ التحليل.",
  )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
  bot.reply_to(
      message,
      "تم استلام الشارت بنجاح، جاري تحليل المعطيات...",
  )


if __name__ == "__main__":
  RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
  if RENDER_URL:
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")

  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
