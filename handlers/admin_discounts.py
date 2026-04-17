from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, DiscountCode
from handlers.admin import CANCEL_BTN, admin_panel

WAIT_COUPON_CODE, WAIT_COUPON_PERCENT, WAIT_COUPON_LIMIT = range(70, 73)

async def admin_discounts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()

    async with AsyncSessionLocal() as session:
        res = await session.execute(select(DiscountCode))
        codes = res.scalars().all()

    from html import escape
    keys = []
    text = "🎁 <b>مدیریت کدهای تخفیف</b>\nلیست کدهای موجود:\n"
    if not codes:
        text += "(هیچ کدی ثبت نشده است)\n"
    else:
        for c in codes:
            text += f"- <code>{escape(c.code)}</code>: {c.percent}% (استفاده: {c.used_count}/{c.max_uses})\n"
            keys.append([InlineKeyboardButton(f"🗑 حذف کد {c.code}", callback_data=f"del_discount_{c.id}")])

    keys.append([InlineKeyboardButton("➕ افزودن کد جدید", callback_data="add_discount_code")])
    keys.append([InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")])
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

# ----- Add discount -----
async def start_add_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لطفا کد تخفیف را با حروف لاتین وارد کنید (مثلا BOMB20):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_COUPON_CODE

async def save_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tmp_discount_code'] = update.message.text
    await update.message.reply_text("درصد تخفیف چقدر است؟ (مثلا 20 برای 20٪):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_COUPON_PERCENT

async def save_discount_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
         await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
         return WAIT_COUPON_PERCENT
    
    context.user_data['tmp_discount_percent'] = int(update.message.text)
    await update.message.reply_text("این کد حداکثر چند بار قابل استفاده است؟ (عدد وارد کنید):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_COUPON_LIMIT

async def save_discount_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
         await update.message.reply_text("فقط عدد مجاز است:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
         return WAIT_COUPON_LIMIT
         
    code = context.user_data['tmp_discount_code']
    percent = context.user_data['tmp_discount_percent']
    max_uses = int(update.message.text)
    
    async with AsyncSessionLocal() as session:
        dc = DiscountCode(code=code, percent=percent, max_uses=max_uses)
        session.add(dc)
        await session.commit()
        
    await update.message.reply_text("✅ با موفقیت اضافه شد.")
    await admin_discounts_menu(update, context)
    return ConversationHandler.END

async def cancel_disc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await admin_panel(update, context)
    return ConversationHandler.END

async def delete_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(DiscountCode).where(DiscountCode.id == uid))
        dc = res.scalars().first()
        if dc:
            await session.delete(dc)
            await session.commit()
            
    await query.answer("کد با موفقیت حذف شد.", show_alert=True)
    await admin_discounts_menu(update, context)

def get_discount_conv_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_add_discount, pattern="^add_discount_code$")],
        states={
            WAIT_COUPON_CODE: [MessageHandler(filters.TEXT, save_discount_code)],
            WAIT_COUPON_PERCENT: [MessageHandler(filters.TEXT, save_discount_percent)],
            WAIT_COUPON_LIMIT: [MessageHandler(filters.TEXT, save_discount_limit)]
        },
        fallbacks=[CallbackQueryHandler(cancel_disc, pattern="^admin_cancel$")]
    )

def get_discount_routers():
    return [
        CallbackQueryHandler(admin_discounts_menu, pattern="^admin_discounts_menu$"),
        CallbackQueryHandler(delete_discount_code, pattern="^del_discount_")
    ]
