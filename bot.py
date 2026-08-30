import os
import telebot
from flask import Flask, request
from telebot import types

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN", "8965396208:AAGN062Yh8u9H76gH_wQ4lfnvdgE8dCEt5w"
)
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# قاعدة بيانات مؤقتة للمستخدمين
users_data = {}

# بياناتك الشخصية المعتمدة
WALLET_ADDRESS = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"
ADMIN_ID = 8655689754
ADMIN_USERNAME = "@TradeGuard_Admin"

# تسجيل الويب هوك تلقائياً للعمل مع Render
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
if RENDER_URL:
  try:
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")
  except Exception as e:
    print(f"Error setting webhook: {e}")


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
  return "Bot is alive and running successfully!", 200


@bot.message_handler(commands=["start"])
def send_welcome(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
      types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
  )

  welcome_text = (
      f"أهلاً بك في بوت التحليل الذكي للأسواق المالية!\n"
      f"معرفك الخاص (ID): `{user_id}`\n\n"
      f"الرجاء اختيار لغة التحليل المفضلة لديك:\n"
      f"Please choose your preferred analysis language:"
  )
  bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
  user_id = call.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}

  if call.data == "lang_ar":
    users_data[user_id]["lang"] = "ar"
    bot.answer_callback_query(call.id, "تم اختيار اللغة العربية.")
    show_main_menu(call.message, "ar")
  elif call.data == "lang_en":
    users_data[user_id]["lang"] = "en"
    bot.answer_callback_query(call.id, "English selected.")
    show_main_menu(call.message, "en")
  elif call.data == "check_account":
    show_account_info(call.message, user_id)
  elif call.data == "subscribe_menu":
    show_subscription_plans(call.message, users_data[user_id]["lang"])


def show_main_menu(message, lang):
  markup = types.InlineKeyboardMarkup(row_width=1)
  if lang == "ar":
    markup.add(
        types.InlineKeyboardButton("📊 حسابي ومعلوماتي", callback_data="check_account"),
        types.InlineKeyboardButton("💎 خطط الاشتراكات", callback_data="subscribe_menu"),
    )
    try:
      bot.edit_message_text(
          "القائمة الرئيسية جاهزة.\nأرسل صورة الشارت الآن وسيقوم البوت بتحليله"
          " باللغة العربية!",
          message.chat.id,
          message.message_id,
          reply_markup=markup,
      )
    except Exception:
      bot.send_message(
          message.chat.id,
          "القائمة الرئيسية جاهزة.\nأرسل صورة الشارت الآن وسيقوم البوت بتحليله"
          " باللغة العربية!",
          reply_markup=markup,
      )
  else:
    markup.add(
        types.InlineKeyboardButton(
            "📊 My Account & Info", callback_data="check_account"
        ),
        types.InlineKeyboardButton(
            "💎 Subscription Plans", callback_data="subscribe_menu"
        ),
    )
    try:
      bot.edit_message_text(
          "Main menu ready.\nSend the chart image now to analyze in English!",
          message.chat.id,
          message.message_id,
          reply_markup=markup,
      )
    except Exception:
      bot.send_message(
          message.chat.id,
          "Main menu ready.\nSend the chart image now to analyze in English!",
          reply_markup=markup,
      )


def show_account_info(message, user_id):
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


# أمر التفعيل اليدوي للأدمن: /activate <user_id>
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
