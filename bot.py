import os
import logging
import base64
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

# 1. إعداد سجلات النظام
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. قراءة متغيرات البيئة
TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN") or "").strip()
WEBHOOK_URL = (os.environ.get("WEBHOOK_URL") or "").strip().rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API") or "").strip()

# تهيئة تطبيق تليجرام
ptb_app = Application.builder().token(TOKEN).build() if TOKEN else None

# 3. إدارة دورة حياة التطبيق (Lifespan الحديثة لـ FastAPI)
@asynccontextmanager
async def lifespan(app: FastAPI):
    if ptb_app:
        logger.info("⚡ بدء تشغيل محرك تليجرام TradeGuard AI...")
        await ptb_app.initialize()
        await ptb_app.start()

        if WEBHOOK_URL and TOKEN:
            full_webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
            logger.info(f"🔗 ربط Webhook على الرابط: {full_webhook_url}")
            await ptb_app.bot.set_webhook(url=full_webhook_url, drop_pending_updates=True)
        else:
            logger.warning("⚠️ يرجى التأكد من ضبط WEBHOOK_URL و TELEGRAM_BOT_TOKEN في Render!")

    yield

    if ptb_app:
        logger.info("🛑 إيقاف محرك تليجرام...")
        await ptb_app.stop()
        await ptb_app.shutdown()

# إنشاء تطبيق FastAPI
app = FastAPI(lifespan=lifespan)

# 4. دوال التعامل مع أوامر البوت
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["👤 حسابي", "💎 الاشتراك"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    user_name = update.effective_user.first_name if update.effective_user else "المستخدم"
    welcome_text = (
        f"مرحباً بك {user_name} في **TradeGuard AI**! 🤖📈\n\n"
        f"أنا نظام التحليل الفني الذكي المخصص لفحص الشموع اليابانية والأسواق المالية.\n\n"
        f"📸 **كيفية الاستخدام**:\n"
        f"أرسل صورة الرسم البياني (الشارت) مباشرة وسيقوم الذكاء الاصطناعي بتحليل الاتجاه والدعم والمقاومة فوراً!"
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account_info = (
        "👤 **تفاصيل حسابك**:\n"
        "━━━━━━━\n"
        "• الحالة: نشط ⚡️\n"
        "• نوع الاشتراك: الخطة المجانية\n"
        "• رصيد التحليلات: غير محدود ♾️"
    )
    await update.message.reply_text(account_info, parse_mode="Markdown")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sub_info = (
        "💎 **خطط الاشتراك**:\n"
        "━━━━━━━\n"
        "أنت حالياً تمتع بالخطة المجانية الكاملة مقدمة من TradeGuard AI 🚀"
    )
    await update.message.reply_text(sub_info, parse_mode="Markdown")

async def analyze_image_with_gemini(base64_image: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ خطأ: لم يتم ضبط مفتاح GEMINI_API_KEY في متغيرات البيئة."

    prompt = """أنت محلل أسواق مالية صارم وخبير للشموع اليابانية (TradeGuard AI).
القاعدة الأولى: افحص الصورة أولاً. إذا لم تكن الصورة تحتوي على رسم بياني (شارت) لأسعار وشموع يابانية مالية، توقف فوراً وأجب فقط بالرسالة التالية:
"⚠️ عذراً، هذه الصورة لا تحتوي على رسم بياني للشمعات اليابانية (Candlestick Chart)."

القاعدة الثانية: إذا كانت الصورة شارت صحيح، استخرج التوصية بالشكل التالي:

📊 **تحليل TradeGuard AI**
━━━━━━━━━━━━━━━━━━
• **الاتجاه العام**: [صاعد / هابط / عرضي]
• **مستوى المقاومة الأقوى**: [السعر]
• **مستوى الدعم الأقوى**: [السعر]
• **النصيحة والتوصية**: [جملة واحدة فقط توضح القرار المناسب]
━━━━━━━━━━━━━━━━━━"""

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}}
            ]
        }]
    }

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro"
    ]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        last_error = ""
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    res_json = response.json()
                    return res_json['candidates'][0]['content']['parts'][0]['text']
                else:
                    last_error = f"رمز الاستجابة ({response.status_code})"
            except Exception as e:
                last_error = str(e)

    return f"❌ تعذر الاتصال بمحرك التحليل. التفاصيل: {last_error}"

async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        processing_msg = await update.message.reply_text("⏳ جاري فحص وتحليل الشارت بواسطة الذكاء الاصطناعي...")
        
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        ai_response = await analyze_image_with_gemini(base64_image)
        
        try:
            await processing_msg.edit_text(ai_response, parse_mode="Markdown")
        except Exception:
            await processing_msg.edit_text(ai_response)
    except Exception as e:
        logger.error(f"Error handling image: {e}", exc_info=True)
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الصورة.")

# تسجيل المعالجات
if ptb_app:
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

# 5. نقاط نهاية FastAPI
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
