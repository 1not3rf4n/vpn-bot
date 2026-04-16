from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from core.settings import get_setting, set_setting
from database.models import AsyncSessionLocal, CryptoNetwork
from sqlalchemy.future import select
from handlers.admin import CANCEL_BTN, admin_panel

(WAIT_CARD, WAIT_CRYP_NAME, WAIT_CRYP_ADDR) = range(60, 63)

async def admin_finance_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()

    card_stat = await get_setting("card_enabled", "on")
    crypto_stat = await get_setting("crypto_enabled", "off")
    zrn_stat = await get_setting("zarinpal_enabled", "off")

    st_card = "🟢 روشن" if card_stat=="on" else "🔴 خاموش"
    st_crypt = "🟢 روشن" if crypto_stat=="on" else "🔴 خاموش"
    st_zrn = "🟢 روشن" if zrn_stat=="on" else "🔴 خاموش"

    text = "💰 **تنظیمات مالی و درگاه‌ها**\nشما می‌توانید روش‌های پرداخت را فعال یا غیرفعال کنید:"
    keys = [
        [InlineKeyboardButton(f"💳 کارت بانکی ({st_card})", callback_data="tg_finance_card_enabled")],
        [InlineKeyboardButton("✍️ تغییر شماره کارت", callback_data="fin_set_card")],
        [InlineKeyboardButton(f"🪙 ارز دیجیتال ({st_crypt})", callback_data="tg_finance_crypto_enabled")],
        [InlineKeyboardButton("🔗 مدیریت آدرس‌های ولت (تتر، تن، شیبا و...)", callback_data="admin_crypto_menu")],
        [InlineKeyboardButton(f"🌐 درگاه مستقیم ({st_zrn})", callback_data="tg_finance_zarinpal_enabled")],
        CANCEL_BTN[0]
    ]
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")

async def toggle_finance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    key = query.data.replace("tg_finance_", "")
    cur = await get_setting(key, "off")
    await set_setting(key, "off" if cur=="on" else "on")
    await admin_finance_menu(update, context)

# Setters
async def ask_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("admin_card", "تنظیم نشده")
    await query.message.reply_text(f"شماره کارت فعلی:\n`{cur}`\n\nلطفا شماره کارت جدید را ارسال کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="Markdown")
    return WAIT_CARD

async def save_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_setting("admin_card", update.message.text)
    await update.message.reply_text("✅ با موفقیت ذخیره شد.")
    await admin_finance_menu(update, context)
    return ConversationHandler.END

async def admin_crypto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    
    async with AsyncSessionLocal() as session:
        nets = (await session.execute(select(CryptoNetwork))).scalars().all()
        
    text = "🪙 **مدیریت شبکه‌های ارز دیجیتال**\nولِت‌های فعال شما:\n\n"
    if not nets: text += "هیچ ولتی ثبت نشده است."
    else:
        for n in nets:
            text += f"🔹 {n.name} ({n.network})\nآدرس: `{n.address}`\n\n"
            
    keys = [
        [InlineKeyboardButton("➕ افزودن ولت جدید", callback_data="fin_add_crypto")],
        [InlineKeyboardButton("🗑 حذف همه ولت‌ها", callback_data="fin_delall_crypto")],
        CANCEL_BTN[0]
    ]
    if query: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")

async def req_crypto_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفا نام ارز یا شبکه را وارد کنید (مثلا: Tether TRC20):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_CRYP_NAME

async def save_crypto_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tmp_cryp_name'] = update.message.text
    await update.message.reply_text("آدرس ولت (Wallet Address) را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_CRYP_ADDR

async def save_crypto_addr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get('tmp_cryp_name', 'Crypto')
    addr = update.message.text
    async with AsyncSessionLocal() as session:
        session.add(CryptoNetwork(name=name, network=name, address=addr))
        await session.commit()
    await update.message.reply_text("✅ ولت با موفقیت اضافه شد.")
    await admin_crypto_menu(update, context)
    return ConversationHandler.END

async def delall_crypto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    async with AsyncSessionLocal() as session:
        nets = (await session.execute(select(CryptoNetwork))).scalars().all()
        for n in nets: await session.delete(n)
        await session.commit()
    await query.answer("همه ولت ها حذف شدند.", show_alert=True)
    await admin_crypto_menu(update, context)

async def cancel_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await admin_panel(update, context)
    return ConversationHandler.END

def get_finance_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_card, pattern="^fin_set_card$"),
            CallbackQueryHandler(req_crypto_name, pattern="^fin_add_crypto$")
        ],
        states={
            WAIT_CARD: [MessageHandler(filters.TEXT, save_card)],
            WAIT_CRYP_NAME: [MessageHandler(filters.TEXT, save_crypto_name)],
            WAIT_CRYP_ADDR: [MessageHandler(filters.TEXT, save_crypto_addr)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_fin),
            CallbackQueryHandler(cancel_fin, pattern="^admin_cancel$")
        ]
    )

def get_finance_routers():
    return [
        CallbackQueryHandler(admin_finance_menu, pattern="^admin_finance_menu$"),
        CallbackQueryHandler(admin_crypto_menu, pattern="^admin_crypto_menu$"),
        CallbackQueryHandler(delall_crypto, pattern="^fin_delall_crypto$"),
        CallbackQueryHandler(toggle_finance, pattern="^tg_finance_")
    ]
