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

# 1. إعداد نظام التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. جلب المتغيرات البيئية من Render
TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN") 
    or os.environ.get("TELEGRAM_TOKEN") 
    or ""
).strip()

WEBHOOK_URL = (
    os.environ.get("WEBHOOK_URL") 
    or ""
).strip().rstrip("/")

PORT = int(os.environ.get("PORT", "10000"))

GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY") 
    or os.environ.get("GEMINI_API") 
    or ""
).strip()

# 3. تهيئة FastAPI والتطبيقات
app = FastAPI()

if not TOKEN:
    logger.error("❌ المتغير TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN مفقود!")
    ptb_app = None
else:
    ptb_app = Application.builder().token(TOKEN).build()

# --- 4. دوال التعامل مع الأوامر ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name if (update.message and update.message.from_user) else "المستخدم"
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
                    res_data = response.json()
                    return res_data['candidates'][0]['content']['parts'][0]['text']
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
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الصورة: {str(e)}")

# ربط الأوامر بالـ ptb_app
if ptb_app:
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    ptb_app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    ptb_app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

# --- 5. مسارات الـ Webhook و Render Health Check ---

@app.api_route("/", methods=["GET", "HEAD"])
async def root_health_check():
    """مسار اختبار الصحة لتجاوز فحص Render وتجنب خطأ 405"""
    return {"status": "ok", "message": "TradeGuard AI Server is running"}

@app.post(f"/{TOKEN}" if TOKEN else "/webhook")
async def telegram_webhook(request: Request):
    """استقبال التحديثات المباشرة وترحيلها للبوت"""
    if not ptb_app:
        return Response(status_code=500, content="Bot app not initialized")
    
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        return Response(status_code=500)
    
    return Response(status_code=200)

@app.on_event("startup")
async def on_startup():
    """تنشيط المحرك وتمرير الـ Webhook لتليجرام عند بدء التشغيل"""
    if ptb_app:
        logger.info("⚡ Initializing and starting PTB Application...")
        await ptb_app.initialize()
        await ptb_app.start()
        
        if WEBHOOK_URL and TOKEN:
            full_webhook_url = f"{WEBHOOK_URL}/{TOKEN}"
            logger.info(f"🔗 Setting Telegram Webhook to: {full_webhook_url}")
            success = await ptb_app.bot.set_webhook(url=full_webhook_url, drop_pending_updates=True)
            logger.info(f"✅ Webhook set status: {success}")

@app.on_event("shutdown")
async def on_shutdown():
    """إغلاق محرك تليجرام عند توقف السيرفر"""
    if ptb_app:
        logger.info("🛑 Stopping PTB Application...")
        await ptb_app.stop()
        await ptb_app.shutdown()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
