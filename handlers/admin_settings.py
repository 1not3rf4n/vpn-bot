from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from core.settings import get_setting, set_setting
import core.config as config
from database.models import AsyncSessionLocal, User
from sqlalchemy.future import select

(EDIT_START_MSG, EDIT_CHANNEL, EDIT_REF, EDIT_UI_COLOR, EDIT_ORDER_TXT, WAIT_XUI_URL, WAIT_XUI_USER, WAIT_XUI_PASS) = range(10, 18)

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="settings_cancel")]]

async def check_admin(user_id):
    if user_id in config.ADMIN_IDS:
        return True
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalars().first()
        return user and user.is_admin

async def settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()

    text = "⚙️ <b>تنظیمات پیشرفته ربات</b>\nجهت تغییر هر یک از موارد زیر روی آن کلیک کنید:"
    keyboard = [
        [InlineKeyboardButton("📝 پیام استارت", callback_data="set_start_msg")],
        [InlineKeyboardButton("📢 قفل کانال اجباری", callback_data="set_channel")],
        [InlineKeyboardButton("🎁 درصد پورسانت دعوت (رفرال)", callback_data="set_referral_percent")],
        [InlineKeyboardButton("💱 نرخ پایه تتر / دلار", callback_data="set_usd_rate")],
        [InlineKeyboardButton("✅ پیام کاستوم تایید پرداخت", callback_data="set_order_msg")],
        [InlineKeyboardButton("🔘 مدیریت کلیدهای سراسری", callback_data="admin_global_toggles")],
        [InlineKeyboardButton("🔌 اتصال پنل (سرور V2ray)", callback_data="settings_xui_panel")],
        [InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_panel")]
    ]
    if query: 
        try: await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except: pass
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def req_start_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("start_message", "")
    await query.message.reply_text(f"پیام فعلی:\n{cur}\n\nلطفاً پیام شروع جدید را ارسال کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return EDIT_START_MSG

async def save_start_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_msg = update.message.text
    await set_setting("start_message", new_msg)
    await update.message.reply_text("✅ پیام استارت با موفقیت تغییر کرد.")
    await settings_panel(update, context)
    return ConversationHandler.END
    
async def req_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("forced_channel", "تنظیم نشده")
    await query.message.reply_text(f"کانال قفل فعلی: {cur}\n\nلطفاً آیدی کانال را بدون @ برای قفل اجباری وارد کنید (برای خاموش کردن off بفرستید):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return EDIT_CHANNEL

async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_ch = update.message.text
    if new_ch.lower() == "off": new_ch = ""
    await set_setting("forced_channel", new_ch)
    await update.message.reply_text("✅ کانال قفل با موفقیت ثبت شد.")
    await settings_panel(update, context)
    return ConversationHandler.END

async def req_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("referral_percent", "10")
    await query.message.reply_text(f"درصد پورسانت فعلی: {cur}٪\n\nلطفاً درصد جدید را بدون علامت ٪ وارد کنید (مثلا 20):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return EDIT_REF

async def save_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("لطفا فقط عدد وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return EDIT_REF
    await set_setting("referral_percent", val)
    await update.message.reply_text("✅ درصد پاداش با موفقیت ثبت شد.")
    await settings_panel(update, context)
    return ConversationHandler.END

async def req_usd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("usd_exchange_rate", "65000")
    await query.message.reply_text(f"نرخ تتر فعلی: {cur}\n\nلطفاً نرخ جدید را وارد کنید (مثلا 65000):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return EDIT_UI_COLOR

async def save_usd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if not val.isdigit():
        await update.message.reply_text("لطفا فقط عدد وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return EDIT_UI_COLOR
    await set_setting("usd_exchange_rate", val)
    await update.message.reply_text("✅ نرخ روزانه دلار تایید شد.")
    await settings_panel(update, context)
    return ConversationHandler.END

async def req_order_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cur = await get_setting("order_confirm_msg", "✅ سفارش شما تایید شد.\n\nکد اشتراک: {sub_code}\nمحصول: {product_name}")
    await query.message.reply_text(f"متن فعلی تایید سفارش:\n\n{cur}\n\nلطفاً متن جدید را ارسال کنید. (مجاز به استفاده از متغیرهای {{sub_code}} و {{product_name}} هستید):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return EDIT_ORDER_TXT

async def save_order_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    await set_setting("order_confirm_msg", val)
    await update.message.reply_text("✅ متن تایید پرداخت با موفقیت تغییر کرد.")
    await settings_panel(update, context)
    return ConversationHandler.END

async def cancel_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await settings_panel(update, context)
    return ConversationHandler.END

def get_settings_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(req_start_msg, pattern="^set_start_msg$"),
            CallbackQueryHandler(req_channel, pattern="^set_channel$"),
            CallbackQueryHandler(req_referral, pattern="^set_referral_percent$"),
            CallbackQueryHandler(req_usd_rate, pattern="^set_usd_rate$"),
            CallbackQueryHandler(req_order_msg, pattern="^set_order_msg$"),
            CallbackQueryHandler(req_xui_panel, pattern="^settings_xui_panel$")
        ],
        states={
            EDIT_START_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_start_msg)],
            EDIT_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel)],
            EDIT_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_referral)],
            EDIT_UI_COLOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_usd_rate)],
            EDIT_ORDER_TXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_order_msg)],
            WAIT_XUI_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_xui_url)],
            WAIT_XUI_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_xui_user)],
            WAIT_XUI_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_xui_pass)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_settings),
            CommandHandler("cancel", cancel_settings),
            CallbackQueryHandler(cancel_settings, pattern="^settings_cancel$")
        ]
    )

async def req_xui_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    from database.models import XUIPanel
    async with AsyncSessionLocal() as session:
        panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
        
    from html import escape
    text = "🔌 <b>مدیریت سرور X-UI</b>\n\n"
    if panel_db:
        text += f"وضعیت فعلی: <b>متصل / ثبت شده</b>\nسایت: <code>{escape(panel_db.url)}</code>\nیوزر نیم قبلی: <code>{escape(panel_db.username)}</code>\n\n"
        
    text += "برای ثبت یا آپدیت پنل، لطفاً آدرس کامل پنل را بفرستید:\nمثلاً <code>http://1.1.1.1:2082</code>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
    return WAIT_XUI_URL

async def save_xui_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_xui_url'] = update.message.text.strip()
    await update.message.reply_text("شناسه کاربری (Username) پنل را ارسال کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_XUI_USER

async def save_xui_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_xui_user'] = update.message.text.strip()
    await update.message.reply_text("رمز عبور (Password) پنل را ارسال کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_XUI_PASS

async def save_xui_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    passw = update.message.text.strip()
    user = context.user_data['temp_xui_user']
    url = context.user_data['temp_xui_url']
    
    from database.models import XUIPanel
    async with AsyncSessionLocal() as session:
        panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
        if not panel_db:
            panel_db = XUIPanel(url=url, username=user, password=passw)
            session.add(panel_db)
        else:
            panel_db.url = url
            panel_db.username = user
            panel_db.password = passw
        await session.commit()
    
    await update.message.reply_text("✅ اطلاعات اتصال پنل با موفقیت ثبت/آپدیت شد.\nمحصولاتی که در وضعیت V2RAY ساخته شده باشند اکنون مستقیما از این پنل اکانت صادر می‌کنند.")
    await settings_panel(update, context)
    return ConversationHandler.END

async def admin_global_toggles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    shop = await get_setting("menu_shop", "on")
    wallet = await get_setting("menu_wallet", "on")
    free = await get_setting("menu_free_config", "on")
    
    keys = [
        [InlineKeyboardButton(f"فروشگاه: {'روشن✅' if shop == 'on' else 'خاموش❌'}", callback_data="toggle_menu_shop")],
        [InlineKeyboardButton(f"کیف پول: {'روشن✅' if wallet == 'on' else 'خاموش❌'}", callback_data="toggle_menu_wallet")],
        [InlineKeyboardButton(f"کانفیگ رایگان: {'روشن✅' if free == 'on' else 'خاموش❌'}", callback_data="toggle_menu_free")],
        [InlineKeyboardButton("🔙 بازگشت به مدیریت", callback_data="admin_settings_menu")]
    ]
    await query.edit_message_text("مدیریت کلیدهای منوی اصلی کاربر:", reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def handle_toggle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target = query.data.replace("toggle_menu_", "menu_")
    cur = await get_setting(target, "on")
    new_v = "off" if cur == "on" else "on"
    await set_setting(target, new_v)
    await admin_global_toggles(update, context)

def get_settings_routers():
    return [
        CallbackQueryHandler(settings_panel, pattern="^admin_settings_menu$"),
        CallbackQueryHandler(admin_global_toggles, pattern="^admin_global_toggles$"),
        CallbackQueryHandler(handle_toggle_menu, pattern="^toggle_menu_")
    ]
