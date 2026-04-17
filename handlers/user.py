from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CopyTextButton
from telegram.ext import ContextTypes
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Category, Product, Service
import core.config as config
import core.settings as settings
from core.utils import check_forced_join
from html import escape

async def send_start_menu(message, user_tg, update, context, is_edit=False, ref_id_passed=None):
    if not await check_forced_join(update, context):
        return

    async with AsyncSessionLocal() as session:
        # Check first user
        result = await session.execute(select(User))
        is_first = len(result.scalars().all()) == 0
        
        result = await session.execute(select(User).where(User.telegram_id == user_tg.id))
        db_user = result.scalars().first()
        
        if not db_user:
            is_admin = is_first or (user_tg.id in config.ADMIN_IDS)
            db_user = User(
                telegram_id=user_tg.id,
                fullname=user_tg.full_name,
                username=user_tg.username,
                is_admin=is_admin
            )
            if ref_id_passed and ref_id_passed != user_tg.id:
                # check if inviter exists
                inviter = (await session.execute(select(User).where(User.telegram_id == ref_id_passed))).scalars().first()
                if inviter: db_user.referred_by_id = inviter.id

            session.add(db_user)
            await session.commit()
            if is_first and user_tg.id not in config.ADMIN_IDS:
                config.ADMIN_IDS.append(user_tg.id)
                
        is_admin = db_user.is_admin or (user_tg.id in config.ADMIN_IDS)

        start_text = await settings.get_setting("start_message", "به ربات خوش آمدید.")
        
        shop_en = await settings.get_setting("menu_shop", "on")
        wallet_en = await settings.get_setting("menu_wallet", "on")
        free_en = await settings.get_setting("menu_free_config", "on")
        
        keyboard = []
        if shop_en == "on":
            keyboard.append([KeyboardButton("🛒 فروشگاه")])
            
        row_2 = [KeyboardButton("🌐 سرویس‌ها"), KeyboardButton("👤 حساب کاربری")]
        keyboard.append(row_2)
        
        row_3 = []
        if wallet_en == "on": row_3.append(KeyboardButton("💰 کیف پول"))
        row_3.append(KeyboardButton("📞 پشتیبانی"))
        keyboard.append(row_3)
        
        keyboard.append([KeyboardButton("🎁 رفرال گیری")])
        
        if free_en == "on":
            keyboard.append([KeyboardButton("❤️‍🔥 کانفیگ رایگان")])
        
        if is_admin:
            keyboard.append([KeyboardButton("⚙️ پنل مدیریت")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        if is_edit:
            # We can't edit text and attach reply_markup with edit_message_text, so delete and send
            try: await update.callback_query.message.delete()
            except: pass
            await message.chat.send_message(start_text, reply_markup=reply_markup)
        else:
            await message.reply_text(start_text, reply_markup=reply_markup)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref_id = None
    if context.args:
        try: ref_id = int(context.args[0])
        except: pass
    await send_start_menu(update.message, update.effective_user, update, context, ref_id_passed=ref_id)

async def user_dashboard_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if not await check_forced_join(update, context):
        await query.answer("لطفا در کانال ما عضو شوید.", show_alert=True)
        return
        
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "start_menu":
        await send_start_menu(query.message, update.effective_user, update, context, is_edit=True)
        
    elif query.data == "wallet":
        from handlers.wallet import wallet_menu
        await wallet_menu(update, context)
        
    elif query.data == "back_to_free_list":
        await back_to_free_list(update, context)
        
    elif query.data.startswith("free_select_"):
        await free_config_detail_handler(update, context)
        
    elif query.data == "my_referral":
        bot_un = context.bot.username
        link = f"https://t.me/{bot_un}?start={user_id}"
        prc = await settings.get_setting("referral_percent", "10")
        text = f"🎁 **طرح درآمدزایی و تخفیف**\n\nشما با دعوت از دوستان خود از طریق لینک زیر، {prc} درصد از مبلغ تمامی خریدهای آن‌ها را مستقیما به عنوان موجودی قابل برداشت یا خرید دریافت می‌کنید!\n\n🔗 لینک اختصاصی شما:\n`{link}`"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="start_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        
    elif query.data == "my_services":
        async with AsyncSessionLocal() as session:
            # First fetch user DB id
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            db_user = result.scalars().first()
            
            result = await session.execute(select(Service).where(Service.user_id == db_user.id))
            services = result.scalars().all()
            
            keyboard = [[InlineKeyboardButton("🔙 بازگشت", callback_data="start_menu")]]
            text = "🌐 <b>سرویس‌های من</b>\n\n"
            if not services:
                text += "شما هیچ سرویس فعالی ندارید!"
            else:
                for idx, s in enumerate(services, 1):
                    exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                    status = "✅ فعال" if s.status == "ACTIVE" else "❌ غیرفعال"
                    p_name = escape(s.panel_username or 'سرویس متفرقه')
                    text += f"{idx}. پنل/یوزرنیم: {p_name}\n"
                    text += f"وضعیت: {status} | انقضا: {exp}\n"
                    if s.config_link:
                        text += f"لینک: <code>{escape(s.config_link)}</code>\n"
                    text += "➖➖➖➖➖➖\n"
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text: return
    text = msg.text
    if text == "🛒 فروشگاه":
        from handlers.shop import shop_nav
        # Since shop_nav requires a query, we send the base menu directly
        async with AsyncSessionLocal() as session:
            cats = (await session.execute(select(Category).where(Category.parent_id == None))).scalars().all()
            prods = (await session.execute(select(Product).where(Product.category_id == None))).scalars().all()
            
        msg = "🛍 <b>فروشگاه سرویس‌ها</b>\nانتخاب کنید:"
        kb = [[InlineKeyboardButton(f"📁 {escape(c.name)}", callback_data=f"usr_cat_{c.id}")] for c in cats]
        for p in prods: kb.append([InlineKeyboardButton(f"🛒 خرید {escape(p.name)} ({p.price:,.0f}T)", callback_data=f"buyprod_{p.id}")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif text == "💰 کیف پول":
        # Fake a query-like flow for wallet by sending message instead
        from handlers.wallet import wallet_menu
        # We need a small hack since wallet_menu expects a callback_query usually. 
        # But wait, we can just fetch and send:
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.telegram_id == update.effective_user.id))).scalars().first()
            bal = user.wallet_balance if user else 0.0
        msg = f"💰 <b>کیف پول شما</b>\nموجودی فعلی: <code>{bal:,.0f} تومان</code>\n\nبرای شارژ حساب روی دکمه زیر کلیک کنید."
        keyboard = [[InlineKeyboardButton("➕ شارژ حساب", callback_data="wallet_add")], [InlineKeyboardButton("🔙 بازگشت", callback_data="start_menu")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif "حساب کاربری" in text or "حساب من" in text:
        bot_un = context.bot.username
        user_id = update.effective_user.id
        link = f"https://t.me/{bot_un}?start={user_id}"
        import core.settings as _settings
        prc = await _settings.get_setting("referral_percent", "10")
        
        async with AsyncSessionLocal() as session:
            from database.models import Order
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            orders_count = len((await session.execute(select(Order).where(Order.user_id == user_db.id).where(Order.status == 'PAID'))).scalars().all()) if user_db else 0
            referrals_count = len((await session.execute(select(User).where(User.referred_by_id == user_db.id))).scalars().all()) if user_db else 0
            bal = user_db.wallet_balance if user_db else 0
            
        msg = f"""📊 **اطلاعات حساب شما:**

🆔 آیدی: `{user_id}`
💰 موجودی: {bal:,.0f} تومان
📦 تعداد سفارشات موفق: {orders_count}
👥 زیرمجموعه موفق: {referrals_count}

🎁 **طرح درآمدزایی و تخفیف**
شما با دعوت از دوستان خود از طریق لینک زیر، {prc} درصد از مبلغ تمامی خریدهای آن‌ها را دریافت می‌کنید!

🔗 لینک اختصاصی شما:
`{link}`"""
        keyboard = [[InlineKeyboardButton("🧾 تاریخچه تراکنش‌ها و فیش‌های من", callback_data="my_transactions")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif "سرویس‌ها" in text:
        user_id = update.effective_user.id
        async with AsyncSessionLocal() as session:
            from database.models import Order
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            services = (await session.execute(select(Service).where(Service.user_id == user_db.id).order_by(Service.id.desc()))).scalars().all()
            msg = "🌐 <b>سرویس‌های من</b>\n\n"
            keys = []
            if not services: msg += "شما هیچ سرویس فعالی ندارید!"
            else:
                for idx, s in enumerate(services, 1):
                    exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                    status = "✅ فعال" if s.status == "ACTIVE" else "❌ غیرفعال"
                    p_name = escape(s.panel_username or 'سرویس متفرقه')
                    msg += f"{idx}. سرور: {p_name}\n"
                    msg += f"وضعیت: {status} | انقضا: {exp}\n"
                    msg += "➖➖➖➖➖➖\n"
                    
                    # Extract config link (first line that looks like vless:// or vmess://)
                    if s.config_link:
                        link_part = s.config_link.split("\n")[0].strip()
                        if link_part.startswith("vless://") or link_part.startswith("vmess://"):
                            keys.append([InlineKeyboardButton(f"📋 کپی لینک سرور #{idx}", copy_text=CopyTextButton(text=link_part))])
                    
                    # Only show renewal for V2RAY active services
                    if s.status == "ACTIVE":
                        keys.append([InlineKeyboardButton(f"🔄 تمدید سرویس #{idx}", callback_data=f"renew_svc_{s.id}")])
            
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys) if keys else None)
            
    elif "مدیریت" in text:
        from handlers.admin import admin_panel
        await admin_panel(update, context) # Handles Message correctly
        
    elif "پشتیبانی" in text:
        await update.message.reply_text("جهت ارتباط با پشتیبانی روی کلید زیر کلیک کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("شروع تیکت جدید", callback_data="support_new")], [InlineKeyboardButton("تیکت‌های قبلی من", callback_data="my_tickets")]]))

    elif "رفرال" in text:
        bot_un = context.bot.username
        user_id = update.effective_user.id
        link = f"https://t.me/{bot_un}?start={user_id}"
        prc = await settings.get_setting("referral_percent", "10")
        
        async with AsyncSessionLocal() as session:
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            referrals_count = len((await session.execute(select(User).where(User.referred_by_id == user_db.id))).scalars().all()) if user_db else 0
        
        share_text = f"با ما به اینترنت آزاد متصل بشید ❤️\n{link}"
        
        msg = f"""🎁 **طرح دعوت از دوستان**

با دعوت از دوستان خود از طریق لینک زیر، **{prc} درصد** از مبلغ تمامی خریدهای آن‌ها مستقیماً به کیف پول شما اضافه می‌شود!

👥 تعداد زیرمجموعه‌های شما: **{referrals_count}** نفر

🔗 لینک اختصاصی شما:
`{link}`"""
        from urllib.parse import quote
        encoded_text = quote("با ما به اینترنت آزاد متصل بشید ❤️")
        keyboard = [
            [InlineKeyboardButton("📤 ارسال برای دوستان", url=f"https://t.me/share/url?url={link}&text={encoded_text}")],
            [InlineKeyboardButton("📋 کپی لینک", copy_text=CopyTextButton(text=link))]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif "کانفیگ رایگان" in text:
        async with AsyncSessionLocal() as session:
            from database.models import FreeConfig
            configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()))).scalars().all()
            if not configs:
                await update.message.reply_text("در حال حاضر کانفیگ رایگانی در دسترس نیست.")
            else:
                msg = "❤️‍🔥 <b>لیست کانفیگ‌های رایگان فعال</b>\nلطفاً یکی از سرورهای زیر را انتخاب کنید:"
                keys = []
                for c in configs:
                    name = escape(c.title or c.country or f"سرور شماره {c.id}")
                    keys.append([InlineKeyboardButton(f"🌐 {name}", callback_data=f"free_select_{c.id}")])
                
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys))

async def free_config_detail_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    config_id = int(query.data.split("_")[2])
    
    async with AsyncSessionLocal() as session:
        from database.models import FreeConfig
        c = (await session.execute(select(FreeConfig).where(FreeConfig.id == config_id))).scalars().first()
        if not c:
            await query.edit_message_text("❌ این کانفیگ دیگر موجود نیست.")
            return

        config_text = c.config_data
        c_title = escape(c.title or 'بدون نام')
        c_country = escape(c.country or 'نامشخص')
        c_desc = escape(c.description or 'ندارد')
        msg = f"🎁 <b>کانفیگ رایگان: {c_title}</b>\n\nکشور: {c_country}\nتوضیحات: {c_desc}\n\n"
        
        links = [l.strip() for l in config_text.strip().split('\n') if l.strip()]
        is_v2ray = any(l.startswith('vless://') or l.startswith('vmess://') for l in links)
        
        btn_list = []
        if is_v2ray:
            msg += f"لینک/کد:\n<code>{escape(config_text)}</code>"
            if len(config_text) <= 256:
                btn_list.append([InlineKeyboardButton("📋 کپی لینک سرور", copy_text=CopyTextButton(text=config_text))])
        else:
            for i, link in enumerate(links, 1):
                msg += f"🔗 لینک {i}:\n<code>{escape(link)}</code>\n\n"
                if len(link) <= 256:
                    btn_list.append([InlineKeyboardButton(f"📋 کپی لینک {i}", copy_text=CopyTextButton(text=link))])
        
        btn_list.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_free_list")])
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btn_list))

async def back_to_free_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    async with AsyncSessionLocal() as session:
        from database.models import FreeConfig
        configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()))).scalars().all()
        if not configs:
            await query.edit_message_text("در حال حاضر کانفیگ رایگانی در دسترس نیست.")
            return
            
        msg = "❤️‍🔥 <b>لیست کانفیگ‌های رایگان فعال</b>\nلطفاً یکی از سرورهای زیر را انتخاب کنید:"
        keys = []
        for c in configs:
            name = escape(c.title or c.country or f"سرور شماره {c.id}")
            keys.append([InlineKeyboardButton(f"🌐 {name}", callback_data=f"free_select_{c.id}")])
        
        await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keys))



