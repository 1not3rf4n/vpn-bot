from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Category, Product, Order
import core.config as config

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="admin_cancel")]]

async def check_admin(user_id):
    if user_id in config.ADMIN_IDS:
        return True
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user = result.scalars().first()
        return user and user.is_admin

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = update.effective_user.id
    else:
        user_id = update.message.from_user.id

    if not await check_admin(user_id):
        text = "شما دسترسی ادمین ندارید."
        if query: await query.edit_message_text(text)
        else: await update.message.reply_text(text)
        return

    async with AsyncSessionLocal() as session:
        from database.models import Ticket, Receipt
        pending_receipts = len((await session.execute(select(Receipt).where(Receipt.status == "PENDING"))).scalars().all())
        open_tickets = len((await session.execute(select(Ticket).where(Ticket.status == "OPEN"))).scalars().all())
        total_users = len((await session.execute(select(User))).scalars().all())

    text = f"👑 **پنل مدیریت پیشرفته**\n➖➖➖➖➖➖\n👥 تعداد کل کاربران: `{total_users}`\n\nلطفا بخش مورد نظر خود را انتخاب کنید:"
    keyboard = [
        [InlineKeyboardButton("📊 آمار و گزارشات", callback_data="admin_stats"), InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="admin_search_user")],
        [InlineKeyboardButton("📋 ۱۰ سفارش اخیر", callback_data="admin_recent_orders"), InlineKeyboardButton("🔎 جستجوی سفارش", callback_data="admin_search_order")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="admin_broadcast")],
        [InlineKeyboardButton(f"🧾 صندوق فیش‌ها ({pending_receipts})", callback_data="admin_receipts"), InlineKeyboardButton(f"🎫 پشتیبانی تیکت‌ها ({open_tickets})", callback_data="admin_tickets")],
        [InlineKeyboardButton("🗂 مدیریت فروشگاه (دسته‌بندی و محصول)", callback_data="admin_shop")],
        [InlineKeyboardButton("💰 مالی و درگاه‌ها", callback_data="admin_finance_menu"), InlineKeyboardButton("🎁 مدیریت تخفیف‌ها", callback_data="admin_discounts_menu")],
        [InlineKeyboardButton("🎁 مدیریت کانفیگ رایگان", callback_data="admin_free_configs")],
        [InlineKeyboardButton("⚙️ تنظیمات عمومی", callback_data="admin_settings_menu")],
        [InlineKeyboardButton("🔙 بازگشت به ربات", callback_data="start_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    async with AsyncSessionLocal() as session:
        from database.models import Service, Ticket, Receipt
        import sqlalchemy as sa
        
        total_users = len((await session.execute(select(User))).scalars().all())
        total_orders = len((await session.execute(select(Order))).scalars().all())
        
        # Calculate revenue (sum of PAID orders or receipts)
        ord_sum = (await session.execute(sa.select(sa.func.sum(Order.amount)).where(Order.status == 'PAID'))).scalar() or 0
        rec_sum = (await session.execute(sa.select(sa.func.sum(Receipt.amount)).where(Receipt.status == 'PAID'))).scalar() or 0
        wallet_sum = (await session.execute(sa.select(sa.func.sum(User.wallet_balance)))).scalar() or 0
        
        active_svcs = len((await session.execute(select(Service).where(Service.status == 'ACTIVE'))).scalars().all())
        open_tickets = len((await session.execute(select(Ticket).where(Ticket.status == 'OPEN'))).scalars().all())
        
    text = f"""📊 **گزارش جامع ربات**

👥 تعداد کل اعضا: {total_users} نفر
🛒 کل سفارشات ثبتی: {total_orders}

💰 **آمار مالی:**
مجموع فروش (سفارشات موفق): {ord_sum:,.0f} تومان
مجموع واریزی (فیش‌های تاییدشده): {rec_sum:,.0f} تومان
موجودی نزد کاربران (کیف پول‌ها): {wallet_sum:,.0f} تومان

🌐 **سرویس‌ها و پشتیبانی:**
سرویس‌های در حال استفاده: {active_svcs}
تیکت‌های باز (منتظر پاسخ): {open_tickets}"""

    keys = [
        [InlineKeyboardButton("📋 ۱۰ سفارش اخیر", callback_data="admin_recent_orders")],
        CANCEL_BTN[0]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")

async def admin_recent_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        from sqlalchemy.orm import selectinload
        orders = (await session.execute(select(Order).options(selectinload(Order.user)).order_by(Order.id.desc()).limit(10))).scalars().all()
        
    from html import escape
    text = "📋 ۱۰ سفارش اخیر ثبت شده در سیستم\n\n"
    if not orders:
        text += "هیچ سفارشی یافت نشد."
    else:
        for o in orders:
            status_fa = {"PAID": "✅ موفق", "PENDING": "⏳ در انتظار", "CANCELED": "❌ لغو شده", "REJECTED": "🔴 رد شده"}.get(o.status, o.status)
            method_fa = {"ZARINPAL": "درگاه", "WALLET": "کیف‌پول", "CARD": "کارت", "CRYPTO": "کریپتو"}.get(o.payment_method, o.payment_method)
            user_obj = o.user
            if user_obj:
                u_name = escape(user_obj.fullname or "نامشخص")
                if user_obj.username:
                    u_user = escape(user_obj.username)
                    uname = f"{u_name} (@{u_user})"
                else:
                    uname = u_name
            else:
                uname = f"ID:{o.user_id}"
            text += f"🔹 سفارش #{o.id} | کاربر: {uname}\n"
            text += f"مبلغ: {o.amount:,.0f} تومان | روش: {method_fa}\n"
            text += f"وضعیت: {status_fa}\n➖➖➖➖➖\n"
            
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")

async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await admin_panel(update, context)

async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "admin_panel" or query.data == "admin_cancel":
        await admin_panel(update, context)
    elif query.data == "admin_stats":
        await admin_stats(update, context)
    elif query.data == "admin_recent_orders":
        await admin_recent_orders(update, context)
