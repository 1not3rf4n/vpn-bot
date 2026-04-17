from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from database.models import AsyncSessionLocal, FreeConfig
from sqlalchemy.future import select
from handlers.admin import CANCEL_BTN, admin_panel
from datetime import datetime, timedelta
from html import escape

WAIT_F_TITLE = 59
WAIT_F_COUNTRY = 60
WAIT_F_DESC = 61
WAIT_F_DATA = 62
WAIT_F_DURATION = 63
WAIT_EDIT_VALUE = 70

async def admin_free_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()))).scalars().all()
        
    text = "🎁 <b>مدیریت کانفیگ‌های رایگان</b>\nبرای مدیریت هر کانفیگ روی آن کلیک کنید:\n\n"
    if not configs:
        text += "هیچ کانفیگی ثبت نشده است."
    
    keys = []
    for c in configs:
        title = escape(c.title or c.country or "بدون نام")
        status = "✅"
        if c.expire_date and c.expire_date < datetime.utcnow():
            status = "❌ (منقضی)"
        keys.append([InlineKeyboardButton(f"{status} {title}", callback_data=f"adm_free_mg_{c.id}")])
        
    keys.append([InlineKeyboardButton("➕ افزودن کانفیگ رایگان جدید", callback_data="add_free_config")])
    keys.append([InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def admin_free_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fid = int(query.data.split("_")[3])
    
    async with AsyncSessionLocal() as session:
        c = (await session.execute(select(FreeConfig).where(FreeConfig.id == fid))).scalars().first()
        if not c:
            await query.edit_message_text("❌ یافت نشد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return
            
    text = f"⚙️ <b>مدیریت کانفیگ: {escape(c.title)}</b>\n\n"
    text += f"🌍 لوکیشن: {escape(c.country or 'نامشخص')}\n"
    text += f"📝 توضیحات: {escape(c.description or 'ندارد')}\n"
    exp_str = c.expire_date.strftime("%Y-%m-%d %H:%M") if c.expire_date else "دائمی"
    text += f"⏳ زمان انقضا: {exp_str}\n"
    
    keys = [
        [InlineKeyboardButton("✏️ نام", callback_data=f"adm_free_ed_title_{fid}"), InlineKeyboardButton("🌍 لوکیشن", callback_data=f"adm_free_ed_country_{fid}")],
        [InlineKeyboardButton("📝 توضیحات", callback_data=f"adm_free_ed_desc_{fid}"), InlineKeyboardButton("🔗 لینک", callback_data=f"adm_free_ed_data_{fid}")],
        [InlineKeyboardButton("⏳ تغییر زمان اعتبار", callback_data=f"adm_free_ed_dur_{fid}")],
        [InlineKeyboardButton("🗑 حذف این کانفیگ", callback_data=f"adm_free_del_{fid}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_free_configs")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def admin_free_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    fid = int(query.data.split("_")[3])
    
    async with AsyncSessionLocal() as session:
        c = (await session.execute(select(FreeConfig).where(FreeConfig.id == fid))).scalars().first()
        if c:
            await session.delete(c)
            await session.commit()
            await query.edit_message_text(f"✅ کانفیگ '{escape(c.title)}' با موفقیت حذف شد.", 
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_free_configs")]]),
                                         parse_mode="HTML")
        else:
            await query.edit_message_text("❌ یافت نشد.")

# --- Adding Flow ---
async def start_add_free(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("یک <b>نام</b> برای این کانفیگ انتخاب کنید (مثلاً: سرور VIP آلمان):", 
                                   reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
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
    await update.message.reply_text("مدت زمان اعتبار به روز (مثلاً 3. برای دائمی عدد 0 بفرستید):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DURATION

async def save_free_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("لطفا فقط عدد وارد کنید:")
        return WAIT_F_DURATION
    context.user_data['temp_fc_dur'] = int(val)
    await update.message.reply_text("لینک یا کد کانفیگ را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_F_DATA

async def save_free_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.message.text
    title = context.user_data.get('temp_fc_title', 'بدون نام')
    country = context.user_data.get('temp_fc_country', 'نامشخص')
    desc = context.user_data.get('temp_fc_desc', '')
    days = context.user_data.get('temp_fc_dur', 0)
    
    exp_date = None
    if days > 0:
        exp_date = datetime.utcnow() + timedelta(days=days)
    
    async with AsyncSessionLocal() as session:
        c = FreeConfig(title=title, country=country, config_data=data, description=desc, config_text=data, expire_date=exp_date)
        session.add(c)
        await session.commit()
        
    await update.message.reply_text(f"✅ کانفیگ رایگان '{escape(title)}' با موفقیت افزوده شد.", parse_mode="HTML")
    await admin_panel(update, context)
    return ConversationHandler.END

# --- Editing Flow ---
async def start_edit_free_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    field = parts[3]
    fid = int(parts[4])
    
    context.user_data['edit_fc_id'] = fid
    context.user_data['edit_fc_field'] = field
    
    field_fa = {"title": "نام", "country": "لوکیشن", "desc": "توضیحات", "data": "لینک", "dur": "مدت اعتبار (روز)"}.get(field, field)
    await query.edit_message_text(f"مقدار جدید را برای <b>{field_fa}</b> وارد کنید:", 
                                   reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
    return WAIT_EDIT_VALUE

async def save_edit_free_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    fid = context.user_data.get('edit_fc_id')
    field = context.user_data.get('edit_fc_field')
    
    async with AsyncSessionLocal() as session:
        c = (await session.execute(select(FreeConfig).where(FreeConfig.id == fid))).scalars().first()
        if not c:
            await update.message.reply_text("خطا: یافت نشد.")
            return ConversationHandler.END
            
        if field == "title": c.title = val
        elif field == "country": c.country = val
        elif field == "desc": c.description = val
        elif field == "data": 
            c.config_data = val
            c.config_text = val
        elif field == "dur":
            if not val.isdigit():
                await update.message.reply_text("فقط عدد وارد کنید:")
                return WAIT_EDIT_VALUE
            days = int(val)
            c.expire_date = (datetime.utcnow() + timedelta(days=days)) if days > 0 else None
            
        await session.commit()
        
    await update.message.reply_text("✅ با موفقیت بروزرسانی شد.")
    await admin_panel(update, context)
    return ConversationHandler.END

def get_admin_free_conv():
    from handlers.admin import cancel_admin
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_add_free, pattern="^add_free_config$"),
            CallbackQueryHandler(start_edit_free_field, pattern="^adm_free_ed_")
        ],
        states={
            WAIT_F_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_title)],
            WAIT_F_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_country)],
            WAIT_F_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_desc)],
            WAIT_F_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_duration)],
            WAIT_F_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_free_data)],
            WAIT_EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_edit_free_value)]
        },
        fallbacks=[CallbackQueryHandler(admin_free_list, pattern="^admin_cancel$")]
    )

def get_admin_free_routers():
    return [
        CallbackQueryHandler(admin_free_list, pattern="^admin_free_configs$"),
        CallbackQueryHandler(admin_free_manage_menu, pattern="^adm_free_mg_"),
        CallbackQueryHandler(admin_free_delete_confirm, pattern="^adm_free_del_")
    ]
