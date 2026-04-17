from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters
from database.models import AsyncSessionLocal, User
from sqlalchemy.future import select
import logging
from html import escape

logger = logging.getLogger(__name__)

WAIT_BROADCAST_MSG = 80

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    text = "📢 <b>سیستم ارسال پیام همگانی</b>\n\nلطفاً پیام خود را (متن، عکس، ویدیو و ...) بفرستید تا برای همه کاربران ارسال شود.\n\n"
    from handlers.admin import CANCEL_BTN
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
    return WAIT_BROADCAST_MSG

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User))).scalars().all()

    count = 0
    fail = 0
    status_msg = await update.message.reply_text(f"⏳ در حال ارسال به {len(users)} کاربر...")

    for u in users:
        try:
            # Use copy_message to preserve formatting and media
            await context.bot.copy_message(
                chat_id=u.telegram_id,
                from_chat_id=msg.chat_id,
                message_id=msg.message_id
            )
            count += 1
        except Exception as e:
            fail += 1
            logger.error(f"Failed to send broadcast to {u.telegram_id}: {e}")

    await status_msg.edit_text(f"✅ ارسال به پایان رسید.\n\nتعداد موفق: {count}\nتعداد ناموفق: {fail}")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    from handlers.admin import admin_panel
    await admin_panel(update, context)
    return ConversationHandler.END

def get_broadcast_conv():
    from handlers.admin import CANCEL_BTN
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^admin_broadcast$")],
        states={
            WAIT_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, send_broadcast)]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_broadcast, pattern="^admin_cancel$"),
            CommandHandler("cancel", cancel_broadcast)
        ]
    )
