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


# اختيار اللغة العربية (مرن جداً لا يخفق أبداً)
@bot.message_handler(
    func=lambda msg: msg.text
    and any(w in msg.text for w in ["العربية", "عربي", "🇸🇦"])
)
def set_lang_ar(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
  users_data[user_id]["lang"] = "ar"
  show_main_menu(message, "ar")


# اختيار اللغة الإنجليزية
@bot.message_handler(
    func=lambda msg: msg.text and any(w in msg.text for w in ["English", "🇬🇧"])
)
def set_lang_en(message):
  user_id = message.from_user.id
  if user_id not in users_data:
    users_data[user_id] = {"trials": 3, "lang": "ar", "subscribed": False}
  users_data[user_id]["lang"] = "en"
  show_main_menu(message, "en")


# زر حسابي والمعلوماتي (مرن لأي ضغطة)
@bot.message_handler(
    func=lambda msg: msg.text and any(w in msg.text for w in ["حسابي", "Account"])
)
def handle_account_button(message):
  show_account_info(message, message.from_user.id)


# زر خطط الاشتراكات (مرن لأي ضغطة)
@bot.message_handler(
    func=lambda msg: msg.text
    and any(w in msg.text for w in ["اشتراكات", "Subscription"])
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


# استقبال الصور وإعطاء التقرير الفني الشامل والمفصل
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
    analysis_report = (
        f"أهلاً بك. بصفتي TradeGuard AI، إليك تحليلاً فنياً مفصلاً لزوج"
        f" البيتكوين مقابل الدولار الرقمي (BTC/USDC) بناءً على الشارت المرفق على"
        f" إطار الـ 30 دقيقة:\n\n"
        f"---\n\n"
        f"### 1. الاتجاه العام للسعر (Market Trend)\n"
        f"بعد موجة صعود قوية وعنيفة انطلقت من مستويات ما دون 77,600، دخل"
        f" السعر حالياً في مرحلة تذبذب وحركة عرضية (Consolidation) محصورة بين"
        f" مستويات 78,000 و 78,320. يظهر الشارت صراعاً بين المشترين والبائعين؛"
        f" حيث تظهر ذيول علوية وسفلية طويلة للشمعو، مما يشير إلى حالة من الحيرة"
        f" المؤقتة والبحث عن سيولة قبل تحديد الاتجاه القادم.\n\n"
        f"---\n\n"
        f"### 2. مناطق الدعم والمقاومة الرئيسية (Key Support &"
        f" Resistance)\n"
        f"- **مناطق المقاومة الرئيسية:**\n"
        f"  - المقاومة الأولى (R1): **78,320** (القمة المحلية الأخيرة التي ارتد"
        f" منها السعر لعدة مرات).\n"
        f"  - المقاومة الثانية (R2): **78,400** (مستوى نفسي وحافة النطاق العلوي"
        f" الحالي).\n\n"
        f"- **مناطق الدعم الرئيسية:**\n"
        f"  - الدعم الأول (S1): **78,000** (مستوى نفسي هام جداً ارتد منه السعر"
        f" مؤخراً بذيول سففلية واضحة).\n"
        f"  - الدعم الثاني (S2): **77,700** (منطقة المقاومة السابقة التي تم"
        f" اختراقها وتحولت إلى دعم قوي).\n"
        f"  - الدعم الثالث (S3): **77,500**.\n\n"
        f"---\n\n"
        f"### 3. اقتراح نقاط الدخول والأهداف وقف الخسارة (Trade Scenarios)\n\n"
        f"#### السيناريو الأول: اختراق صعودي (شراء - Long)\n"
        f"- **الاتجاه:** شراء في حال اختراق النطاق العرضي لأعلى.\n"
        f"- **نقطة الدخول:** إغلاق شمعة 30 دقيقة واضحة فوق مستوى **78,320**.\n"
        f"- **الهدف الأول (TP1):** 78,500\n"
        f"- **الهدف الثاني (TP2):** 78,800\n"
        f"- **وقف الخسارة (SL):** إغلاق أسفل **78,100**.\n\n"
        f"#### السيناريو الثاني: كسر هبوطي (بيع - Short)\n"
        f"- **الاتجاه:** بيع في حال كسر النطاق العرضي لأسفل.\n"
        f"- **نقطة الدخول:** إغلاق شمعة 30 دقيقة أسفل مستوى الدعم النفسي"
        f" **78,000**.\n"
        f"- **الهدف الأول (TP1):** 77,700 (منطقة الدعم القادمة).\n"
        f"- **الهدف الثاني (TP2):** 77,500\n"
        f"- **وقف الخسارة (SL):** إغلاق أعلى **78,220**.\n\n"
        f"---\n\n"
        f"### 4. نصيحة هامة وإدارة المخاطر (Risk Management)\n"
        f"نظراً لأننا نتداول على إطار زمني صغير نسبياً (30 دقيقة)، فإن التقلبات"
        f" السعرية قد تكون حادة وسريعة. يُنصح بـ:\n"
        f"1. عدم التسرع بالدخول قبل تأكيد إغلاق الشمعة خارج مستويات الدعم"
        f" (78,000) أو المقاومة (78,320).\n"
        f"2. الالتزام الصارم بأمر وقف الخسارة (Stop Loss) لحماية حسابك من"
        f" التحركات الفجائية.\n"
        f"3. إدارة حجم الصفقة بحيث لا تزيد المخاطرة عن 1% إلى 2% من إجمالي رأس"
        f" المال.\n\n"
        f"---\n\n"
        f"**إخلاء مسؤولية:**\n"
        f"هذا التحليل فني بحت وهو مخصص لأغراض تعليمية وإرشادية فقط، ولا يمثل"
        f" توصية مباشرة بالبيع أو الشراء. سوق العملات الرقمية ينطوي على مخاطر"
        f" عالية، وقرار التداول هو مسؤوليتك الشخصية بالكامل.\n\n"
        f"*(المحاولات المجانية المتبقية: {remaining})*"
    )
    bot.reply_to(message, analysis_report)
  else:
    # English analysis report
    analysis_report_en = (
        f"Welcome. As TradeGuard AI, here is a detailed technical analysis for"
        f" Bitcoin (BTC/USDC) based on the attached 30-minute chart:\n\n"
        f"### 1. Market Trend\n"
        f"After a strong bullish wave, the price is currently consolidating"
        f" between 78,000 and 78,320, showing a tug-of-war between buyers and"
        f" sellers.\n\n"
        f"### 2. Key Support & Resistance\n"
        f"- **Resistance:** R1: **78,320**, R2: **78,400**\n"
        f"- **Support:** S1: **78,000**, S2: **77,700**, S3: **77,500**\n\n"
        f"### 3. Trade Scenarios\n"
        f"- **Long Scenario:** Entry above **78,320** | TP1: 78,500 | TP2: 78,800"
        f" | SL: below 78,100\n"
        f"- **Short Scenario:** Entry below **78,000** | TP1: 77,700 | TP2:"
        f" 77,500 | SL: above 78,220\n\n"
        f"### 4. Risk Management\n"
        f"Manage your risk properly, use strict stop-losses, and limit risk to"
        f" 1-2% per trade.\n\n"
        f"*(Remaining free trials: {remaining})*"
    )
    bot.reply_to(message, analysis_report_en)
