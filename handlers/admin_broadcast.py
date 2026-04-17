from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from database.models import AsyncSessionLocal, User
from sqlalchemy.future import select
from handlers.admin import CANCEL_BTN, admin_panel, check_admin
import asyncio
import logging

logger = logging.getLogger(__name__)

WAIT_BROADCAST_MSG = 80
CONFIRM_BROADCAST = 81

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not await check_admin(update.effective_user.id):
        return ConversationHandler.END
        
    await query.edit_message_text(
        "📢 **بخش ارسال پیام همگانی**\n\nلطفاً پیام خود را (متن، عکس، فیلم و ...) ارسال کنید.\nهر چیزی که بفرستید دقیقاً برای کاربران کپی خواهد شد.",
        reply_markup=InlineKeyboardMarkup(CANCEL_BTN),
        parse_mode="Markdown"
    )
    return WAIT_BROADCAST_MSG

async def get_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Save the message to copy later
    context.user_data['broadcast_msg'] = update.message
    
    # Show preview
    await update.message.reply_text("👁 **پیش‌نمایش پیام بالا است.**\n\nآیا از ارسال این پیام برای تمام کاربران اطمینان دارید؟", 
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("✅ بله، ارسال شود", callback_data="confirm_broadcast_start")],
                                        [InlineKeyboardButton("❌ خیر، لغو شود", callback_data="admin_cancel")]
                                    ]),
                                    reply_to_message_id=update.message.message_id)
    return CONFIRM_BROADCAST

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    msg_to_copy = context.user_data.get('broadcast_msg')
    if not msg_to_copy:
        await query.edit_message_text("❌ خطا: پیام یافت نشد.")
        return ConversationHandler.END
        
    await query.edit_message_text("⏳ **در حال ارسال پیام...**\nلطفاً صبور باشید. پس از اتمام گزارش نهایی داده خواهد شد.")
    
    success = 0
    fail = 0
    
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User))).scalars().all()
        total = len(users)
        
    for user in users:
        try:
            # We use copy_message to preserve headers, captions, and media
            await context.bot.copy_message(
                chat_id=user.telegram_id,
                from_chat_id=msg_to_copy.chat_id,
                message_id=msg_to_copy.message_id
            )
            success += 1
        except Exception as e:
            logger.error(f"Failed broadcast to {user.telegram_id}: {e}")
            fail += 1
        
        # Tiny delay to avoid rate limits
        await asyncio.sleep(0.05) if success % 20 == 0 else None

    report = f"📊 **گزارش نهایی ارسال همگانی**\n\n"
    report += f"✅ ارسال موفق: {success}\n"
    report += f"❌ ارسال ناموفق: {fail}\n"
    report += f"👥 کل کاربران: {total}"
    
    await query.message.reply_text(report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")]]))
    return ConversationHandler.END

def get_broadcast_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^admin_broadcast$")],
        states={
            WAIT_BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(execute_broadcast, pattern="^confirm_broadcast_start$")]
        },
        fallbacks=[CallbackQueryHandler(admin_panel, pattern="^admin_cancel$")]
    )
