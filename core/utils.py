from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import core.settings as settings

async def check_forced_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Checks if the user has joined the forced channel.
    Returns True if joined, False if not.
    Sends a message if not joined.
    """
    channel = await settings.get_setting("forced_channel", "")
    if not channel or channel.strip() == "":
        return True
    
    # Prepend @ if missing
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = f"@{channel}"
        
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ['left', 'kicked']:
            return await _send_join_req(update, channel)
        return True
    except Exception as e:
        # If bot is not in the channel or user hasn't started bot properly,
        # fail open or soft fail. Let's log it and fail closed for security.
        # But if the channel is wrong, it will block everyone. So we assume False but text admin later.
        return await _send_join_req(update, channel)

async def _send_join_req(update: Update, channel):
    text = f"❌ **کاربر گرامی**\nجهت حمایت از ما و استفاده از ربات، لطفا ابتدا در کانال زیر عضو شوید:\n\n{channel}\n\nپس از عضویت، روی دکمه زیر کلیک کنید."
    url = f"https://t.me/{channel.replace('@', '')}"
    keys = [
        [InlineKeyboardButton("عضویت در کانال", url=url)],
        [InlineKeyboardButton("✅ عضو شدم", callback_data="start_menu")]
    ]
    markup = InlineKeyboardMarkup(keys)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        except:
            await update.callback_query.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    return False
