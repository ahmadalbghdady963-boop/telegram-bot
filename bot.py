import os
import telebot

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN", "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w"
)
bot = telebot.TeleBot(TOKEN)


@bot.message_handler(commands=["start"])
def send_welcome(message):
  bot.reply_to(
      message,
      "أهلاً بك! بوت تحليل الشارتات والأسواق المالية جاهز. أرسل صورة الشارت"
      " لنبدأ التحليل.",
  )


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
  bot.reply_to(
      message,
      "تم استلام الشارت بنجاح، جاري تحليل المعطيات...",
  )


if __name__ == "__main__":
  print("Bot is starting polling...")
  try:
    bot.remove_webhook()
  except Exception:
    pass
  bot.infinity_polling(none_stop=True)
