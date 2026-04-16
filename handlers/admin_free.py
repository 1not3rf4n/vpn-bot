from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from database.models import AsyncSessionLocal, FreeConfig
from sqlalchemy.future import select
from handlers.admin import CANCEL_BTN, admin_panel

WAIT_F_TYPE = 58
WAIT_F_COUNTRY = 59
WAIT_F_DESC = 60
WAIT_F_DATA = 61


async def admin_free_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    async with AsyncSessionLocal() as session:
        configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()).limit(10))).scalars().all()

    text = "🎁 **مدیریت کانفیگ‌های رایگان**\nلیست کانفیگ‌های اخیر:\n\n"
    for c in configs:
        text += f"🔹 `{c.country}` - {c.description[:15]}... [حذف: /del_free_{c.id}]\n"

    keys = [
        [InlineKeyboardButton("➕ افزودن کانفیگ رایگان جدید",
                              callback_data="add_free_config")],
        [InlineKeyboardButton("🔙 بازگشت به مدیریت",
                              callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys))


async def start_add_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keys = [
        [InlineKeyboardButton("🔑 V2RAY (vless/vmess)",
                              callback_data="free_type_v2ray")],
        [InlineKeyboardButton("🔗 لینک معمولی (سایر)",
                              callback_data="free_type_other")],
        CANCEL_BTN[0]
    ]
    await query.edit_message_text("نوع کانفیگ رایگان را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_F_TYPE


async def select_free_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "free_type_v2ray":
        context.user_data['temp_fc_type'] = "V2RAY"
    else:
        context.user_data['temp_fc_type'] = "OTHER"
    await query.edit_message_text("لطفاً نام کشور/لوکیشن را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_COUNTRY


async def save_free_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fc_country'] = update.message.text
    await update.message.reply_text("پیام یا توضیحات کوتاه:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DESC


async def save_free_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fc_desc'] = update.message.text
    fc_type = context.user_data.get('temp_fc_type', 'V2RAY')
    if fc_type == "V2RAY":
        await update.message.reply_text("لینک کانفیگ V2RAY را وارد کنید (vless:// یا vmess://):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    else:
        await update.message.reply_text("لینک‌ها را ارسال کنید (هر لینک در یک خط یا پشت هم):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DATA


async def save_free_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.message.text
    country = context.user_data.get('temp_fc_country', 'نامشخص')
    desc = context.user_data.get('temp_fc_desc', '')
    fc_type = context.user_data.get('temp_fc_type', 'V2RAY')

    if fc_type == "OTHER":
        # Extract and clean links
        import re
        from urllib.parse import quote
        lines = data.strip().split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # If it looks like a URL, encode non-ascii parts
            if '://' in line:
                # Split protocol and rest
                parts = line.split('://', 1)
                protocol = parts[0]
                rest = quote(parts[1], safe='/:@?&=#%+')
                cleaned.append(f"{protocol}://{rest}")
            else:
                cleaned.append(line)
        data = '\n'.join(cleaned)

    async with AsyncSessionLocal() as session:
        c = FreeConfig(country=country, config_data=data, description=desc)
        session.add(c)
        await session.commit()

    await update.message.reply_text("✅ کانفیگ رایگان افزوده شد.")
    await admin_panel(update, context)
    return ConversationHandler.END


async def del_free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fid = int(update.message.text.split("_")[2])
        async with AsyncSessionLocal() as session:
            c = (await session.execute(select(FreeConfig).where(FreeConfig.id == fid))).scalars().first()
            if c:
                await session.delete(c)
                await session.commit()
                await update.message.reply_text("🗑 کانفیگ حذف شد.")
    except:
        pass


def get_admin_free_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(
            start_add_free, pattern="^add_free_config$")],
        states={
            WAIT_F_TYPE: [CallbackQueryHandler(select_free_type, pattern="^free_type_")],
            WAIT_F_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_country)],
            WAIT_F_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_desc)],
            WAIT_F_DATA: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, save_free_data)]
        },
        fallbacks=[CallbackQueryHandler(
            admin_free_list, pattern="^admin_cancel$")]
    )


def get_admin_free_routers():
    return [
        CallbackQueryHandler(admin_free_list, pattern="^admin_free_configs$"),
        CommandHandler("del_free", del_free_command)
    ]
