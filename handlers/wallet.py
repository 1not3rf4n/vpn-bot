from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Receipt
import core.settings as settings
import core.config as config

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="wallet_cancel")]]

(TOP_UP_AMOUNT, TOP_UP_METHOD, SEND_RECEIPT) = range(20, 23)

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == update.effective_user.id))
        user = result.scalars().first()
        bal = user.wallet_balance if user else 0.0

    text = f"💰 **کیف پول شما**\nموجودی فعلی: `{bal}` تومان\n\nبرای شارژ حساب روی دکمه زیر کلیک کنید."
    keyboard = [
        [InlineKeyboardButton("➕ شارژ حساب", callback_data="wallet_add")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="start_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def request_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("لطفا مبلغ مورد نظر برای شارژ (به تومان) را بصورت عدد لاتین وارد کنید:", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
    return TOP_UP_AMOUNT

async def select_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = update.message.text
    if not amount.isdigit():
        await update.message.reply_text("مبلغ نامعتبر است، لطفا فقط عدد وارد کنید.")
        return TOP_UP_AMOUNT
    
    context.user_data['top_up_amount'] = int(amount)
    
    text = f"مبلغ انتخابی: {int(amount):,.0f} تومان\nلطفا روش پرداخت را انتخاب کنید:"
    
    # Check what is enabled
    c_st = await settings.get_setting("card_enabled", "on")
    z_st = await settings.get_setting("zarinpal_enabled", "off")
    crypt_st = await settings.get_setting("crypto_enabled", "off")
    
    keyboard = []
    if c_st == "on": keyboard.append([InlineKeyboardButton("💳 کارت به کارت (تایید دستی)", callback_data="pay_card")])
    if z_st == "on": keyboard.append([InlineKeyboardButton("🌐 درگاه آنلاین زرین‌پال", callback_data="pay_zarinpal")])
    if crypt_st == "on": keyboard.append([InlineKeyboardButton("🪙 ارز دیجیتال (تتر/ترون)", callback_data="pay_crypto")])
    
    keyboard.append(CANCEL_BTN[0])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return TOP_UP_METHOD

async def handle_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "pay_zarinpal":
        # Ideally, generate zarinpal link here
        await query.edit_message_text("این درگاه در حال حاضر متصل نیست. لطفا از کارت به کارت استفاده کنید.")
        return ConversationHandler.END
        
    elif query.data == "pay_card":
        from telegram import CopyTextButton
        card_num = await settings.get_setting("admin_card", "نامشخص")
        amount = context.user_data.get('top_up_amount', 0)
        text = f"لطفا مبلغ **{amount:,.0f} تومان** را به شماره کارت زیر واریز کنید:\n\n`{card_num}`\n\nپس از واریز، **عکس فیش پرداختی** را دقیقاً همینجا ارسال کنید."
        keys = [
            [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_num)),
             InlineKeyboardButton("💰 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
            CANCEL_BTN[0]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keys))
        return SEND_RECEIPT
        
    elif query.data == "pay_crypto":
        from telegram import CopyTextButton
        async with AsyncSessionLocal() as session:
            from database.models import CryptoNetwork
            nets = (await session.execute(select(CryptoNetwork).where(CryptoNetwork.is_active == True))).scalars().all()
            if not nets:
                await query.edit_message_text("هیچ شبکه ارزی در حال حاضر فعال نیست.")
                return ConversationHandler.END
            
            amount = context.user_data.get('top_up_amount', 0)
            usd_rate = float(await settings.get_setting("usd_exchange_rate", "65000"))
            amount_usd = round(amount / usd_rate, 1) if amount > 0 else 0.0
            
            text = f"لطفا مبلغ **{amount_usd} دلار** (معادل {amount:,.0f} تومان) را به یکی از آدرس‌های زیر واریز کنید:\n\n"
            copy_keys = [[InlineKeyboardButton("💰 کپی مبلغ", copy_text=CopyTextButton(text=str(amount_usd)))]]
            for n in nets:
                text += f"🔹 شبکه {n.name} ({n.network}):\n`{n.address}`\n\n"
                copy_keys.append([InlineKeyboardButton(f"📋 کپی آدرس {n.name}", copy_text=CopyTextButton(text=n.address))])
            text += "پس از واریز، **عکس رسید تراکنش** را دقیقاً همینجا ارسال کنید."
            
        copy_keys.append(CANCEL_BTN[0])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(copy_keys))
        return SEND_RECEIPT

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً حتماً عکس فیش را ارسال کنید!")
        return SEND_RECEIPT
        
    photo_id = update.message.photo[-1].file_id
    amount = context.user_data.get('top_up_amount', 0)
    user_id = update.effective_user.id
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.telegram_id == user_id))
        user_db = result.scalars().first()
        
        receipt = Receipt(user_id=user_db.id, amount=amount, photo_id=photo_id, status="PENDING", receipt_type="TOPUP")
        session.add(receipt)
        await session.flush() # get ID
        receipt_id = receipt.id
        
        # Notify Admins
        from html import escape
        u_name = escape(update.effective_user.full_name or "نامشخص")
        if update.effective_user.username:
            u_user = escape(update.effective_user.username)
            u_disp = f"{u_name} (@{u_user})"
        else:
            u_disp = u_name
        admin_text = f"💰 <b>درخواست شارژ حساب تحویل شد</b>\nکاربر: {u_disp} ({user_id})\nمبلغ: {amount} تومان\nآیدی دیتابیس رسید: #T{receipt_id}"
        keys = [
            [InlineKeyboardButton("✅ تایید و شارژ", callback_data=f"verify_receipt_{receipt_id}")],
            [InlineKeyboardButton("❌ رد تراکنش", callback_data=f"reject_receipt_{receipt_id}")]
        ]
        
        admins = (await session.execute(select(User).where(User.is_admin == True))).scalars().all()
        for ad in admins:
            try:
                await context.bot.send_photo(chat_id=ad.telegram_id, photo=photo_id, caption=admin_text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
            except: pass
            
        await session.commit()
        
    await update.message.reply_text("✅ فیش شما با موفقیت ثبت شد و پس از تایید مدیر، درخواست شما اعمال خواهد شد.")
    await wallet_menu(update, context)
    return ConversationHandler.END

async def cancel_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    else:
        await update.message.reply_text("عملیات شارژ لغو شد.")
    await wallet_menu(update, context) # Requires query existance or passing context. We can just send a generic.
    return ConversationHandler.END

def get_wallet_conv_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(request_amount, pattern="^wallet_add$")],
        states={
            TOP_UP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_method)],
            TOP_UP_METHOD: [CallbackQueryHandler(handle_method, pattern="^pay_")],
            SEND_RECEIPT: [MessageHandler(filters.PHOTO, receive_receipt)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_wallet),
            CallbackQueryHandler(cancel_wallet, pattern="^wallet_cancel$")
        ],
        allow_reentry=True
    )

## Admin Receipts Handlers
async def admin_receipts_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        receipts = (await session.execute(select(Receipt).where(Receipt.status == "PENDING").order_by(Receipt.id.desc()).limit(10))).scalars().all()
        
    text = "🧾 **صندوق فیش‌های بررسی‌نشده**\nتعداد فیش‌های منتظر تایید (حداکثر 10 مورد):"
    if not receipts:
        text = "هیچ فیش منتظر تاییدی وجود ندارد."
        
    keys = []
    for r in receipts:
        r_type = "شارژ" if r.receipt_type == "TOPUP" else "خرید"
        keys.append([InlineKeyboardButton(f"فیش #{r.id} ({r_type}) - {r.amount}T", callback_data=f"admin_view_receipt_{r.id}")])
    keys.append([InlineKeyboardButton("🔙 بازگشت به پنل", callback_data="admin_panel")])
    
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
    else:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")

async def admin_view_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rec_id = int(query.data.split("_")[3])
    
    async with AsyncSessionLocal() as session:
        receipt = (await session.execute(select(Receipt).where(Receipt.id == rec_id))).scalars().first()
        if not receipt:
            await query.edit_message_text("رسید مورد نظر پیدا نشد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_receipts")]]))
            return
            
        user_db = (await session.execute(select(User).where(User.id == receipt.user_id))).scalars().first()
        
    r_type_text = "شارژ کیف پول" if receipt.receipt_type == "TOPUP" else "خرید محصول مستقیم"
    from html import escape
    u_name = escape(user_db.fullname or "نامشخص")
    u_user = escape(user_db.username) if user_db.username else "ندارد"
    u_disp = f"{u_name} (@{u_user})" if user_db.username else u_name
    admin_text = f"🛒 <b>تایید فیش مالی</b>\nکاربر: {u_disp}\nمبلغ: {receipt.amount} تومان\nنوع فیش: {r_type_text}\nآیدی رسید: #{receipt.id}"
    keys = [
        [InlineKeyboardButton("✅ تایید سند", callback_data=f"verify_receipt_{receipt.id}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"reject_receipt_{receipt.id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_receipts")]
    ]
    # Delete current menu message and send a photo instead
    await query.message.delete()
    await context.bot.send_photo(chat_id=query.message.chat_id, photo=receipt.photo_id, caption=admin_text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def verify_receipt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    action, _, rec_id = query.data.split("_")
    rec_id = int(rec_id)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Receipt).where(Receipt.id == rec_id))
        receipt = result.scalars().first()
        if not receipt or receipt.status != "PENDING":
            await query.edit_message_caption(
                "این رسید قبلا بررسی شده است یا وجود ندارد.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به فیش‌ها", callback_data="admin_receipts")]])
            )
            return

        result = await session.execute(select(User).where(User.id == receipt.user_id))
        user_db = result.scalars().first()
        
        keys = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به فیش‌ها", callback_data="admin_receipts")]])
        if action == "verify":
            receipt.status = "APPROVED"
            
            if receipt.receipt_type == "TOPUP":
                user_db.wallet_balance += receipt.amount
                await query.edit_message_caption("✅ تراکنش تایید شد و حساب کاربر شارژ گردید.", reply_markup=keys)
                try:
                    await context.bot.send_message(user_db.telegram_id, f"✅ کیف پول شما مبلغ {receipt.amount} تومان با موفقیت شارژ شد.")
                except: pass
                
            elif receipt.receipt_type == "ORDER":
                from database.models import Order
                from core.provision import provision_order_and_notify
                
                order = (await session.execute(select(Order).where(Order.id == receipt.reference_id))).scalars().first()
                if order:
                    order.status = "PAID"
                    await session.commit()
                    
                    await query.edit_message_caption("✅ رسید تایید شد و پروسه تحویل اکانت آغاز گردید.", reply_markup=keys)
                    await provision_order_and_notify(order.id, context.bot)
            
            await session.commit()
        elif action == "reject":
            receipt.status = "REJECTED"
            await session.commit()
            await query.edit_message_caption("❌ تراکنش رد شد.", reply_markup=keys)
            try:
                await context.bot.send_message(user_db.telegram_id, f"❌ متاسفانه فیش ارسالی شما برای مبلغ {receipt.amount} تایید نشد.")
            except: pass

async def user_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == update.effective_user.id))).scalars().first()
        if not user_db: return
        
        from database.models import Order
        orders = (await session.execute(select(Order).where(Order.user_id == user_db.id).order_by(Order.id.desc()).limit(10))).scalars().all()
        
    text = "🧾 **تاریخچه تراکنش‌های اخیر شما:**\n\n"
    if not orders:
        text += "هیچ سفارشی یافت نشد."
    else:
        for o in orders:
            text += f"🔸 سفارش `#{o.id}`\nمبلغ: {o.amount:,.0f} تومان\nوضعیت: {o.status}\nتوضیحات: {o.payment_method}\n➖➖➖➖➖\n"
            
    async with AsyncSessionLocal() as session:
        receipts = (await session.execute(select(Receipt).where(Receipt.user_id == user_db.id).where(Receipt.receipt_type == 'TOPUP').order_by(Receipt.id.desc()).limit(5))).scalars().all()
    if receipts:
        text += "\n💸 **۵ فیش شارژ اخیر:**\n\n"
        for r in receipts:
            text += f"🔹 فیش `#{r.id}` | {r.amount:,.0f} تومان | وضعیت: {r.status}\n"
            
    await update.effective_message.reply_text(text, parse_mode="Markdown")

def get_wallet_routers():
    from telegram.ext import CallbackQueryHandler
    return [
        CallbackQueryHandler(admin_receipts_list, pattern="^admin_receipts$"),
        CallbackQueryHandler(admin_view_receipt, pattern="^admin_view_receipt_"),
        CallbackQueryHandler(user_transactions, pattern="^my_transactions$")
    ]
