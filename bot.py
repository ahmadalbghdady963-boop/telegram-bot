import os
import logging
import base64
import asyncio
import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# 1. إعداد نظام تسجيل الأخطاء (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. استدعاء المتغيرات البيئية من Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", "10000"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# 3. الأوامر الأساسية للبوت
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر /start"""
    user_name = update.message.from_user.first_name if update.message.from_user else "المستخدم"
    welcome_text = (
        f"مرحباً بك {user_name} في TradeGuard AI! 🤖📈\n\n"
        f"أنا هنا لمساعدتك في التحليل الفني المالي.\n"
        f"قم بإرسال صورة الشارت (Chart) وسأقوم بتحليلها فوراً!"
    )
    await update.message.reply_text(welcome_text)

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر حسابي"""
    await update.message.reply_text("👤 **تفاصيل حسابك**:\nالاشتراك: مجاني (حساب نشط ⚡️)\nالحد اليومي: غير محدود")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر الاشتراك"""
    await update.message.reply_text("💎 **خطط الاشتراك**:\nأنت حالياً تستخدم الخطة المجانية. الخطط المتقدمة ستتوفر قريباً!")

# 4. دالة الاتصال بنموذج Gemini API المباشر
async def analyze_image_with_gemini(base64_image: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ خطأ: مفتاح GEMINI_API_KEY غير متوفر في متغيرات البيئة على Render."

    prompt = """أنت محلل أسواق مالية صارم وخبير للشموع اليابانية (TradeGuard AI).
القاعدة الأولى الحازمة: افحص الصورة أولاً. إذا لم تكن الصورة تحتوي على رسم بياني (شارت) لأسعار وشموع يابانية مالية، توقف فوراً وأجب فقط بالرسالة التالية دون أي إضافات:
"⚠️ عذراً، هذه الصورة لا تحتوي على رسم بياني للشمعات اليابانية (Candlestick Chart)."

القاعدة الثانية: إذا كانت الصورة تحتوي على رسم بياني صحيح للشموع اليابانية، قم بتحليل الشارت واستخراج البيانات الفنية فوراً بالصيغة الهيكلية التالية المحددة:

📊 **تحليل TradeGuard AI**
━━━━━━━━━━━━━━━━━━
• **الاتجاه العام**: [صاعد / هابط / عرضي]
• **مستوى المقاومة الأقوى**: [السعر]
• **مستوى الدعم الأقوى**: [السعر]
• **النصيحة والتوصية**: [جملة واحدة فقط توضح القرار المناسب بناء على السلوك السعري]
━━━━━━━━━━━━━━━━━━"""

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
        }]
    }

    # قائمة النماذج المتاحة للتجربة التلقائية لضمان عدم حدوث خطأ 404
    models_to_try = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        last_error = ""
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            try:
                response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    res_json = response.json()
                    text = res_json['candidates'][0]['content']['parts'][0]['text']
                    return text
                else:
                    last_error = f"رمز الاستجابة ({response.status_code}) من النموذج {model}"
                    logger.warning(f"Model {model} failed: {response.text}")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Exception for {model}: {e}")

    return f"❌ فشل الاتصال بخدمة التحليل الفني.\nالتفاصيل: {last_error}"

# 5. معالجة الصور واستدعاء التحليل
async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور المرسلة للتحليل"""
    try:
        processing_msg = await update.message.reply_text("⏳ جاري فحص وتحليل الشارت بواسطة الذكاء الاصطناعي...")
        
        # تنزيل الصورة بأعلى دقة
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # الاتصال بـ Gemini API
        ai_response = await analyze_image_with_gemini(base64_image)
        
        # تحديث الرسالة بالنتيجة النهائية
        try:
            await processing_msg.edit_text(ai_response, parse_mode="Markdown")
        except Exception:
            await processing_msg.edit_text(ai_response)

    except Exception as e:
        logger.error(f"Error analyzing chart: {e}", exc_info=True)
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الصورة: {str(e)}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """التقاط وإدارة الأخطاء العامة"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ حدث خطأ داخلي في الخادم. تم تسجيل الخطأ للمراجعة.")

# 6. التشغيل الرئيسي
def main():
    if not TOKEN or not WEBHOOK_URL:
        logger.error("❌ المتغيرات البيئية TELEGRAM_TOKEN أو WEBHOOK_URL مفقودة!")
        return

    app = Application.builder().token(TOKEN).build()

    # تسجيل الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

    app.add_error_handler(error_handler)

    logger.info("🚀 جاري بدء تشغيل البوت عبر Webhook...")
    
    # التعديل الجوهري: إضافة url_path=TOKEN لربط المسار بشكل صحيح ومنع خطأ 404
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
