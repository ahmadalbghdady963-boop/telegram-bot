from datetime import datetime, timedelta
import os
import threading
from flask import Flask, request, abort
import requests
from telebot import TeleBot, types

# === المتغيرات الأساسية (تُجلب من إعدادات ريندر) ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
FIREBASE_URL = os.getenv("FIREBASE_URL") # تأكد في ريندر أن الرابط يبدأ بـ https:// وينتهي بـ .com بدون شرطات مائلة إضافية
PORT = int(os.getenv("PORT", 10000))

# === إعدادات البوت الخاصة بك ===
ADMIN_ID = "8655689754"
RENDER_APP_URL = "https://telegram-bot-pqy3.onrender.com"
WALLET_TON = "UQClWC3pSNcpxdYrRstljCDLKYcTY760blJnIElyieAFSdQK"
ADMIN_USERNAME = "@TradeGuard_Admin"

bot = TeleBot(TOKEN)
app = Flask(__name__)
USER_CACHE = {}

# === مسارات الويب هوك (Webhook) ===
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

# === دوال قواعد البيانات (Firebase) ===
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

# === أوامر الإدارة ===
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

# === أوامر المستخدمين والتصميم الأصلي ===
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

    remaining_ar = "غير محدود (مشترك) ♾️" if is_subscribed else f"{max(0, 3 - trials)} من 3"
    remaining_en = "Unlimited (Subscribed) ♾️" if is_subscribed else f"{max(0, 3 - trials)} of 3"

    # إعادة الأزرار الشفافة الأنيقة
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

# === معالجة الصور والتواصل السليم مع Dify ===
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

  # رسالة الدفع إذا انتهت المحاولات
  if not is_subscribed and trials >= 3:
    if lang == "ar":
      sub_msg = (
          "⚠️ **انتهت محاولاتك المجانية!**\n\nللاشتراك والحصول على تحليلات غير محدودة:\n"
          "🥉 **باقة 10 أيام (15$)**\n🏆 **الباقة الشهرية (38$)**\n\n"
          f"💳 **الدفع عبر شبكة TON:**\n`{WALLET_TON}`\n\n"
          "✅ **للتفعيل:**\n"
          f"قم بنسخ هذا الرقم (الآيدي الخاص بك): `{user_id}`\n"
          f"وأرسله مع صورة إيصال الدفع إلى الإدارة هنا: {ADMIN_USERNAME}"
      )
    else:
      sub_msg = (
          "⚠️ **Your free trials have ended!**\n\nTo subscribe for unlimited analysis:\n"
          "🥉 **10-Day Plan ($15)**\n🏆 **Monthly Plan ($38)**\n\n"
          f"💳 **Pay via TON network:**\n`{WALLET_TON}`\n\n"
          "✅ **To Activate:**\n"
          f"Copy this ID: `{user_id}`\n"
          f"And send it with the payment receipt to the admin here: {ADMIN_USERNAME}"
      )
    bot.reply_to(message, sub_msg, parse_mode="Markdown")
    return

  msg = bot.reply_to(message, "⏳ جاري فحص وتحليل الصورة..." if lang == "ar" else "⏳ Inspecting and analyzing image...")

  try:
    # 1. تحميل الصورة من تيليجرام
    file_id = message.photo[-1].file_id
    file_info_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
    file_res = requests.get(file_info_url, timeout=10).json()

    if not file_res.get("ok"):
      raise Exception("Failed to fetch file info from Telegram")

    file_path = file_res["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    
    img_res = requests.get(download_url, timeout=30)
    downloaded_file = img_res.content

    # 2. رفع الصورة إلى Dify
    upload_url = "https://api.dify.ai/v1/files/upload"
    headers_upload = {"Authorization": f"Bearer {DIFY_API_KEY}"}
    files_data = {"file": ("chart.jpg", downloaded_file, "image/jpeg")}
    data_upload = {"user": user_id}

    upload_response = requests.post(upload_url, headers=headers_upload, files=files_data, data=data_upload, timeout=30)
    
    if upload_response.status_code not in [200, 201]:
      raise Exception(f"Dify Upload Error: {upload_response.text}")

    upload_result = upload_response.json()
    dify_file_id = upload_result.get("id")

    # 3. إرسال الطلب للتحليل (الفحص الذكي)
    chat_url = "https://api.dify.ai/v1/chat-messages"
    
    query_text = (
        "قم بفحص هذه الصورة بدقة. إذا كانت الصورة لا تحتوي على شارت تداول، أو رسوم بيانية مالية، أو منصة تداول (مثل صورة شخصية، إيصال دفع، لقطة شاشة عادية، أو أي شيء آخر)، "
        "فلا تقم بتحليلها واكتب بالحرف الواحد فقط هذه الجملة: 'NOT_CHART'.\n"
        "أما إذا كانت شارت تداول صحيح، فقم بتحليلها فنياً بشكل مفصل ومقسم فقرات، وفي النهاية أضف تحذير المخاطرة بأن التداول مسؤولية شخصية."
    )

    if lang == "en":
       query_text = (
        "Inspect this image carefully. If the image DOES NOT contain a trading chart, financial graph, or trading platform (e.g., a selfie, payment receipt, normal screenshot), "
        "do NOT analyze it and output exactly this phrase: 'NOT_CHART'.\n"
        "If it is a valid trading chart, provide a detailed technical analysis in ENGLISH ONLY, and append a risk warning at the end."
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
      raise Exception(f"Dify Chat Error: {response.status_code}")

    result = response.json()
    answer = result.get("answer", "")

    # 4. التعامل مع الرد
    if "NOT_CHART" in answer:
      warning_text = (
          "⚠️ **هذه ليست صورة شارت تداول!**\n"
          "الرجاء إرسال رسوم بيانية أو شارت تداول صحيح للتحليل.\n\n"
          f"💡 *ملاحظة:* إذا كنت تريد إرسال إيصال الدفع، فالرجاء إرساله مباشرة إلى الإدارة هنا: {ADMIN_USERNAME}"
      ) if lang == "ar" else (
          "⚠️ **This is not a trading chart!**\n"
          "Please send a valid trading chart or graph for analysis.\n\n"
          f"💡 *Note:* If you are sending a payment receipt, please send it directly to the admin here: {ADMIN_USERNAME}"
      )
      bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=warning_text, parse_mode="Markdown")
      return

    # إرسال التحليل النهائي
    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=answer)

    # خصم محاولة فقط لو كانت الصورة شارت حقيقي وتم تحليلها بنجاح
    if not is_subscribed:
      new_trials = trials + 1
      update_user_data(user_id, {"trials": new_trials})
      remaining = max(0, 3 - new_trials)
      rem_msg = f"ℹ️ لديك {remaining} محاولات مجانية متبقية." if lang == "ar" else f"ℹ️ You have {remaining} free trials remaining."
      bot.send_message(message.chat.id, rem_msg)

  except Exception as e:
    error_msg = f"❌ حدث خطأ في النظام. الرجاء المحاولة لاحقاً.\n(Debug: {str(e)})" if lang == "ar" else f"❌ System error. Please try again later.\n(Debug: {str(e)})"
    bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=error_msg)

# === إعداد الويب هوك ===
def setup_webhook():
  try:
    bot.remove_webhook()
    bot.set_webhook(url=f"{RENDER_APP_URL}/{TOKEN}")
  except Exception as e:
    print(f"Failed to set Webhook: {e}")

setup_webhook()

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=PORT)
