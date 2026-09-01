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

# 1. إعداد نظام تسجيل الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. قراءة المتغيرات البيئية
TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-bot-pqy3.onrender.com")
PORT = int(os.environ.get("PORT", "10000"))

# 3. دوال التعامل مع الأوامر
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.first_name
    welcome_text = (
        f"مرحباً بك {user_name} في TradeGuard AI! 🤖📈\n\n"
        f"أنا هنا لمساعدتك في التحليل الفني.\n"
        f"قم بإرسال صورة الشارت (Chart) وسأقوم بتحليلها فوراً."
    )
    await update.message.reply_text(welcome_text)

async def account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 تفاصيل حسابك:\nالاشتراك: مجاني\nالحالة: نشط")

async def subscription_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💎 خطط الاشتراك ستتوفر قريباً!")

async def handle_chart_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        processing_msg = await update.message.reply_text("جاري تحليل الشارت عبر الذكاء الاصطناعي... ⏳")
        await asyncio.sleep(2) 
        ai_response = "✅ تم تحليل الشارت بنجاح.\n\nالسعر الحالي يلامس منطقة دعم هامة (مثال تجريبي)."
        await processing_msg.edit_text(ai_response)
    except Exception as e:
        logger.error(f"Error analyzing chart: {e}", exc_info=True)
        await update.message.reply_text("❌ عذراً، حدث خطأ أثناء تحليل الصورة. يرجى المحاولة مجدداً.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

# 4. التشغيل الرئيسي مع معالجة Event Loop
def main():
    if not TOKEN:
        logger.error("❌ خطأ حرج: متغير TELEGRAM_TOKEN أو BOT_TOKEN غير موجود في إعدادات Render!")
        return

    # إصلاح مشكلة حلقة الأحداث في بايثون الحديثة على Render
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.Regex("^👤 حسابي$"), account_command))
    app.add_handler(MessageHandler(filters.Regex("^💎 الاشتراك$"), subscription_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_chart_image))
    app.add_error_handler(error_handler)

    logger.info("🚀 جاري بدء تشغيل البوت عبر Webhook...")
    
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
