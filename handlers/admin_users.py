from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
import logging
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Order, Receipt, Service, Ticket
from handlers.admin import CANCEL_BTN, admin_panel
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

WAIT_USER_ID = 63
WAIT_SVC_TEXT = 64
WAIT_SVC_DUR = 65
WAIT_ORDER_SEARCH = 66

async def admin_search_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🔍 <b>جستجوی کاربر</b>\n\nلطفاً آیدی عددی کاربر و یا یوزرنیم وی را (با @ یا بدون @) ارسال کنید:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
async def render_user_profile(user, message_obj, is_edit=False):
    async with AsyncSessionLocal() as session:
        orders = (await session.execute(select(Order).where(Order.user_id == user.id))).scalars().all()
        receipts = (await session.execute(select(Receipt).where(Receipt.user_id == user.id))).scalars().all()
        services = (await session.execute(select(Service).where(Service.user_id == user.id))).scalars().all()
        tickets = (await session.execute(select(Ticket).where(Ticket.user_id == user.id))).scalars().all()
        
    from html import escape
    u_name = escape(user.fullname or "نامشخص")
    u_user = escape(user.username) if user.username else "ندارد"
    
    text = f"👤 <b>اطلاعات کاربر</b>\n\n"
    text += f"آیدی عددی: <code>{user.telegram_id}</code>\n"
    text += f"نام: {u_name} (@{u_user})\n" if user.username else f"نام: {u_name}\n"
    text += f"لینک پروفایل: <a href='tg://user?id={user.telegram_id}'>کلیک کنید</a>\n"
    text += f"موجودی کیف پول: {user.wallet_balance:,.0f} تومان\n\n"
    
    paid_ord = [o for o in orders if o.status == 'PAID']
    paid_rec = [r for r in receipts if r.status == 'PAID']
    active_svcs = [s for s in services if s.status == 'ACTIVE']
    
    text += f"📦 سفارشات موفق / کل: {len(paid_ord)} / {len(orders)}\n"
    text += f"🧾 فیش‌های تاییدشده / کل: {len(paid_rec)} / {len(receipts)}\n"
    text += f"🌐 سرویس‌های فعال: {len(active_svcs)}\n"
    text += f"✉️ کل تیکت‌های کاربر: {len(tickets)}\n"
    
    keys = [
        [InlineKeyboardButton("➕ افزودن سرویس دستی", callback_data=f"adm_addsvc_{user.id}")],
        [InlineKeyboardButton("⚙️ مشاهده/مدیریت سرویس‌ها", callback_data=f"adm_mgsvc_{user.id}")],
        [InlineKeyboardButton("🔍 سابقه تیکت‌ها", callback_data=f"adm_tcks_{user.id}"), InlineKeyboardButton("👀 فیش‌ها", callback_data=f"adm_recs_{user.id}")],
        [InlineKeyboardButton("💬 ارسال پیام ربات", callback_data=f"adm_msg_{user.id}")],
        [InlineKeyboardButton("💰 صفر کردن کیف پول", callback_data=f"adm_resetwal_{user.id}")],
        CANCEL_BTN[0]
    ]
    
    if is_edit:
        await message_obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def admin_search_user_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    
    async with AsyncSessionLocal() as session:
        if val.isdigit():
            user = (await session.execute(select(User).where(User.telegram_id == int(val)))).scalars().first()
        else:
            from sqlalchemy import func
            uname = val.replace("@", "").lower()
            user = (await session.execute(select(User).where(func.lower(User.username) == uname))).scalars().first()
            
        if not user:
            await update.message.reply_text("❌ کاربری با این مشخصات در دیتابیس یافت نشد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return WAIT_USER_ID
            
    await render_user_profile(user, update.message, is_edit=False)
    return ConversationHandler.END

async def adm_search_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[3])
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        if user:
            await render_user_profile(user, query, is_edit=True)
    return ConversationHandler.END

# --- Manual Service Mgmt ---
async def start_add_manual_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    context.user_data['temp_svc_uid'] = u_id
    keys = [[InlineKeyboardButton("🔙 بازگشت به کاربر", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text("لطفاً متن کانفیگ یا لینک سرویس را برای کاربر بفرستید:", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_SVC_TEXT

async def save_manual_svc_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['temp_svc_text'] = update.message.text
    await update.message.reply_text("سرویس چند روزه است؟ (فقط عدد مثل 30):", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_SVC_DUR

async def save_manual_svc_dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if not val.isdigit():
        await update.message.reply_text("فقط عدد بفرستید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_SVC_DUR
        
    u_id = context.user_data.get('temp_svc_uid')
    svc_text = context.user_data.get('temp_svc_text', '')
    days = int(val)
    
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        svc = Service(
            user_id=u_id,
            config_link=svc_text,
            panel_username="سرویس دستی ادمین",
            status="ACTIVE",
            expire_date=datetime.utcnow() + timedelta(days=days)
        )
        session.add(svc)
        await session.commit()
    
    await update.message.reply_text("✅ سرویس با موفقیت قبت شد.")
    # Return to admin panel or something
    await admin_panel(update, context)
    return ConversationHandler.END

async def mgmt_user_svcs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        services = (await session.execute(select(Service).where(Service.user_id == u_id).order_by(Service.id.desc()))).scalars().all()
        
    if not services:
        from handlers.admin import CANCEL_BTN
        await query.edit_message_text("این کاربر هیچ سرویسی ندارد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return ConversationHandler.END
        
    from html import escape
    keys = []
    text = f"📦 <b>سرویس‌های {escape(user.fullname or 'کاربر')}</b>\n\n"
    for s in services:
        exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
        text += f"🔹 <code>{escape(s.panel_username or 'نامشخص')}</code>\nانقضا: {exp} | وضعیت: {s.status}\n\n"
        keys.append([
            InlineKeyboardButton(f"🗑 حذف {s.id}", callback_data=f"adm_askdelsvc_{s.id}"),
            InlineKeyboardButton(f"➕ ۳۰ روز تمدید", callback_data=f"adm_ren_svc_{s.id}")
        ])

    keys.append([InlineKeyboardButton("🔙 بازگشت به نمایه", callback_data=f"adm_search_back_{user.id}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    return ConversationHandler.END

async def do_renew_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    s_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        svc = (await session.execute(select(Service).where(Service.id == s_id))).scalars().first()
        if svc:
            if svc.expire_date and svc.expire_date > datetime.utcnow():
                svc.expire_date += timedelta(days=30)
            else:
                svc.expire_date = datetime.utcnow() + timedelta(days=30)
            svc.status = "ACTIVE"
            await session.commit()
    await query.answer("سرویس ۳۰ روز تمدید شد!", show_alert=True)
    # Reload would be nice, but for simplicity, we just send to panel
    await admin_panel(update, context)

async def ask_del_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    s_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        svc = (await session.execute(select(Service).where(Service.id == s_id))).scalars().first()
    
    if not svc:
        await query.edit_message_text("❌ سرویس یافت نشد.")
        return
        
    text = (
        f"❓ <b>تایید حذف سرویس</b>\n\n"
        f"سرویس: <code>{svc.panel_username}</code>\n"
        f"شناسه: {svc.id}\n\n"
        f"لطفاً نوع حذف را انتخاب کنید:"
    )
    keys = [
        [InlineKeyboardButton("🗑 فقط حذف سرویس", callback_data=f"adm_delsvc_{s_id}")],
        [InlineKeyboardButton("💰 حذف سرویس + کسر از آمار فروش", callback_data=f"adm_delsvcorder_{s_id}")],
        [InlineKeyboardButton("🔙 انصراف", callback_data=f"adm_mgsvc_{svc.user_id}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def do_del_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    s_id = int(data.split("_")[2])
    u_id = None
    
    async with AsyncSessionLocal() as session:
        svc = (await session.execute(select(Service).where(Service.id == s_id))).scalars().first()
        if svc:
            u_id = svc.user_id
            panel_uname = svc.panel_username # Usually #SUB-123
            
            # 1. Delete Service
            await session.delete(svc)
            
            # 2. Check if we need to delete Order as well
            if "order" in data and panel_uname and "#SUB-" in panel_uname:
                try:
                    order_id = int(panel_uname.replace("#SUB-", ""))
                    from database.models import Order
                    order = (await session.execute(select(Order).where(Order.id == order_id))).scalars().first()
                    if order:
                        await session.delete(order)
                        logger.info(f"Admin deleted service {s_id} AND order {order_id} to adjust stats.")
                except:
                    pass
            
            await session.commit()

    if u_id:
        await query.answer("✅ حذف با موفقیت انجام شد.", show_alert=True)
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
            if user: await render_user_profile(user, query, is_edit=True)
            else: await admin_panel(update, context)
    else:
        await query.answer("❌ خطا: سرویس یافت نشد.")
        await admin_panel(update, context)

async def adm_reset_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        if user:
            user.wallet_balance = 0.0
            await session.commit()
            logger.info(f"Admin {query.from_user.id} reset wallet of user {user.telegram_id}")
            await query.answer("✅ موجودی کیف پول کاربر صفر شد.", show_alert=True)
            await render_user_profile(user, query, is_edit=True)
        else:
            await query.answer("❌ کاربر یافت نشد.")

# --- User Tickets View ---
async def adm_view_user_tcks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        tickets = (await session.execute(select(Ticket).where(Ticket.user_id == u_id).order_by(Ticket.id.desc()))).scalars().all()
        
    if not tickets:
        await query.edit_message_text("تیکتی از این کاربر ثبت نشده است.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return ConversationHandler.END
        
    text = "✉️ <b>سابقه تیکت‌های کاربر:</b>\n\n"
    from html import escape
    for t in tickets:
        st = '🟢 باز' if t.status == 'OPEN' else '🔴 بسته'
        text += f"🔹 کد <code>#{t.id}</code> | {escape(t.department)} | وضعیت: {st}\n"
        text += f"متن: <i>{escape(t.message or '')}</i>\n"
        if t.reply: text += f"پاسخ: <i>{escape(t.reply)}</i>\n"
        text += "➖➖➖➖➖\n"
        
    keys = [[InlineKeyboardButton("🔙 جستجوی مجدد کاربر", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    return ConversationHandler.END

# --- User Receipts View ---
async def adm_view_user_recs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        if not user: return ConversationHandler.END
        
        recs = (await session.execute(select(Receipt).where(Receipt.user_id == u_id).order_by(Receipt.id.desc()).limit(15))).scalars().all()
        
    text = f"🧾 <b>آخرین فیش‌های کاربر</b> (<code>{user.telegram_id}</code>)\n\n"
    if not recs:
        text += "هیچ فیشی یافت نشد."
    for r in recs:
        typ = "شارژ" if r.receipt_type == "TOPUP" else "خرید"
        status_fa = {"APPROVED": "✅ تایید شده", "PENDING": "⏳ در انتظار", "REJECTED": "❌ رد شده"}.get(r.status, r.status)
        text += f"🔹 کد فیش: <code>{r.id}</code> | وضعیت: {status_fa}\nنوع: {typ} | مبلغ: {r.amount:,.0f} تومان\n"
        text += "➖➖➖➖➖\n"
        
    keys = [[InlineKeyboardButton("🔙 بازگشت به مشخصات", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    return ConversationHandler.END

# --- Send Message to User ---
WAIT_USER_MSG = 89
async def adm_start_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u_id = int(query.data.split("_")[2])
    context.user_data['tmp_msg_uid'] = u_id
    keys = [[InlineKeyboardButton("🔙 انصراف", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text("لطفا پیامی که میخواهید مستقیما به کاربر ارسال شود را بفرستید:", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_USER_MSG

async def adm_send_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u_id = context.user_data.get('tmp_msg_uid')
    msg = update.message.text
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        if user:
            try:
                await context.bot.send_message(user.telegram_id, f"پیام از طرف مدیریت:\n\n{msg}")
                await update.message.reply_text("✅ پیام با موفقیت ارسال شد.")
            except Exception as e:
                await update.message.reply_text(f"❌ ارسال پیام با خطا مواجه شد: {e}")
            await render_user_profile(user, update.message, is_edit=False)
            
    return ConversationHandler.END

# --- Order/Subscription Search ---
async def admin_search_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🔎 <b>جستجوی سفارش / کد اشتراک</b>\n\nشماره سفارش را وارد کنید.\nمثال: <code>5</code> یا <code>SUB-5</code> یا <code>O-5</code>"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
    return WAIT_ORDER_SEARCH

async def admin_search_order_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip().upper()
    # Extract order ID from various formats: "5", "#SUB-5", "SUB-5", "#O5", "O-5"
    import re
    match = re.search(r'(\d+)', val)
    if not match:
        await update.message.reply_text("❌ فرمت نامعتبر. لطفاً شماره سفارش را وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return WAIT_ORDER_SEARCH
    
    order_id = int(match.group(1))
    
    async with AsyncSessionLocal() as session:
        from database.models import Product
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalars().first()
        if not order:
            await update.message.reply_text(f"❌ سفارشی با شماره <code>{order_id}</code> یافت نشد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN), parse_mode="HTML")
            return WAIT_ORDER_SEARCH
        
        user = (await session.execute(select(User).where(User.id == order.user_id))).scalars().first()
        product = (await session.execute(select(Product).where(Product.id == order.product_id))).scalars().first()
        receipt = (await session.execute(select(Receipt).where(Receipt.reference_id == order.id).where(Receipt.receipt_type == "ORDER"))).scalars().first()
        service = (await session.execute(select(Service).where(Service.user_id == order.user_id).order_by(Service.id.desc()))).scalars().first()
    
    status_fa = {"PAID": "✅ موفق", "PENDING": "⏳ در انتظار", "CANCELED": "❌ لغو", "REJECTED": "🔴 رد شده"}.get(order.status, order.status)
    method_fa = {"ZARINPAL": "درگاه", "WALLET": "کیف‌پول", "CARD": "کارت به کارت", "CRYPTO": "ارز دیجیتال"}.get(order.payment_method, order.payment_method)
    date_str = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "نامشخص"
    product_name = product.name if product else "حذف شده"
    
    from html import escape
    u_fullname = escape(user.fullname or "نامشخص")
    if user and user.username:
        u_username = escape(user.username)
        u_disp = f"{u_fullname} (@{u_username})"
    else:
        u_disp = u_fullname
    p_name = escape(product_name or "حذف شده")
    
    text = f"""🔎 <b>جزئیات سفارش #{order.id}</b>

👤 <b>کاربر:</b>
نام: {u_disp}
آیدی تلگرام: <code>{user.telegram_id if user else 'نامشخص'}</code>
لینک: <a href="tg://user?id={user.telegram_id if user else 0}">کلیک</a>

📦 <b>محصول:</b> {p_name}
💰 <b>مبلغ:</b> {order.amount:,.0f} تومان
💳 <b>روش پرداخت:</b> {method_fa}
📊 <b>وضعیت:</b> {status_fa}
📅 <b>تاریخ:</b> {date_str}"""

    if receipt:
        rec_status = {"PENDING": "⏳ بررسی نشده", "APPROVED": "✅ تایید شده", "REJECTED": "❌ رد شده"}.get(receipt.status, receipt.status)
        text += f"\n\n🧾 <b>فیش:</b> #{receipt.id} | وضعیت: {rec_status}"
    else:
        text += "\n\n🧾 <b>فیش:</b> ندارد (پرداخت کیف پول)"
    
    keys = []
    if receipt and receipt.photo_id:
        keys.append([InlineKeyboardButton("🖼 مشاهده فیش", callback_data=f"adm_view_order_receipt_{receipt.id}")])
    if user:
        keys.append([InlineKeyboardButton("👤 مشاهده پروفایل کاربر", callback_data=f"adm_search_back_{user.id}")])
    keys.append([InlineKeyboardButton("🔎 جستجوی سفارش دیگر", callback_data="admin_search_order")])
    keys.append(CANCEL_BTN[0])
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    return ConversationHandler.END

async def adm_view_order_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rec_id = int(query.data.split("_")[4])
    
    async with AsyncSessionLocal() as session:
        receipt = (await session.execute(select(Receipt).where(Receipt.id == rec_id))).scalars().first()
        if not receipt or not receipt.photo_id:
            await query.edit_message_text("فیشی یافت نشد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return
    
    keys = [[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_cancel")]]
    await query.message.delete()
    await context.bot.send_photo(chat_id=query.message.chat_id, photo=receipt.photo_id, caption=f"🧾 فیش #{receipt.id}", reply_markup=InlineKeyboardMarkup(keys))

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await admin_panel(update, context)
    return ConversationHandler.END

def get_admin_users_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_search_user_start, pattern="^admin_search_user$"),
            CallbackQueryHandler(admin_search_order_start, pattern="^admin_search_order$"),
            CallbackQueryHandler(start_add_manual_svc, pattern="^adm_addsvc_"),
            CallbackQueryHandler(adm_start_msg, pattern="^adm_msg_")
        ],
        states={
            WAIT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_user_result)],
            WAIT_ORDER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_order_result)],
            WAIT_SVC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_manual_svc_text)],
            WAIT_SVC_DUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_manual_svc_dur)],
            WAIT_USER_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_send_msg)]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_search, pattern="^admin_cancel$"),
            CallbackQueryHandler(adm_search_back_handler, pattern="^adm_search_back_")
        ],
        allow_reentry=True
    )

def get_admin_users_routers():
    return [
        CallbackQueryHandler(mgmt_user_svcs, pattern="^adm_mgsvc_"),
        CallbackQueryHandler(do_renew_svc, pattern="^adm_rensvc_"),
        CallbackQueryHandler(ask_del_svc, pattern="^adm_askdelsvc_"),
        CallbackQueryHandler(do_del_svc, pattern="^adm_delsvc"),
        CallbackQueryHandler(adm_view_user_tcks, pattern="^adm_tcks_"),
        CallbackQueryHandler(adm_view_user_recs, pattern="^adm_recs_"),
        CallbackQueryHandler(adm_reset_wallet, pattern="^adm_resetwal_"),
        CallbackQueryHandler(adm_search_back_handler, pattern="^adm_search_back_"),
        CallbackQueryHandler(adm_view_order_receipt, pattern="^adm_view_order_receipt_")
    ]
