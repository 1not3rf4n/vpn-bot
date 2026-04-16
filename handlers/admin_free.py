from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from database.models import AsyncSessionLocal, FreeConfig
from sqlalchemy.future import select
from handlers.admin import CANCEL_BTN, admin_panel

WAIT_F_TITLE = 59
WAIT_F_COUNTRY = 60
WAIT_F_DESC = 61
WAIT_F_DATA = 62

async def admin_free_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()))).scalars().all()
        
    text = "🎁 **مدیریت کانفیگ‌های رایگان**\nلیست تمام کانفیگ‌ها:\n\n"
    if not configs:
        text += "هیچ کانفیگی ثبت نشده است."
    for c in configs:
        title = c.title or c.country or "بدون نام"
        text += f"🔹 `{title}` - [حذف: /del_free_{c.id}]\n"
        
    keys = [
        [InlineKeyboardButton("➕ افزودن کانفیگ رایگان جدید", callback_data="add_free_config")],
        [InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys))

async def start_add_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("یک **نام** برای این کانفیگ انتخاب کنید (مثلاً: سرور VIP آلمان):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="Markdown")
    return WAIT_F_TITLE

async def save_free_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fc_title'] = update.message.text
    await update.message.reply_text("نام کشور/لوکیشن:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_COUNTRY

async def save_free_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fc_country'] = update.message.text
    await update.message.reply_text("توضیحات کوتاه یا پیام برای کاربر:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DESC

async def save_free_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_fc_desc'] = update.message.text
    await update.message.reply_text("لینک یا کد کانفیگ را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DATA

async def save_free_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.message.text
    title = context.user_data.get('temp_fc_title', 'بدون نام')
    country = context.user_data.get('temp_fc_country', 'نامشخص')
    desc = context.user_data.get('temp_fc_desc', '')
    
    import re
    from urllib.parse import quote
    
    is_v2ray = "vless://" in data.lower() or "vmess://" in data.lower() or "trojan://" in data.lower()
    
    if not is_v2ray:
        lines = data.strip().split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            if not line: continue
            if '://' in line:
                try:
                    parts = line.split('://', 1)
                    protocol = parts[0]
                    rest = quote(parts[1], safe='/:@?&=#%+')
                    cleaned.append(f"{protocol}://{rest}")
                except: cleaned.append(line)
            else:
                cleaned.append(line)
        data = '\n'.join(cleaned)
    
    async with AsyncSessionLocal() as session:
        c = FreeConfig(title=title, country=country, config_data=data, description=desc, config_text=data)
        session.add(c)
        await session.commit()
        
    await update.message.reply_text(f"✅ کانفیگ رایگان '{title}' با موفقیت افزوده شد.")
    await admin_panel(update, context)
    return ConversationHandler.END

async def del_free_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import check_admin
    if not await check_admin(update.effective_user.id):
        return

    try:
        text = update.message.text
        fid = int(text.split("_")[-1])
        
        async with AsyncSessionLocal() as session:
            c = (await session.execute(select(FreeConfig).where(FreeConfig.id == fid))).scalars().first()
            if c:
                await session.delete(c)
                await session.commit()
                await update.message.reply_text(f"🗑 کانفیگ شماره {fid} با موفقیت حذف شد.")
            else:
                await update.message.reply_text("❌ این کانفیگ یافت نشد.")
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

def get_admin_free_conv():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_free, pattern="^add_free_config$")],
        states={
            WAIT_F_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_title)],
            WAIT_F_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_country)],
            WAIT_F_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_desc)],
            WAIT_F_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_data)]
        },
        fallbacks=[CallbackQueryHandler(admin_free_list, pattern="^admin_cancel$")]
    )

def get_admin_free_routers():
    return [
        CallbackQueryHandler(admin_free_list, pattern="^admin_free_configs$"),
        MessageHandler(filters.Regex(r'^/del_free_\d+'), del_free_command)
    ]
