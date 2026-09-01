import os
import logging
import base64
import html
from contextlib import asynccontextmanager
import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import google.generativeai as genai

# 1. إعداد نظام التسجيل (Logging)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. تنقية متغيرات البيئة من Render
TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or ""
).strip().strip('"').strip("'")

RAW_WEBHOOK_URL = (
    os.environ.get("WEBHOOK_URL") or ""
).strip().strip('"').strip("'").rstrip("/")

WEBHOOK_URL = ""
if RAW_WEBHOOK_URL:
    if not RAW_WEBHOOK_URL.startswith("http://") and not RAW_WEBHOOK_URL.startswith("https://"):
        WEBHOOK_URL = f"https://{RAW_WEBHOOK_URL}"
    else:
        WEBHOOK_URL = RAW_WEBHOOK_URL

PORT = int(os.environ.get("PORT", "10000"))
GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API") or ""
).strip().strip('"').strip("'")

# تهيئة Gemini SDK
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# تهيئة تطبيق تليجرام
ptb_app = Application.builder().token(TOKEN).build() if TOKEN else None

# 3. إدارة دورة حياة FastAPI (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    if ptb_app:
        logger.info("⚡ بدء تشغيل محرك TradeGuard AI...")
        await ptb_app.initialize()
        await ptb_app.start()

        if WEBHOOK_URL and TOKEN:
            full_webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
            logger.info(f"🔗 ربط Webhook على الرابط: {full_webhook_url}")
            try:
                success = await ptb_app.bot.set_webhook(url=full_webhook_url, drop_pending_updates=True)
                logger.info(f"✅ تم ضبط Webhook بنجاح: {success}")
            except Exception as e:
                logger.error(f"⚠️ فشل ضبط Webhook: {e}")
        else:
            logger.warning("⚠️ يرجى ضبط WEBHOOK_URL و TELEGRAM_BOT_TOKEN في Render!")

    yield

    if ptb_app:
        logger.info("🛑 إيقاف محرك تليجرام...")
        await ptb_app.stop()
        await ptb_app.shutdown()

app = FastAPI(lifespan=lifespan)

# 4. دوال التعامل مع أوامر البوت
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["👤 حسابي", "💎 الاشتراك"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    user_name = html.escape(update.effective_user.first_name if update.effective_user else "المستخدم")
    welcome_text = (
        f"مرحباً بك {user_name} في <b>TradeGuard AI</b>! 🤖📈\n\n"
        f"أنا نظام التحليل الفني الذكي المخصص لفحص الشموع اليابانية والأسواق المالية.\n\n"
        f"📸 <b>كيفية الاستخدام</b>:\n"
        f"أرسل صورة الرسم البياني (الشارت) مباشرة وسيقوم الذكاء الاصطناعي بتحليل الاتجاه والدعم والمقاومة فوراً!"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_info = (
        "👤 <b>تفاصيل حسابك</b>:\n"
        "━━━━━━━\n"
        "• الحالة: نشط ⚡️\n"
        "• نوع الاشتراك: الخطة المجانية\n"
        "• رصيد التحليلات: غير محدود ♾️"
    )
    await update.message.reply_text(account_info, parse_mode="HTML")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub_info = (
        "💎 <b>خطط الاشتراك</b>:\n"
        "━━━━━━━\n"
        "أنت حالياً تتمتع بالخطة المجانية الكاملة مقدمة من TradeGuard AI 🚀"
    )
    await update.message.reply_text(sub_info, parse_mode="HTML")

async def analyze_image_with_gemini(image_bytes: bytes) -> str:
    if not GEMINI_API_KEY:
        return "❌ خطأ: لم يتم ضبط مفتاح GEMINI_API_KEY في متغيرات البيئة."

    # توجيه Gemini بالإبقاء على الأقواس [] في التنسيق النهائي
    prompt = """أنت محلل أسواق مالية صارم وخبير للشموع اليابانية (TradeGuard AI).
القاعدة الأولى: افحص الصورة أولاً. إذا لم تكن الصورة تحتوي على رسم بياني (شارت) لأسعار وشموع يابانية مالية، توقف فوراً وأجب فقط بالرسالة التالية:
"⚠️ عذراً، هذه الصورة لا تحتوي على رسم بياني للشمعات اليابانية (Candlestick Chart)."

القاعدة الثانية: إذا كانت الصورة شارت صحيح، استخرج التوصية واستخدم الأقواس [] المحددة حول النتائج بالشكل التالي تماماً:

📊 <b>تحليل TradeGuard AI</b>
━━━━━━━━━━━━━━━━━━
• <b>الاتجاه العام</b>: [ضع الاتجاه هنا: صاعد / هابط / عرضي]
• <b>مستوى المقاومة الأقوى</b>: [ضع سعر المقاومة هنا]
• <b>مستوى الدعم الأقوى</b>: [ضع سعر الدعم هنا]
• <b>النصيحة والتوصية</b>: [ضع النصيحة في جملة واحدة هنا]
━━━━━━━━━━━━━━━━━━"""

    models_to_try = ['gemini-1.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro']
    image_part = {"mime_type": "image/jpeg", "data": image_bytes}

    # محاولة بواسطة SDK الرسمي
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, image_part])
            if response and response.text:
                return response.text
        except Exception as e:
            logger.warning(f"SDK model {model_name} failed: {e}")

    # محاولة احتياطية بواسطة HTTP REST Direct Call
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
            ]
        }]
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    rest_endpoints = [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        last_err = ""
        for url in rest_endpoints:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
                else:
                    last_err = f"رمز ({resp.status_code})"
            except Exception as ex:
                last_err = str(ex)

    return f"❌ تعذر الاتصال بمحرك التحليل. التفاصيل: {last_err}"

async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        processing_msg = await update.message.reply_text("⏳ جاري فحص وتحليل الشارت بواسطة الذكاء الاصطناعي...")
        
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        
        ai_response = await analyze_image_with_gemini(bytes(image_bytes))
        
        try:
            await processing_msg.edit_text(ai_response, parse_mode="HTML")
        except Exception:
            await processing_msg.edit_text(ai_response)
    except Exception as e:
        logger.error(f"Error handling image: {e}", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ أثناء معالجة الصورة.")

# 5. تسجيل الأوامر والمعالجات
if ptb_app:
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

# 6. مسارات Health Check و Webhook
@app.api_route("/", methods=["GET", "HEAD"])
async def root_health_check():
    return {"status": "ok", "service": "TradeGuard AI"}

@app.post(f"/{TOKEN}" if TOKEN else "/webhook")
async def telegram_webhook(request: Request):
    if not ptb_app:
        return Response(status_code=500, content="Bot app not initialized")
    
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    
    return Response(status_code=200)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
