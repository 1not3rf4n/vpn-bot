from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Order, Receipt, Service, Ticket
from handlers.admin import CANCEL_BTN, admin_panel
from datetime import datetime, timedelta

WAIT_USER_ID = 63
WAIT_SVC_TEXT = 64
WAIT_SVC_DUR = 65

async def admin_search_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🔍 **جستجوی کاربر**\n\nلطفاً آیدی عددی کاربر و یا یوزرنیم وی را (با @ یا بدون @) ارسال کنید:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return WAIT_USER_ID

async def render_user_profile(user, message_obj, is_edit=False):
    async with AsyncSessionLocal() as session:
        orders = (await session.execute(select(Order).where(Order.user_id == user.id))).scalars().all()
        receipts = (await session.execute(select(Receipt).where(Receipt.user_id == user.id))).scalars().all()
        services = (await session.execute(select(Service).where(Service.user_id == user.id))).scalars().all()
        tickets = (await session.execute(select(Ticket).where(Ticket.user_id == user.id))).scalars().all()
        
    text = f"👤 **اطلاعات کاربر**\n\n"
    text += f"آیدی عددی: `{user.telegram_id}`\n"
    text += f"نام: {user.fullname}\n"
    text += f"یوزرنیم: @{user.username or 'ندارد'}\n"
    text += f"لینک پروفایل: [کلیک کنید](tg://user?id={user.telegram_id})\n"
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
        CANCEL_BTN[0]
    ]
    
    if is_edit:
        await message_obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")

async def admin_search_user_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    
    async with AsyncSessionLocal() as session:
        if val.isdigit():
            user = (await session.execute(select(User).where(User.telegram_id == int(val)))).scalars().first()
        else:
            uname = val.replace("@", "")
            user = (await session.execute(select(User).where(User.username == uname))).scalars().first()
            
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
        await query.edit_message_text("این کاربر هیچ سرویسی ندارد.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
        return ConversationHandler.END
        
    text = f"⚙️ **سرویس‌های کاربر {user.telegram_id}**\n\n"
    keys = []
    
    for s in services:
        exp_st = s.expire_date.strftime('%Y-%m-%d') if s.expire_date else 'نامشخص'
        text += f"🔹 کد #{s.id} | وضعیت: {s.status} | انقضا: {exp_st}\n"
        row = [
            InlineKeyboardButton(f"تمدید ۳۰ روزه (#{s.id})", callback_data=f"adm_rensvc_{s.id}"),
            InlineKeyboardButton(f"حذف (#{s.id})", callback_data=f"adm_delsvc_{s.id}")
        ]
        keys.append(row)
        
    keys.append([InlineKeyboardButton("🔙 بازگشت به نمایه", callback_data=f"adm_search_back_{user.id}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys))
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

async def do_del_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    s_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        svc = (await session.execute(select(Service).where(Service.id == s_id))).scalars().first()
        if svc:
            await session.delete(svc)
            await session.commit()
            u_id = svc.user_id
    await query.answer("سرویس حذف شد!", show_alert=True)
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.id == u_id))).scalars().first()
        await render_user_profile(user, query, is_edit=True)

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
        
    text = "✉️ **سابقه تیکت‌های کاربر:**\n\n"
    for t in tickets:
        st = '🟢 باز' if t.status == 'OPEN' else '🔴 بسته'
        text += f"🔹 کد `#{t.id}` | {t.department} | وضعیت: {st}\n"
        text += f"متن: _{t.message}_\n"
        if t.reply: text += f"پاسخ: _{t.reply}_\n"
        text += "➖➖➖➖➖\n"
        
    keys = [[InlineKeyboardButton("🔙 جستجوی مجدد کاربر", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
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
        
    text = f"🧾 **آخرین فیش‌های کاربر** ({user.telegram_id})\n\n"
    if not recs:
        text += "هیچ فیشی یافت نشد."
    for r in recs:
        typ = "شارژ" if r.receipt_type == "TOPUP" else "خرید"
        text += f"🔹 کد فیش: `{r.id}` | وضعیت: {r.status}\nنوع: {typ} | مبلغ: {r.amount:,.0f} تومان\n"
        text += "➖➖➖➖➖\n"
        
    keys = [[InlineKeyboardButton("🔙 بازگشت به مشخصات", callback_data=f"adm_search_back_{u_id}")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
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

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query: await update.callback_query.answer()
    await admin_panel(update, context)
    return ConversationHandler.END

def get_admin_users_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_search_user_start, pattern="^admin_search_user$"),
            CallbackQueryHandler(start_add_manual_svc, pattern="^adm_addsvc_"),
            CallbackQueryHandler(adm_start_msg, pattern="^adm_msg_")
        ],
        states={
            WAIT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_search_user_result)],
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
        CallbackQueryHandler(do_del_svc, pattern="^adm_delsvc_"),
        CallbackQueryHandler(adm_view_user_tcks, pattern="^adm_tcks_"),
        CallbackQueryHandler(adm_view_user_recs, pattern="^adm_recs_"),
        CallbackQueryHandler(adm_search_back_handler, pattern="^adm_search_back_")
    ]
