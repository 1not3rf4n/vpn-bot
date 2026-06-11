from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, CommandHandler, filters
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Category, Product, Service, Order, DiscountCode, Receipt
from services.vpn_panel import vpn_panel
import core.settings as settings
import core.config as config
import logging

logger = logging.getLogger(__name__)

(WAIT_SHOP_ACTION, WAIT_COUPON, WAIT_SHOP_METHOD, WAIT_SHOP_RECEIPT, WAIT_SERVER_NAME) = range(80, 85)
CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف و بازگشت", callback_data="shop_cancel")]]

async def shop_nav(update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id=None):
    query = update.callback_query
    
    shop_en = await settings.get_setting("menu_shop", "on")
    if shop_en != "on":
        text = "❌ فروشگاه در حال حاضر بسته است."
        if query:
            await query.answer()
            await query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return
        
    async with AsyncSessionLocal() as session:
        current_cat = None
        if parent_id:
            res = await session.execute(select(Category).where(Category.id == parent_id))
            current_cat = res.scalars().first()
                
        res = await session.execute(select(Category).where(Category.parent_id == parent_id).where(Category.is_active == True))
        sub_cats = res.scalars().all()
        
        products = []
        if parent_id:
            res = await session.execute(select(Product).where(Product.category_id == parent_id).where(Product.is_active == True))
            products = res.scalars().all()

    from html import escape
    cat_name = escape(current_cat.name) if current_cat else 'دسته اصلی'
    text = f"🛍 <b>فروشگاه سرویس‌ها</b>\n\n📌 بخش: {cat_name}\nانتخاب کنید:"
    keyboard = []
    
    for c in sub_cats:
        keyboard.append([InlineKeyboardButton(f"📁 {escape(c.name)}", callback_data=f"usr_cat_{c.id}")])
    
    for p in products:
        keyboard.append([InlineKeyboardButton(f"🛒 خرید {escape(p.name)} ({p.price:,.0f} تومان)", callback_data=f"buyprod_{p.id}")])

    if parent_id and current_cat and current_cat.parent_id:
        keyboard.append([InlineKeyboardButton("⬆️ بالاتر", callback_data=f"usr_cat_{current_cat.parent_id}")])
    elif parent_id:
        keyboard.append([InlineKeyboardButton("⬆️ دسته اصلی", callback_data=f"shop_categories")])
        
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به خانه", callback_data="start_menu")])
    
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def shop_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    shop_en = await settings.get_setting("menu_shop", "on")
    if shop_en != "on":
        await query.edit_message_text("❌ فروشگاه در حال حاضر بسته است.")
        return
    
    if query.data == "shop_categories":
        await shop_nav(update, context, None)
    elif query.data.startswith("usr_cat_"):
        cid = int(query.data.split("_")[2])
        await shop_nav(update, context, cid)

# --- Buying Flow with Coupon ---
async def send_invoice_panel(query, context, product):
    price_str = "رایگان"
    
    orig_price = context.user_data.get('checkout_original_price', 0)
    final_price = context.user_data.get('checkout_final_price', 0)
    disc_percent = context.user_data.get('checkout_discount_percent', 0)
    
    if orig_price > 0:
        if disc_percent > 0:
            price_str = f"<s>{orig_price:,.0f}</s> {final_price:,.0f} تومان (<b>{disc_percent}% تخفیف!</b>)"
        else:
            price_str = f"{orig_price:,.0f} تومان"
            
    text = f"💳 <b>پیش‌فاکتور</b>\n\nمحصول: {product.name}\nمبلغ: {price_str}\n\nجهت اعمال تخفیف روی کلید مربوطه کلیک کنید، در غیر اینصورت مستقیما روش پرداخت را انتخاب نمایید:"
    
    keys = [
        [InlineKeyboardButton("🎁 اعمال کد تخفیف", callback_data="shop_enter_coupon")],
        [InlineKeyboardButton("💳 انتخاب روش پرداخت", callback_data="shop_select_method")],
        [InlineKeyboardButton("🔙 انصراف", callback_data=f"usr_cat_{product.category_id}")]
    ]
    
    if hasattr(query, 'edit_message_text'):
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
    else:
        await query.reply_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    shop_en = await settings.get_setting("menu_shop", "on")
    if shop_en != "on":
        await query.edit_message_text("❌ فروشگاه در حال حاضر بسته است.")
        return ConversationHandler.END
    p_id = int(query.data.split("_")[1])
    context.user_data['checkout_prod_id'] = p_id
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Product).where(Product.id == p_id))
        product = res.scalars().first()
        if not product or not getattr(product, 'is_active', True):
            await query.edit_message_text("❌ متاسفانه این محصول در حال حاضر مجاز به فروش نیست.", reply_markup=InlineKeyboardMarkup(CANCEL_BTN))
            return ConversationHandler.END
            
    context.user_data['checkout_final_price'] = product.price
    context.user_data['checkout_original_price'] = product.price
    context.user_data['checkout_discount_percent'] = 0
    
    usd_rate = float(await settings.get_setting("usd_exchange_rate", "65000"))
    price_usd = round(product.price / usd_rate, 1) if product.price > 0 else 0.0
    context.user_data['checkout_final_price_usd'] = price_usd
    context.user_data['checkout_original_price_usd'] = price_usd
    
    await send_invoice_panel(query, context, product)
    return WAIT_SHOP_ACTION

async def ask_for_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keys = [[InlineKeyboardButton("🔙 بازگشت به فاکتور", callback_data="shop_cancel_coupon")]]
    await query.edit_message_text("لطفا کد تخفیف خود را به صورت پیام متنی ارسال کنید:", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_COUPON

async def cancel_coupon_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p_id = context.user_data.get('checkout_prod_id')
    async with AsyncSessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
        if product:
            await send_invoice_panel(query, context, product)
    return WAIT_SHOP_ACTION

async def apply_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text
    p_id = context.user_data.get('checkout_prod_id')
    
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func
        res = await session.execute(select(Product).where(Product.id == p_id))
        product = res.scalars().first()
        
        # Case insensitive and stripped coupon check
        clean_code = code.strip().lower()
        res = await session.execute(select(DiscountCode).where(func.lower(DiscountCode.code) == clean_code).where(DiscountCode.active == True))
        coupon = res.scalars().first()
        
        if not coupon or (coupon.max_uses > 0 and coupon.used_count >= coupon.max_uses):
            await update.message.reply_text("❌ کد تخفیف نامعتبر است یا ظرفیت استفاده از آن تمام شده.")
            return WAIT_COUPON
            
        discount_amount = (product.price * coupon.percent) / 100
        final_price = product.price - discount_amount
        
        usd_rate = float(await settings.get_setting("usd_exchange_rate", "65000"))
        final_price_usd = round(final_price / usd_rate, 1) if final_price > 0 else 0.0
        
        context.user_data['checkout_final_price'] = final_price
        context.user_data['checkout_final_price_usd'] = final_price_usd
        context.user_data['checkout_coupon_id'] = coupon.id
        context.user_data['checkout_discount_percent'] = coupon.percent
        
        if update.callback_query:
            await send_invoice_panel(update.callback_query, context, product)
        else:
            await send_invoice_panel(update.message, context, product)
            
        await update.message.reply_text(f"✅ کد تخفیف {coupon.percent}% با موفقیت روی فاکتور اعمال شد!")
        return WAIT_SHOP_ACTION

async def shop_select_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    p_id = context.user_data.get('checkout_prod_id')
    async with AsyncSessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
        if not product: return ConversationHandler.END
    
    c_st = await settings.get_setting("card_enabled", "on")
    z_st = await settings.get_setting("zarinpal_enabled", "off")
    crypt_st = await settings.get_setting("crypto_enabled", "off")
    tetra_st = await settings.get_setting("tetra98_enabled", "off")
    
    keys = []
    has_toman = product.price > 0
    
    usd_rate = float(await settings.get_setting("usd_exchange_rate", "65000"))
    price_usd = round(product.price / usd_rate, 1) if product.price > 0 else 0.0
    has_usd = price_usd > 0
    
    if has_toman:
        keys.append([InlineKeyboardButton("💰 پرداخت از موجودی کیف پول", callback_data="shop_pay_wallet")])
        if c_st == "on": keys.append([InlineKeyboardButton("💳 کارت به کارت", callback_data="shop_pay_card")])
        if tetra_st == "on": keys.append([InlineKeyboardButton("⚡ کارت به کارت سریع", callback_data="shop_pay_tetra98")])
        if z_st == "on": keys.append([InlineKeyboardButton("🌐 درگاه زرین‌پال", callback_data="shop_pay_zarinpal")])
    if has_usd and crypt_st == "on":
        keys.append([InlineKeyboardButton("🪙 ارز دیجیتال (دلار)", callback_data="shop_pay_crypto")])

    keys.append(CANCEL_BTN[0])
    
    await query.edit_message_text("لطفا روش پرداخت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(keys))
    return WAIT_SHOP_METHOD

async def shop_handle_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    p_id = context.user_data.get('checkout_prod_id')
    user_id = update.effective_user.id
    
    async with AsyncSessionLocal() as session:
        product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
        if not product: return ConversationHandler.END
        final_price = context.user_data.get('checkout_final_price', product.price)
        final_price_usd = context.user_data.get('checkout_final_price_usd', 0.0)
        
        if query.data == "shop_pay_crypto":
            from database.models import CryptoNetwork
            from telegram import CopyTextButton
            nets = (await session.execute(select(CryptoNetwork).where(CryptoNetwork.is_active == True))).scalars().all()
            if not nets:
                await query.edit_message_text("هیچ شبکه ارزی در حال حاضر فعال نیست.")
                return ConversationHandler.END
            
            from html import escape
            text = f"مبلغ قابل پرداخت: <b>{final_price_usd} دلار</b> (رمزارز)\nبه یکی از آدرس‌های زیر واریز کنید:\n\n"
            copy_keys = [[InlineKeyboardButton("💰 کپی مبلغ", copy_text=CopyTextButton(text=str(final_price_usd)))]]
            for n in nets:
                text += f"🔹 {escape(n.name)}:\n<code>{escape(n.address)}</code>\n\n"
                copy_keys.append([InlineKeyboardButton(f"📋 کپی آدرس {escape(n.name)}", copy_text=CopyTextButton(text=n.address))])
            text += "پس از واریز، <b>عکس رسید</b> تراکنش را ارسال کنید."
            
            context.user_data['checkout_pay_method'] = 'CRYPTO'
            copy_keys.append(CANCEL_BTN[0])
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(copy_keys))
            return WAIT_SHOP_RECEIPT
            
        elif query.data == "shop_pay_card":
            from telegram import CopyTextButton
            from html import escape
            card_num = await settings.get_setting("admin_card", "نامشخص")
            text = f"مبلغ قابل پرداخت: <b>{final_price:,.0f} تومان</b>\nشماره کارت:\n<code>{card_num}</code>\n\n<b>عکس رسید پرداختی</b> را ارسال کنید."
            context.user_data['checkout_pay_method'] = 'CARD'
            keys = [
                [InlineKeyboardButton("📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_num)),
                 InlineKeyboardButton("💰 کپی مبلغ", copy_text=CopyTextButton(text=str(int(final_price))))],
                CANCEL_BTN[0]
            ]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys))
            return WAIT_SHOP_RECEIPT

        elif query.data == "shop_pay_wallet":
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
            
            if not product: return ConversationHandler.END
            
            final_price = context.user_data.get('checkout_final_price', product.price)
            
            if user_db.wallet_balance < final_price:
                keys = [[InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_add")],
                        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"usr_cat_{product.category_id}")]]
                await query.edit_message_text(f"❌ موجودی کافی نیست. (نیاز: {final_price:,.0f} تومان ، موجودی: {user_db.wallet_balance:,.0f} تومان)", reply_markup=InlineKeyboardMarkup(keys))
                return ConversationHandler.END
                
            user_db.wallet_balance -= final_price
            
            # apply coupon logic
            c_id = context.user_data.get('checkout_coupon_id')
            if c_id:
                coupon = (await session.execute(select(DiscountCode).where(DiscountCode.id == c_id))).scalars().first()
                if coupon: coupon.used_count += 1
                
            from core.provision import provision_order_and_notify
            order = Order(user_id=user_db.id, product_id=product.id, amount=final_price, payment_method="WALLET", status="PAID")
            session.add(order)
            await session.commit()
            
            sub_code = f"#SUB-{order.id}"
            
            # --- Referral Reward ---
            if user_db.referred_by_id:
                inviter = (await session.execute(select(User).where(User.id == user_db.referred_by_id))).scalars().first()
                if inviter:
                    prc = await settings.get_setting("referral_percent", "10")
                    reward = (final_price * int(prc)) / 100
                    if reward > 0:
                        inviter.wallet_balance += reward
                        try:
                            await context.bot.send_message(inviter.telegram_id, f"🎉 زیرمجموعه شما خریدی انجام داد و مبلغ {reward} تومان به عنوان کمیسیون به کیف پول شما اضافه شد!")
                        except: pass
# -----------------------
                    await session.commit()
                    
                    keys = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به صفحه اصلی", callback_data="start_menu")]])
                    await query.edit_message_text(f"✅ پردازش موفقیت‌آمیز بود. لطفا چند لحظه منتظر صدور فاکتور و تحویل اکانت باشید...", reply_markup=keys)
                    
                    # Check if custom server name is enabled for this product
                    custom_name_enabled = await settings.get_setting("custom_server_name_enabled", "on") == "on"
                    if custom_name_enabled and product.product_type == 'V2RAY':
                        context.user_data['provision_order_id'] = order.id
                        await ask_server_name(update, context)
                    else:
                        await provision_order_and_notify(order.id, context.bot)

        elif query.data == "shop_pay_tetra98":
            tetra_enabled = await settings.get_setting("tetra98_enabled", "off")
            if tetra_enabled != "on":
                await query.edit_message_text("❌ این روش پرداخت در حال حاضر غیرفعال است.")
                return ConversationHandler.END

            api_key = getattr(config, "TETRA98_API_KEY", "") or ""
            if not api_key:
                await query.edit_message_text("❌ خطا: کلید درگاه Tetra98 روی سرور تنظیم نشده است.")
                return ConversationHandler.END

            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            if not user_db:
                await query.edit_message_text("❌ خطا: کاربر یافت نشد.")
                return ConversationHandler.END

            final_price = context.user_data.get('checkout_final_price', product.price)
            if final_price <= 0:
                await query.edit_message_text("❌ این محصول نیازی به پرداخت ندارد.")
                return ConversationHandler.END

            order = Order(
                user_id=user_db.id,
                product_id=product.id,
                amount=final_price,
                payment_method="TETRA98",
                status="PENDING",
            )
            order.coupon_id = context.user_data.get("checkout_coupon_id")
            session.add(order)
            await session.flush()

            hash_id = f"invoice-{order.id}"
            order.gateway_hash_id = hash_id

            from services.tetra98 import Tetra98Gateway
            gw = Tetra98Gateway(api_key)

            desc = f"Order #{order.id} - {product.name}"
            callback_url = f"https://t.me/{context.bot.username}" if getattr(context.bot, "username", None) else "https://t.me/"
            status_code, data, raw = await gw.create_order(
                hash_id=hash_id,
                amount=int(final_price),
                description=desc,
                callback_url=callback_url,
                email="",
                mobile=(query.from_user.phone_number if hasattr(query.from_user, "phone_number") else ""),
            )

            if status_code != 200 or str(data.get("status")) != "100":
                await session.rollback()
                code = data.get("status", status_code)
                msg = data.get("message") or data.get("error") or ""
                logger.error(f"Tetra98 create_order failed: http={status_code} code={code} msg={msg} raw={raw[:500]}")
                detail = f"\nجزئیات: {msg}" if msg else ""
                await query.edit_message_text(f"❌ خطا در ایجاد سفارش پرداخت. (کد: {code}){detail}")
                return ConversationHandler.END

            authority = data.get("Authority") or ""
            tracking_id = data.get("tracking_id") or ""
            payment_url_bot = data.get("payment_url_bot") or ""
            payment_url_web = data.get("payment_url_web") or ""

            order.gateway_authority = authority
            order.gateway_tracking_id = str(tracking_id)
            await session.commit()

            from html import escape
            text = (
                f"⚡ <b>پرداخت سریع</b>\n\n"
                f"مبلغ: <b>{final_price:,.0f} تومان</b>\n"
                f"کد پیگیری: <code>{escape(str(tracking_id))}</code>\n\n"
                f"برای پرداخت روی یکی از لینک‌های زیر بزنید، بعد از پرداخت برگردید و روی «بررسی پرداخت» کلیک کنید."
            )

            keys = []
            if payment_url_bot:
                keys.append([InlineKeyboardButton("پرداخت از طریق ربات", url=payment_url_bot)])
            if payment_url_web:
                keys.append([InlineKeyboardButton("پرداخت از طریق سایت", url=payment_url_web)])
            keys.append([InlineKeyboardButton("✅ بررسی پرداخت", callback_data=f"tetra_verify_{order.id}")])
            keys.append([InlineKeyboardButton("🔙 انصراف", callback_data="shop_cancel")])

            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
            return ConversationHandler.END
        
    for k in ['checkout_prod_id', 'checkout_final_price', 'checkout_final_price_usd', 'checkout_coupon_id', 'checkout_pay_method']:
        context.user_data.pop(k, None)
        
    return ConversationHandler.END

async def shop_receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("لطفاً حتماً عکس فیش را ارسال کنید!")
        return WAIT_SHOP_RECEIPT
        
    photo_id = update.message.photo[-1].file_id
    p_id = context.user_data.get('checkout_prod_id')
    pay_method = context.user_data.get('checkout_pay_method', 'UNKNOWN')
    user_id = update.effective_user.id
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
        product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
        final_price = context.user_data.get('checkout_final_price', product.price) if product else 0
        final_price_usd = context.user_data.get('checkout_final_price_usd', 0.0)
        
        c_id = context.user_data.get('checkout_coupon_id')
        if c_id:
            coupon = (await session.execute(select(DiscountCode).where(DiscountCode.id == c_id))).scalars().first()
            if coupon: coupon.used_count += 1
            
        # Create Order as PENDING
        order = Order(user_id=user_db.id, product_id=product.id, amount=final_price, payment_method=pay_method, status="PENDING")
        session.add(order)
        await session.flush()
        
        # Create Receipt linked to Order
        # Depending on payment method, we register amount
        amt = final_price_usd if pay_method == "CRYPTO" else final_price
        receipt = Receipt(user_id=user_db.id, amount=amt, photo_id=photo_id, status="PENDING", receipt_type="ORDER", reference_id=order.id)
        session.add(receipt)
        await session.flush()
        receipt_id = receipt.id
        
        from html import escape
        if pay_method == "CRYPTO":
            amt_str = f"{final_price_usd} دلار"
        else:
            amt_str = f"{final_price:,.0f} تومان"
            
        u_name = escape(update.effective_user.full_name)
        u_user = f" (@{escape(update.effective_user.username)})" if update.effective_user.username else ""
        p_name = escape(product.name if product else "حذف شده")
        
        admin_text = f"🛒 <b>درخواست خرید محصول (پرداخت مستقیم)</b>\nکاربر: {u_name}{u_user}\nمحصول: {p_name}\nمبلغ پرداخت: {amt_str}\nآیدی رسید: #O{receipt_id}"
        keys = [
            [InlineKeyboardButton("✅ تایید سند", callback_data=f"verify_receipt_{receipt_id}")],
            [InlineKeyboardButton("❌ رد سند", callback_data=f"reject_receipt_{receipt_id}")]
        ]
        admins = (await session.execute(select(User).where(User.is_admin == True))).scalars().all()
        for ad in admins:
            try: await context.bot.send_photo(chat_id=ad.telegram_id, photo=photo_id, caption=admin_text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="HTML")
            except: pass
            
        await session.commit()
    
    await update.message.reply_text("✅ فیش شما ارسال شد و پس از تایید توسط پشتیبانی، سرویس فعال می‌گردد.")
    await shop_nav(update, context, None)
    
    for k in ['checkout_prod_id', 'checkout_final_price', 'checkout_coupon_id', 'checkout_pay_method']:
        context.user_data.pop(k, None)
    return ConversationHandler.END

async def ask_server_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask user to choose server name or use random."""
    query = update.callback_query
    await query.answer()
    
    keys = [
        [InlineKeyboardButton("🎲 استفاده از اسم رندوم سیستم", callback_data="server_name_random")],
        [InlineKeyboardButton("✏️ انتخاب اسم دلخواه", callback_data="server_name_custom")]
    ]
    await query.edit_message_text(
        "🌐 <b>انتخاب اسم سرور</b>\n\n"
        "لطفاً یکی را انتخاب کنید:\n\n"
        "🎲 <b>رندوم</b>: سیستم به صورت خودکار یک اسم برای سرور شما انتخاب می‌کند.\n"
        "✏️ <b>دلخواه</b>: شما می‌توانید اسم دلخواه خود را وارد کنید (مثلاً myname-vpn).",
        reply_markup=InlineKeyboardMarkup(keys),
        parse_mode="HTML"
    )

async def handle_server_name_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "server_name_random":
        order_id = context.user_data.get('provision_order_id')
        if order_id:
            from core.provision import provision_order_and_notify
            await provision_order_and_notify(order_id, context.bot)
        context.user_data.pop('provision_order_id', None)
        context.user_data.pop('custom_server_name', None)
        
    elif query.data.startswith("server_name_custom"):
        # Could be with or without order_id
        parts = query.data.split("_")
        if len(parts) > 3:
            # srvname_custom_{order_id} format
            order_id = int(parts[-1])
            context.user_data['provision_order_id'] = order_id
        elif len(parts) == 3:
            # server_name_custom format (from wallet payment)
            pass
        await query.edit_message_text(
            "✏️ لطفاً اسم دلخواه سرور خود را وارد کنید:\n\n"
            "(فقط حروف انگلیسی، اعداد و کاراکترهای - و _ مجازند)\n"
            "مثال: myvpn-server یا uk-london",
            reply_markup=InlineKeyboardMarkup(CANCEL_BTN)
        )
        return WAIT_SERVER_NAME
    
    elif query.data.startswith("srvname_random_"):
        order_id = int(query.data.split("_")[-1])
        if order_id:
            from core.provision import provision_order_and_notify
            await provision_order_and_notify(order_id, context.bot)
        await query.edit_message_text("✅ سرویس با اسم رندوم در حال ساخت است...")
        
    elif query.data.startswith("srvname_custom_"):
        order_id = int(query.data.split("_")[-1])
        context.user_data['provision_order_id'] = order_id
        context.user_data['waiting_custom_name'] = True
        await query.edit_message_text(
            "✏️ لطفاً اسم دلخواه سرور خود را وارد کنید:\n\n"
            "(فقط حروف انگلیسی، اعداد و کاراکترهای - و _ مجازند)\n"
            "مثال: myvpn-server یا uk-london\n\n"
            "⚠️ <b>مهم</b>: پیام خود را به صورت متنی ارسال کنید.",
            reply_markup=InlineKeyboardMarkup(CANCEL_BTN),
            parse_mode="HTML"
        )
        return WAIT_SERVER_NAME

async def save_custom_server_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    name = update.message.text.strip()
    
    # Validate: only alphanumeric, dash and underscore
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        await update.message.reply_text(
            "❌ فقط حروف انگلیسی، اعداد و کاراکترهای - و _ مجازند!\n"
            "مثال: myvpn-server یا uk_london",
            reply_markup=InlineKeyboardMarkup(CANCEL_BTN)
        )
        return WAIT_SERVER_NAME
    
    # Limit length
    if len(name) > 32:
        await update.message.reply_text(
            "❌ طول اسم نباید بیش از 32 کاراکتر باشد!",
            reply_markup=InlineKeyboardMarkup(CANCEL_BTN)
        )
        return WAIT_SERVER_NAME
    
    context.user_data['custom_server_name'] = name
    order_id = context.user_data.get('provision_order_id')
    
    if order_id:
        from core.provision import provision_order_and_notify
        await provision_order_and_notify(order_id, context.bot, custom_server_name=name)
    
    context.user_data.pop('provision_order_id', None)
    return ConversationHandler.END


async def cancel_chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    p_id = context.user_data.get('checkout_prod_id')
    cat_id = 0
    if p_id:
        async with AsyncSessionLocal() as session:
            product = (await session.execute(select(Product).where(Product.id == p_id))).scalars().first()
            cat_id = product.category_id if product else 0
    # Clean up server name data
    context.user_data.pop('provision_order_id', None)
    context.user_data.pop('custom_server_name', None)
    await shop_nav(update, context, cat_id if cat_id > 0 else None)
    return ConversationHandler.END

def get_shop_handlers():
    return [
        CallbackQueryHandler(tetra_verify_payment, pattern="^tetra_verify_"),
        CallbackQueryHandler(shop_router, pattern="^(shop_categories|usr_cat_)"),
        CallbackQueryHandler(handle_server_name_choice, pattern="^server_name_|^srvname_"),
        ConversationHandler(
            entry_points=[CallbackQueryHandler(checkout_start, pattern="^buyprod_")],
            states={
                WAIT_SHOP_ACTION: [
                    CallbackQueryHandler(ask_for_coupon, pattern="^shop_enter_coupon$"),
                    CallbackQueryHandler(shop_select_method, pattern="^shop_select_method$")
                ],
                WAIT_COUPON: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, apply_coupon),
                    CallbackQueryHandler(cancel_coupon_handler, pattern="^shop_cancel_coupon$")
                ],
                WAIT_SHOP_METHOD: [CallbackQueryHandler(shop_handle_method, pattern="^shop_pay_")],
                WAIT_SHOP_RECEIPT: [MessageHandler(filters.PHOTO, shop_receive_receipt)],
                WAIT_SERVER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_custom_server_name)]
            },
            fallbacks=[
                CallbackQueryHandler(cancel_chk, pattern="^usr_cat_|shop_cancel|server_name_|^srvname_"),
                CommandHandler("cancel", cancel_chk)
            ],
            allow_reentry=True
        )
    ]


async def tetra_verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[2])

    api_key = getattr(config, "TETRA98_API_KEY", "") or ""
    if not api_key:
        await query.edit_message_text("❌ خطا: کلید درگاه Tetra98 روی سرور تنظیم نشده است.")
        return

    from services.tetra98 import Tetra98Gateway
    gw = Tetra98Gateway(api_key)

    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalars().first()
        if not order:
            await query.edit_message_text("❌ سفارش یافت نشد.")
            return
        if order.status == "PAID":
            await query.edit_message_text("✅ این سفارش قبلاً پرداخت شده است.")
            return

        authority = order.gateway_authority or ""
        if not authority:
            await query.edit_message_text("❌ خطا: Authority برای این سفارش ذخیره نشده است.")
            return

        status_code, data, raw = await gw.verify(authority=authority)
        if status_code != 200:
            logger.error(f"Tetra98 verify HTTP error: http={status_code} raw={raw[:500]}")
            await query.edit_message_text("❌ خطا در ارتباط با درگاه. لطفاً دوباره تلاش کنید.")
            return

        # Some gateways return int/str; accept both
        ok = False
        if isinstance(data, dict):
            st = data.get("status")
            ok = (st == 100) or (st == "100") or (str(st) == "100")

        if not ok:
            await query.edit_message_text("⏳ هنوز پرداخت برای این سفارش تایید نشده است. چند دقیقه دیگر دوباره تست کنید.")
            return

        # Mark paid and provision
        order.status = "PAID"

        # Apply coupon usage only after successful payment
        if order.coupon_id:
            coupon = (await session.execute(select(DiscountCode).where(DiscountCode.id == order.coupon_id))).scalars().first()
            if coupon:
                coupon.used_count += 1

        await session.commit()

    from core.provision import provision_order_and_notify
    await query.edit_message_text("✅ پرداخت تایید شد. در حال تحویل سرویس...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 صفحه اصلی", callback_data="start_menu")]]))
    await provision_order_and_notify(order_id, context.bot)

    for k in ['checkout_prod_id', 'checkout_final_price', 'checkout_final_price_usd', 'checkout_coupon_id', 'checkout_pay_method']:
        context.user_data.pop(k, None)
