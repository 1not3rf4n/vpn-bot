from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Ticket
import core.config as config

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="support_cancel")]]

CHOOSE_DEP = 29
SEND_TICKET = 30
REPLY_TICKET = 31

async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keys = [
        [InlineKeyboardButton("بخش پشتیبانی فنی", callback_data="dep_Tech")],
        [InlineKeyboardButton("بخش پیگیری مالی", callback_data="dep_Finance")],
        [InlineKeyboardButton("بخش فروش و سوالات", callback_data="dep_Sales")],
        CANCEL_BTN[0]
    ]
    await query.edit_message_text("دپارتمان مربوطه را جهت ارتباط با کارشناسان انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keys))
    return CHOOSE_DEP

async def support_choose_dep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dep_map = {"dep_Tech": "پشتیبانی فنی", "dep_Finance": "پیگیری مالی", "dep_Sales": "فروش"}
    context.user_data['ticket_dep'] = dep_map.get(query.data, "پشتیبانی")
    await query.edit_message_text(f"دپارتمان: {context.user_data['ticket_dep']}\n\nلطفاً پیام خود را بفرستید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return SEND_TICKET

async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user_db = result.scalars().first()
        
        ticket = Ticket(user_id=user_db.id, department=context.user_data.get('ticket_dep', 'پشتیبانی'), message=message_text)
        session.add(ticket)
        await session.flush()
        ticket_id = ticket.id
        await session.commit()
        
    await update.message.reply_text(f"پیام شما با موفقیت به پشتیبانی ارسال شد. کد پیگیری: {ticket_id}")
    
    # Notify admins
    for admin in config.ADMIN_IDS:
        try:
            from html import escape
            u_name = escape(update.effective_user.full_name or "نامشخص")
            if update.effective_user.username:
                u_user = escape(update.effective_user.username)
                u_disp = f"{u_name} (@{u_user})"
            else:
                u_disp = u_name
            admin_msg = f"📩 <b>تیکت جدید</b> (#{ticket_id})\nاز طرف: {u_disp} ({user_id})\n\nمتن:\n{escape(message_text or 'بدون متن')}"
            keyboard = [[InlineKeyboardButton("✍️ پاسخ به تیکت", callback_data=f"reply_ticket_{ticket_id}")]]
            await context.bot.send_message(admin, admin_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except: pass
        
    return ConversationHandler.END

async def cancel_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            from handlers.user import send_start_menu
            await send_start_menu(update.callback_query.message, update.effective_user, update, context, is_edit=True)
        except:
            await update.callback_query.message.reply_text("عملیات لغو شد.")
    else:
        await update.message.reply_text("عملیات لغو شد.")
    return ConversationHandler.END

# Admin side reply
async def admin_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ticket_id = int(query.data.split("_")[2])
    context.user_data['replying_ticket'] = ticket_id
    await query.message.reply_text(f"لطفا جواب خود را برای تیکت #{ticket_id} بنویسید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return REPLY_TICKET

async def admin_reply_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ticket_id = context.user_data.get('replying_ticket')
    reply_text = update.message.text
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
        ticket = result.scalars().first()
        if not ticket:
            await update.message.reply_text("تیکت پیدا نشد.")
            return ConversationHandler.END
            
        ticket.reply = reply_text
        ticket.status = "CLOSED"
        
        result = await session.execute(select(User).where(User.id == ticket.user_id))
        user_db = result.scalars().first()
        await session.commit()
        
    keys = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به لیست تیکت‌ها", callback_data="admin_tickets")]])
    await update.message.reply_text("پاسخ شما ارسال شد.", reply_markup=keys)
    try:
         await context.bot.send_message(user_db.telegram_id, f"جواب پشتیبانی به تیکت #{ticket_id}:\n\n{reply_text}")
    except: pass
    return ConversationHandler.END

def get_support_conv_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(support_start, pattern="^support_new$")],
        states={
            CHOOSE_DEP: [CallbackQueryHandler(support_choose_dep, pattern="^dep_")],
            SEND_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_receive)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_support),
            CallbackQueryHandler(cancel_support, pattern="^support_cancel$")
        ]
    )

def get_admin_support_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_reply_start, pattern="^reply_ticket_")],
        states={
            REPLY_TICKET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_send)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_support),
            CallbackQueryHandler(cancel_support, pattern="^support_cancel$")
        ]
    )

async def admin_tickets_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    import core.settings as settings
    
    async with AsyncSessionLocal() as session:
        tickets = (await session.execute(select(Ticket).where(Ticket.status == "OPEN").order_by(Ticket.id.desc()).limit(10))).scalars().all()
    
    text = "🎫 <b>صندوق تیکت‌های باز</b>\nتیکت‌های منتظر پاسخ (حداکثر 10 مورد آخر):"
    keys = []
    for t in tickets:
        keys.append([InlineKeyboardButton(f"#{t.id} - ({t.department}) - 👤 مشاهده", callback_data=f"admin_view_ticket_{t.id}")])
        
    keys.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def admin_view_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    t_id = int(query.data.split("_")[3])
    
    async with AsyncSessionLocal() as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == t_id))).scalars().first()
        if not ticket:
            await query.edit_message_text("تیکت یافت نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_tickets")]]))
            return
            
        from html import escape
        user_db = (await session.execute(select(User).where(User.id == ticket.user_id))).scalars().first()
        u_name = escape(user_db.fullname or "نامشخص")
        if user_db.username:
            u_user = escape(user_db.username)
            u_disp = f"{u_name} (@{u_user})"
        else:
            u_disp = u_name
        
    text = f"🎫 <b>مشاهده تیکت #{ticket.id}</b>\n\n👤 فرستنده: {u_disp}\n🏢 دپارتمنت: {ticket.department}\n\n📝 متن تیکت:\n{escape(ticket.message or 'بدون متن')}"
    keys = [
        [InlineKeyboardButton("✍️ پاسخ به این تیکت", callback_data=f"reply_ticket_{ticket.id}")],
        [InlineKeyboardButton("🗑 پیام خوانده شد (بستن تیکت)", callback_data=f"close_ticket_{ticket.id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست تیکت‌ها", callback_data="admin_tickets")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def admin_close_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("تیکت بسته شد.", show_alert=True)
    t_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        ticket = (await session.execute(select(Ticket).where(Ticket.id == t_id))).scalars().first()
        if ticket:
            ticket.status = "CLOSED"
            await session.commit()
            
    await admin_tickets_list(update, context)

async def my_tickets_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == update.effective_user.id))).scalars().first()
        if not user_db: return
        tickets = (await session.execute(select(Ticket).where(Ticket.user_id == user_db.id).order_by(Ticket.id.desc()).limit(5))).scalars().all()
        
    text = "🎫 <b>تیکت‌های اخیر شما:</b>\n\n"
    if not tickets:
        text += "شما تا کنون با پشتیبانی ارتباط نداشته‌اید."
    else:
        from html import escape
        for t in tickets:
            status_dot = '🟢 باز' if t.status == 'OPEN' else '🔴 بسته'
            text += f"🔹 تیکت <code>#{t.id}</code> | دپارتمان: {escape(t.department)}\n"
            text += f"وضعیت: {status_dot}\n"
            if t.reply:
                text += f"پاسخ پشتیبان:\n<i>{escape(t.reply)}</i>\n"
            text += "➖➖➖➖➖\n"
            
    await update.effective_message.reply_text(text, parse_mode="HTML")

def get_support_routers():
    return [
        CallbackQueryHandler(admin_tickets_list, pattern="^admin_tickets$"),
        CallbackQueryHandler(admin_view_ticket, pattern="^admin_view_ticket_"),
        CallbackQueryHandler(admin_close_ticket, pattern="^close_ticket_"),
        CallbackQueryHandler(my_tickets_list, pattern="^my_tickets$")
    ]
