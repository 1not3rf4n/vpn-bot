from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CopyTextButton
from telegram.ext import ContextTypes
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Category, Product, Service
import core.config as config
import core.settings as settings
from core.utils import check_forced_join

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
        
        keyboard.append([KeyboardButton("🎁 دعوت از دوستان")])
        
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
        await query.answer("لطفا در کانال حامی عضو شوید.", show_alert=True)
        return
        
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "start_menu":
        await send_start_menu(query.message, update.effective_user, update, context, is_edit=True)
        
    elif query.data == "wallet":
        from handlers.wallet import wallet_menu
        await wallet_menu(update, context)
        
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
            text = "🌐 **سرویس‌های من**\n\n"
            if not services:
                text += "شما هیچ سرویس فعالی ندارید!"
            else:
                for idx, s in enumerate(services, 1):
                    exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                    status = "✅ فعال" if s.status == "ACTIVE" else "❌ غیرفعال"
                    text += f"{idx}. پنل/یوزرنیم: {s.panel_username or 'سرویس متفرقه'}\n"
                    text += f"وضعیت: {status} | انقضا: {exp}\n"
                    if s.config_link:
                        text += f"لینک: `{s.config_link}`\n"
                    text += "➖➖➖➖➖➖\n"
            
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
            
        msg = "🛍 **فروشگاه سرویس‌ها**\nانتخاب کنید:"
        kb = [[InlineKeyboardButton(f"📁 {c.name}", callback_data=f"usr_cat_{c.id}")] for c in cats]
        for p in prods: kb.append([InlineKeyboardButton(f"🛒 خرید {p.name} ({p.price}T)", callback_data=f"buyprod_{p.id}")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif text == "💰 کیف پول":
        # Fake a query-like flow for wallet by sending message instead
        from handlers.wallet import wallet_menu
        # We need a small hack since wallet_menu expects a callback_query usually. 
        # But wait, we can just fetch and send:
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(User).where(User.telegram_id == update.effective_user.id))).scalars().first()
            bal = user.wallet_balance if user else 0.0
        msg = f"💰 **کیف پول شما**\nموجودی فعلی: `{bal:,.0f} تومان`\n\nبرای شارژ حساب روی دکمه زیر کلیک کنید."
        keyboard = [[InlineKeyboardButton("➕ شارژ حساب", callback_data="wallet_add")], [InlineKeyboardButton("🔙 بازگشت", callback_data="start_menu")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif "حساب کاربری" in text or "حساب من" in text:
        bot_un = context.bot.username
        user_id = update.effective_user.id
        link = f"https://t.me/{bot_un}?start={user_id}"
        import core.settings as settings
        prc = await settings.get_setting("referral_percent", "10")
        
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
            msg = "🌐 **سرویس‌های من**\n\n"
            keys = []
            if not services: msg += "شما هیچ سرویس فعالی ندارید!"
            else:
                for idx, s in enumerate(services, 1):
                    exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                    status = "✅ فعال" if s.status == "ACTIVE" else "❌ غیرفعال"
                    msg += f"{idx}. سرور: {s.panel_username or 'سرویس متفرقه'}\n"
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
            
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keys) if keys else None)
            
    elif "مدیریت" in text:
        from handlers.admin import admin_panel
        await admin_panel(update, context) # Handles Message correctly
        
    elif "پشتیبانی" in text:
        await update.message.reply_text("جهت ارتباط با پشتیبانی روی کلید زیر کلیک کنید:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("شروع تیکت جدید", callback_data="support_new")], [InlineKeyboardButton("تیکت‌های قبلی من", callback_data="my_tickets")]]))

    elif "دعوت از دوستان" in text:
        bot_un = context.bot.username
        user_id = update.effective_user.id
        link = f"https://t.me/{bot_un}?start={user_id}"
        prc = await settings.get_setting("referral_percent", "10")
        
        async with AsyncSessionLocal() as session:
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            referrals_count = len((await session.execute(select(User).where(User.referred_by_id == user_db.id))).scalars().all()) if user_db else 0
        
        share_text = f"سلام! از این ربات عالی VPN استفاده کن 👇\n{link}"
        
        msg = f"""🎁 **طرح دعوت از دوستان**

با دعوت از دوستان خود از طریق لینک زیر، **{prc} درصد** از مبلغ تمامی خریدهای آن‌ها مستقیماً به کیف پول شما اضافه می‌شود!

👥 تعداد زیرمجموعه‌های شما: **{referrals_count}** نفر

🔗 لینک اختصاصی شما:
`{link}`"""
        keyboard = [
            [InlineKeyboardButton("📤 ارسال برای دوستان", url=f"https://t.me/share/url?url={link}&text=سلام!+از+این+ربات+عالی+VPN+استفاده+کن+👇")],
            [InlineKeyboardButton("📋 کپی لینک", copy_text=CopyTextButton(text=link))]
        ]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif "کانفیگ رایگان" in text:
        async with AsyncSessionLocal() as session:
            from database.models import FreeConfig
            configs = (await session.execute(select(FreeConfig).order_by(FreeConfig.id.desc()).limit(1))).scalars().all()
            if not configs:
                await update.message.reply_text("در حال حاضر کانفیگ رایگانی در دسترس نیست.")
            else:
                c = configs[0]
                msg = f"🎁 **کانفیگ رایگان (تست)**\n\nکشور: {c.country}\nتوضیحات: {c.description}\n\nلینک/کد:\n`{c.config_data}`"
                keys = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 کپی لینک سرور", copy_text=CopyTextButton(text=c.config_data))]
                ])
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keys)
