import os
import threading
import telebot
from flask import Flask
from telebot import types

TOKEN = "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

users_data = {}
WALLET_ADDRESS = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"
ADMIN_ID = 8655689754
ADMIN_USERNAME = "@TradeGuard_Admin"


@app.route("/", methods=["GET"])
def index():
  return "Bot is alive and running successfully!", 200


def run_bot():
  try:
    bot.remove_webhook()
    print("Starting bot polling...")
    bot.infinity_polling(skip_pending=True)
  except Exception as e:
    print(f"Polling error: {e}")


threading.Thread(target=run_bot, daemon=True).start()


@bot.message_handler(commands=["start"])
def send_welcome(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

  # أزرار واضحة تظهر أسفل لوحة المفاتيح مباشرة لضمان عدم ضياعها
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
  markup.add("🇸🇦 العربية", "🇬🇧 English")

  welcome_text = (
      f"أهلاً بك في بوت التحليل الذكي للأسواق المالية!\n"
      f"معرفك الخاص (ID): `{user_id}`\n\n"
      f"الرجاء اختيار لغة التحليل بالضغط على الزر أسفل الشات:"
  )
  bot.send_message(
      message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown"
  )


@bot.message_handler(func=lambda msg: msg.text in ["🇸🇦 العربية", "عربي", "العربية"])
def set_lang_ar(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
  users_data[user_id]["lang"] = "ar"
  show_main_menu(message, "ar")


@bot.message_handler(func=lambda msg: msg.text in ["🇬🇧 English", "English"])
def set_lang_en(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
  users_data[user_id]["lang"] = "en"
  show_main_menu(message, "en")


@bot.message_handler(
    func=lambda msg: msg.text in ["📊 حسابي ومعلوماتي", "📊 My Account & Info"]
)
def handle_account_button(message):
  show_account_info(message, message.from_user.id)


@bot.message_handler(
    func=lambda msg: msg.text in ["💎 خطط الاشتراكات", "💎 Subscription Plans"]
)
def handle_sub_button(message):
  user_id = message.from_user.id
  lang = users_data.get(user_id, {}).get("lang", "ar")
  show_subscription_plans(message, lang)


def show_main_menu(message, lang):
  markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
  if lang == "ar":
    markup.add("📊 حسابي ومعلوماتي", "💎 خطط الاشتراكات")
    bot.send_message(
        message.chat.id,
        "تم اختيار اللغة العربية بنجاح ✅.\nالقائمة الرئيسية جاهزة. أرسل صورة"
        " الشارت الآن وسيقوم البوت بتحليله!",
        reply_markup=markup,
    )
  else:
    markup.add("📊 My Account & Info", "💎 Subscription Plans")
    bot.send_message(
        message.chat.id,
        "English selected successfully ✅.\nMain menu ready. Send the chart"
        " image now to analyze!",
        reply_markup=markup,
    )


def show_account_info(message, user_id):
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
  user = users_data[user_id]
  lang = user["lang"]
  trials = user["trials"]
  sub_status = "مشترك (مفعل) ⭐" if user["subscribed"] else "غير مشترك ❌"

  if lang == "ar":
    text = (
        f"📋 **معلومات الحساب:**\n\n- الـ ID الخاص بك: `{user_id}`\n- المحاولات"
        f" المجانية المتبقية: `{trials}`\n- حالة الاشتراك: `{sub_status}`"
    )
  else:
    text = (
        f"📋 **Account Info:**\n\n- Your ID: `{user_id}`\n- Remaining Free"
        f" Trials: `{trials}`\n- Subscription Status: `{sub_status}`"
    )
  bot.send_message(message.chat.id, text, parse_mode="Markdown")


def show_subscription_plans(message, lang):
  if lang == "ar":
    text = (
        f"💎 **خطط الاشتراكات والأسعار:**\n\n"
        f"1️⃣ **اشتراك 10 أيام:** `15 دولاراً`\n"
        f"2️⃣ **اشتراك شهري (30 يوماً):** `38 دولاراً`\n\n"
        f"💳 **طريقة الدفع (شبكة TON):**\n"
        f"عنوان المحفظة:\n`{WALLET_ADDRESS}`\n\n"
        f"📩 بعد التحويل، أرسل صورة إيصال الدفع مع الـ ID الخاص بك إلى حساب الأدمن"
        f" لتفعيل اشتراكك:\n{ADMIN_USERNAME}"
    )
  else:
    text = (
        f"💎 **Subscription Plans & Pricing:**\n\n"
        f"1️⃣ **10 Days Plan:** `$15`\n"
        f"2️⃣ **Monthly Plan (30 Days):** `$38`\n\n"
        f"💳 **Payment Method (TON Network):**\n"
        f"Wallet Address:\n`{WALLET_ADDRESS}`\n\n"
        f"📩 After payment, send the receipt and your ID to admin for"
        f" activation:\n{ADMIN_USERNAME}"
    )
  bot.send_message(message.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=["activate"])
def admin_activate(message):
  if message.from_user.id != ADMIN_ID:
    bot.reply_to(message, "هذا الأمر مخصص للمسؤول فقط.")
    return

  try:
    parts = message.text.split()
    target_user_id = int(parts[1])
    if target_user_id in users_data:
      users_data[target_user_id]["subscribed"] = True
      bot.reply_to(
          message, f"تم تفعيل الاشتراك للمستخدم بنجاح: {target_user_id}"
      )
      bot.send_message(
          target_user_id,
          "🎉 تهانينا! تم تفعيل اشتراكك بنجاح. يمكنك الآن إرسال الشارتات بلا"
          " حدود.",
      )
    else:
      bot.reply_to(message, "المستخدم غير موجود في الذاكرة المؤقتة للبوت.")
  except Exception:
    bot.reply_to(message, "خطأ في الصيغة. استخدم الأمر هكذا: /activate <user_id>")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

  user = users_data[user_id]
  lang = user["lang"]

  if not user["subscribed"] and user["trials"] <= 0:
    if lang == "ar":
      bot.reply_to(
          message,
          "❌ عذراً، لقد نفدت جميع محاولاتك المجانية (3/3).\nللاشتراك، يرجى"
          f" التحويل إلى المحفظة ومراسلة الإدارة عبر: {ADMIN_USERNAME}",
      )
    else:
      bot.reply_to(
          message,
          "❌ Sorry, your free trials have expired (3/3).\nTo subscribe,"
          f" please pay and contact admin at: {ADMIN_USERNAME}",
      )
    return

  if not user["subscribed"]:
    user["trials"] -= 1

  remaining = user["trials"]

  if lang == "ar":
    bot.reply_to(
        message,
        f"🔍 تم استلام الشارت بنجاح.\nجاري تحليل المعطيات باللغة"
        f" العربية...\n(المحاولات المجانية المتبقية: {remaining})",
    )
  else:
    bot.reply_to(
        message,
        f"🔍 Chart received successfully.\nAnalyzing data in English...\n(Remaining"
        f" free trials: {remaining})",
    )
