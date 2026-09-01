import os
import logging
import base64
import asyncio
import httpx
from fastapi import FastAPI, Request, Response
import uvicorn
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# --- 1. الإعدادات والتهيئة ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# جلب المتغيرات
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# تهيئة تطبيق FastAPI وخادم Telegram
app = FastAPI()
ptb_app = Application.builder().token(TOKEN).build()

# --- 2. دوال معالجة أوامر تليجرام ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name if update.message.from_user else "المستخدم"
    welcome_text = (
        f"مرحباً بك {user_name} في TradeGuard AI! 🤖📈\n\n"
        f"أنا هنا لمساعدتك في التحليل الفني المالي.\n"
        f"قم بإرسال صورة الشارت (Chart) وسأقوم بتحليلها فوراً!"
    )
    await update.message.reply_text(welcome_text)

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 **تفاصيل حسابك**:\nالاشتراك: مجاني (حساب نشط ⚡️)\nالحد اليومي: غير محدود")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 **خطط الاشتراك**:\nأنت حالياً تستخدم الخطة المجانية. الخطط المتقدمة ستتوفر قريباً!")

async def analyze_image_with_gemini(base64_image: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ خطأ: مفتاح GEMINI_API_KEY غير متوفر في متغيرات البيئة على Render."

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

    models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        last_error = ""
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    return response.json()['candidates'][0]['content']['parts'][0]['text']
                else:
                    last_error = f"رمز ({response.status_code})"
            except Exception as e:
                last_error = str(e)

    return f"❌ فشل الاتصال بخدمة التحليل الفني. التفاصيل: {last_error}"

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
        logger.error(f"Error analyzing chart: {e}", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ أثناء معالجة الصورة.")

# --- 3. تسجيل الأوامر في التطبيق ---
ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
ptb_app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
ptb_app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

# --- 4. إعدادات FastAPI للـ Webhook ---

@app.post(f"/{TOKEN}")
async def telegram_webhook(request: Request):
    """استقبال التحديثات من تليجرام عبر المسار المؤمن بالتوكن"""
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        
        # التأكد من تهيئة وتشغيل تطبيق تليجرام
        if not ptb_app._initialized:
            await ptb_app.initialize()
            await ptb_app.start()

        await ptb_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
    
    return Response(status_code=200)

@app.get("/")
def health_check():
    """مسار صحة الخادم للتأكد من عمله على Render"""
    return {"status": "TradeGuard AI Bot is Running!"}

@app.on_event("startup")
async def on_startup():
    """عند بدء تشغيل الخادم، قم بتسجيل الـ Webhook مع تليجرام"""
    if TOKEN and WEBHOOK_URL:
        webhook_path = f"{WEBHOOK_URL}/{TOKEN}"
        await ptb_app.bot.set_webhook(url=webhook_path, drop_pending_updates=True)
        logger.info(f"✅ Webhook is set to: {webhook_path}")
    else:
        logger.error("❌ TOKEN or WEBHOOK_URL is missing!")

@app.on_event("shutdown")
async def on_shutdown():
    """عند إيقاف الخادم"""
    if ptb_app._initialized:
        await ptb_app.stop()
        await ptb_app.shutdown()

# --- 5. نقطة الدخول الرئيسية ---
if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN is missing!")
    else:
        # تشغيل خادم Uvicorn الذي سيحتضن FastAPI و Telegram معاً
        logger.info(f"🚀 Starting Uvicorn server on port {PORT}...")
        uvicorn.run(app, host="0.0.0.0", port=PORT)
