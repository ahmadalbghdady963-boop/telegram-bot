import os
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# 1. إعداد نظام تسجيل الأخطاء (Logging) الاحترافي
# هذا سيجعل أي خطأ يظهر بوضوح في سجلات Render بدلاً من الفشل الصامت
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. استدعاء المتغيرات البيئية
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # مثال: https://telegram-bot-pqy3.onrender.com
PORT = int(os.environ.get("PORT", "10000"))

# 3. دوال التعامل مع الأوامر (Handlers)
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر /start"""
    user_name = update.message.from_user.first_name
    welcome_text = (
        f"مرحباً بك {user_name} في TradeGuard AI! 🤖📈\n\n"
        f"أنا هنا لمساعدتك في التحليل الفني.\n"
        f"قم بإرسال صورة الشارت (Chart) وسأقوم بتحليلها فوراً."
    )
    await update.message.reply_text(welcome_text)

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر حسابي"""
    await update.message.reply_text("👤 تفاصيل حسابك:\nالاشتراك: مجاني\nالحالة: نشط")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الرد على أمر الاشتراك"""
    await update.message.reply_text("💎 خطط الاشتراك ستتوفر قريباً!")

async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الصور المرسلة للتحليل"""
    try:
        # إرسال رسالة للمستخدم لطمأنته أن العملية بدأت
        processing_msg = await update.message.reply_text("جاري تحليل الشارت عبر الذكاء الاصطناعي... ⏳")
        
        # جلب الصورة (نأخذ أعلى دقة متوفرة)
        photo_file = await update.message.photo[-1].get_file()
        
        # --- هنا تضع كود الربط الخاص بك مع Gemini API أو Dify ---
        # مثال (يجب استبداله بالكود الفعلي الخاص بك):
        # image_bytes = await photo_file.download_as_bytearray()
        # ai_response = call_dify_or_gemini_api(image_bytes)
        # ---------------------------------------------------------
        
        # محاكاة لعملية التحليل (للتجربة)
        await asyncio.sleep(2) 
        ai_response = "✅ تم تحليل الشارت بنجاح.\n\nالسعر الحالي يلامس منطقة دعم هامة (مثال تجريبي)."
        
        # تعديل رسالة "الانتظار" بالنتيجة النهائية
        await processing_msg.edit_text(ai_response)

    except Exception as e:
        # تسجيل الخطأ الفعلي في Render لمعرفة السبب الحقيقي لفشل Dify/Gemini
        logger.error(f"Error analyzing chart: {e}", exc_info=True)
        await update.message.reply_text("❌ عذراً، حدث خطأ أثناء تحليل الصورة. يرجى التأكد من وضوح الشارت والمحاولة مجدداً.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """التقاط أي خطأ عام في البوت لمنعه من التوقف"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text("⚠️ حدث خطأ داخلي في الخادم. تم تسجيل الخطأ للمراجعة.")

# 4. الدالة الرئيسية لتشغيل البوت بنظام Webhook
def main():
    if not TOKEN or not WEBHOOK_URL:
        logger.error("❌ المتغيرات البيئية TELEGRAM_TOKEN أو WEBHOOK_URL مفقودة!")
        return

    # بناء التطبيق
    app = Application.builder().token(TOKEN).build()

    # ربط الأوامر بالدوال
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    
    # ربط الصور بدالة التحليل
    app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))

    # معالج الأخطاء الشامل
    app.add_error_handler(error_handler)

    logger.info("🚀 جاري بدء تشغيل البوت عبر Webhook...")
    
    # التشغيل باستخدام Webhook المتوافق مع Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
        drop_pending_updates=True # لتجاهل الأوامر القديمة المتراكمة التي سببت التعليق
    )

if __name__ == '__main__':
    main()
