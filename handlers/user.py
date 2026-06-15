from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, CopyTextButton, InputFile
from telegram.ext import ContextTypes
from sqlalchemy.future import select
from sqlalchemy import func
from database.models import AsyncSessionLocal, User, Category, Product, Service, Order, XUIPanel, TestServerAssignment
from core.xui import XUIApi
import core.config as config
import core.settings as settings
from core.utils import check_forced_join
from core.v2ray_delivery import (
    apply_remark_to_link,
    copy_button_row,
    extract_direct_link,
    extract_sub_code,
    fetch_subscription_configs,
    format_config_item_text,
    make_qr_bytes,
    parse_service_meta,
    safe_copy_button,
    send_individual_configs_delivery,
    send_subscription_delivery,
)
from html import escape
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

async def handle_v2ray_delivery_action(update: Update, context: ContextTypes.DEFAULT_TYPE, service: Service, action: str):
    """Handle service delivery actions from text buttons (sub/cfg/server)."""
    await update.message.chat.send_message("⏳ در حال آماده‌سازی...")

    async with AsyncSessionLocal() as session:
        svc = await session.get(Service, service.id)
        if not svc:
            await update.message.reply_text("❌ سرویس یافت نشد.")
            return

        # Get user for product name
        user_db = (await session.execute(select(User).where(User.telegram_id == update.effective_user.id))).scalars().first()
        product_name = "سرویس V2RAY"
        if svc.panel_username and "#SUB-" in svc.panel_username:
            try:
                oid = int(svc.panel_username.replace("#SUB-", ""))
                order = (await session.execute(select(Order).where(Order.id == oid))).scalars().first()
                if order and order.product_id:
                    prod = (await session.execute(select(Product).where(Product.id == order.product_id))).scalars().first()
                    if prod:
                        product_name = prod.name
            except Exception:
                pass

        sub_code = extract_sub_code(svc.panel_username)
        direct = extract_direct_link(svc.config_link)
        meta = parse_service_meta(svc.config_link)
        client_email = meta.get("email", "")

        if not client_email:
            # Try to get email from remark if available
            remark = meta.get("remark", "")
            if remark:
                # Remove @ prefix if present
                client_email = remark.lstrip("@")
            # Don't extract from direct link to avoid getting UUID instead of email

        panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()

        if not panel_db:
            await update.message.reply_text("❌ پنل متصل نیست. به پشتیبانی پیام دهید.")
            return

        sub_path = await settings.get_setting("xui_sub_path", "/sub/")
        xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
        sub_id = client_email
        display_remark = meta.get("remark", "")

        exp_date = svc.expire_date.strftime("%Y-%m-%d") if svc.expire_date else "نامحدود"
        days_left = max(0, (svc.expire_date - datetime.now()).days) if svc.expire_date else "نامحدود"
        usage_str = ""

        try:
            client_stats = await xui.get_all_client_stats()
            if client_stats and client_email:
                for cs in client_stats:
                    if cs.get("email") == client_email:
                        total = cs.get("total", 0) // (1024**3)
                        used = (cs.get("up", 0) + cs.get("down", 0)) // (1024**3)
                        usage_str = f"📊 استفاده: {used}/{total}GB | ⏳ {days_left} روز" if total > 0 else f"📊 مصرف شده: {used}GB | ⏳ {days_left} روز"
                        break
        except Exception:
            pass

        chat_id = update.effective_chat.id

        if action == "server":
            if direct:
                qr = make_qr_bytes(direct)
                caption = f"🔗 <b>لینک سرور</b>\n\n📅 انقضا: {exp_date}\n{usage_str}\n\n<code>{direct}</code>\n\nمی‌توانید QR را اسکن کنید یا لینک را کپی کنید"
                await context.bot.send_photo(
                    chat_id,
                    photo=InputFile(qr, filename="qr.png"),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(copy_button_row(direct, "📋 کپی لینک")),
                )
            await xui.close()
            return

        if action == "sub":
            sub_url = xui.build_subscription_url(sub_id, sub_path)
            qr = make_qr_bytes(sub_url)
            caption = f"🔗 <b>لینک ساب</b>\n\n📅 انقضا: {exp_date}\n{usage_str}\n\n<code>{sub_url}</code>\n\nمی‌توانید QR را اسکن کنید یا لینک ساب را کپی کنید"
            await context.bot.send_photo(
                chat_id,
                photo=InputFile(qr, filename="qr.png"),
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(copy_button_row(sub_url, "📋 کپی لینک ساب")),
            )
            await xui.close()
            return

        if action == "cfg":
            links = []
            if client_email:
                sub_url = xui.build_subscription_url(client_email, sub_path)
                links = await fetch_subscription_configs(sub_url)
            if not links and direct:
                links = [direct]

            if display_remark:
                links = [apply_remark_to_link(l, display_remark) for l in links]
            if not links and svc.config_link:
                for line in svc.config_link.split("\n"):
                    line = line.strip()
                    if line.startswith(("vless://", "vmess://", "trojan://", "ss://")):
                        links.append(line)

            await xui.close()

            try:
                usage_info = f"📅 انقضا: {exp_date}"
                if usage_str:
                    usage_info += f"\n{usage_str}"
                await send_individual_configs_delivery(
                    context.bot, chat_id,
                    links=links, sub_code=sub_code, product_name=product_name,
                    usage_info=usage_info,
                )
            except Exception as e:
                logger.error(f"Config delivery failed: {e}")
                await update.message.reply_text("❌ خطا در ارسال کانفیگ‌ها. دوباره تلاش کنید.")
            return

        await xui.close()


async def _resolve_service_for_delivery(session, service_id: int, telegram_id: int):
    user_db = (await session.execute(select(User).where(User.telegram_id == telegram_id))).scalars().first()
    if not user_db:
        return None, None, None
    svc = (await session.execute(
        select(Service).where(Service.id == service_id, Service.user_id == user_db.id)
    )).scalars().first()
    if not svc:
        return None, None, None
    product_name = "سرویس V2RAY"
    if svc.panel_username and "#SUB-" in svc.panel_username:
        try:
            oid = int(svc.panel_username.replace("#SUB-", ""))
            order = (await session.execute(select(Order).where(Order.id == oid))).scalars().first()
            if order and order.product_id:
                prod = (await session.execute(select(Product).where(Product.id == order.product_id))).scalars().first()
                if prod:
                    product_name = prod.name
        except Exception:
            pass
    return svc, product_name, user_db


async def handle_v2ray_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send subscription QR/link or individual config QRs."""
    query = update.callback_query
    if not await check_forced_join(update, context):
        await query.answer("لطفا در کانال عضو شوید.", show_alert=True)
        return
    await query.answer("در حال آماده‌سازی...")

    parts = query.data.split("_")
    action = parts[1]  # server, cfg, or sub
    svc_id = int(parts[-1])
    chat_id = update.effective_chat.id

    async with AsyncSessionLocal() as session:
        svc, product_name, _ = await _resolve_service_for_delivery(session, svc_id, update.effective_user.id)
        if not svc:
            await query.message.reply_text("❌ سرویس یافت نشد.")
            return

        sub_code = extract_sub_code(svc.panel_username)
        direct = extract_direct_link(svc.config_link)
        meta = parse_service_meta(svc.config_link)
        client_email = meta.get("email", "")

        # If no email in meta, try to extract it from remark only (not from direct link)
        if not client_email:
            # Try to get email from remark if available
            remark = meta.get("remark", "")
            if remark:
                # Remove @ prefix if present
                client_email = remark.lstrip("@")
            # Don't extract from direct link to avoid getting UUID instead of email

        panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()

        if not panel_db:
            await query.message.reply_text("❌ پنل متصل نیست. به پشتیبانی پیام دهید.")
            return

        sub_path = await settings.get_setting("xui_sub_path", "/sub/")
        xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
        sub_id = client_email
        display_remark = meta.get("remark", "")

        exp_date = svc.expire_date.strftime("%Y-%m-%d") if svc.expire_date else "نامحدود"
        days_left = max(0, (svc.expire_date - datetime.now()).days) if svc.expire_date else "نامحدود"
        usage_str = ""

        try:
            client_stats = await xui.get_all_client_stats()
            if client_stats and client_email:
                for cs in client_stats:
                    if cs.get("email") == client_email:
                        total = cs.get("total", 0) // (1024**3)
                        used = (cs.get("up", 0) + cs.get("down", 0)) // (1024**3)
                        usage_str = f"📊 استفاده: {used}/{total}GB | ⏳ {days_left} روز" if total > 0 else f"📊 مصرف شده: {used}GB | ⏳ {days_left} روز"
                        break
        except Exception:
            pass

        if action == "server":
            if direct:
                qr = make_qr_bytes(direct)
                caption = f"🔗 <b>لینک سرور</b>\n\n📅 انقضا: {exp_date}\n{usage_str}\n\n<code>{direct}</code>\n\nمی‌توانید QR را اسکن کنید یا لینک را کپی کنید"
                await context.bot.send_photo(
                    chat_id,
                    photo=InputFile(qr, filename="qr.png"),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(copy_button_row(direct, "📋 کپی لینک")),
                )
            await xui.close()
            return

        if action == "sub":
            sub_url = xui.build_subscription_url(sub_id, sub_path)
            qr = make_qr_bytes(sub_url)
            caption = f"🔗 <b>لینک ساب</b>\n\n📅 انقضا: {exp_date}\n{usage_str}\n\n<code>{sub_url}</code>\n\nمی‌توانید QR را اسکن کنید یا لینک ساب را کپی کنید"
            await context.bot.send_photo(
                chat_id,
                photo=InputFile(qr, filename="qr.png"),
                caption=caption,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(copy_button_row(sub_url, "📋 کپی لینک ساب")),
            )
            await xui.close()
            return

        links = []
        if sub_id:
            sub_url = xui.build_subscription_url(sub_id, sub_path)
            links = await fetch_subscription_configs(sub_url)
        if not links and direct:
            links = [direct]

        if display_remark:
            links = [apply_remark_to_link(l, display_remark) for l in links]
        if not links and svc.config_link:
            for line in svc.config_link.split("\n"):
                line = line.strip()
                if line.startswith(("vless://", "vmess://", "trojan://", "ss://")):
                    links.append(line)

        await xui.close()

        try:
            usage_info = f"📅 انقضا: {exp_date}"
            if usage_str:
                usage_info += f"\n{usage_str}"
            await send_individual_configs_delivery(
                context.bot, chat_id,
                links=links, sub_code=sub_code, product_name=product_name,
                usage_info=usage_info,
            )
        except Exception as e:
            logger.error(f"Config delivery failed: {e}")
            await query.message.reply_text("❌ خطا در ارسال کانفیگ‌ها. دوباره تلاش کنید.")


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

        # Modern styled start text
        start_text = await settings.get_setting("start_message", "به ربات خوش آمدید.")
        composed_caption = f"<b>{start_text}</b>"
        
        shop_en = await settings.get_setting("menu_shop", "on")
        wallet_en = await settings.get_setting("menu_wallet", "on")
        free_en = await settings.get_setting("menu_free_config", "on")
        renew_en = await settings.get_setting("menu_renew", "on")
        test_en = await settings.get_setting("menu_test_server", "off")
        
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
        
        if test_en == "on":
            keyboard.append([KeyboardButton("🧪 سرور تست")])
        
        if is_admin:
            keyboard.append([KeyboardButton("⚙️ پنل مدیریت")])
            
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        # Send decorative background image if configured (glass-style header)
        bg_url = await settings.get_setting("menu_background_url", "")
        try:
            if bg_url:
                try:
                    await message.chat.send_photo(photo=bg_url, caption=composed_caption, parse_mode="HTML")
                except Exception:
                    try:
                        await message.chat.send_photo(photo=bg_url)
                    except Exception:
                        await message.chat.send_message(composed_caption, parse_mode="HTML")
                await message.chat.send_message("برای ادامه از دکمه‌های زیر استفاده کنید:", reply_markup=reply_markup)
                return
        except Exception:
            pass

        if is_edit:
            # We can't edit text and attach reply_markup with edit_message_text, so delete and send
            try: await update.callback_query.message.delete()
            except: pass
            await message.chat.send_message(composed_caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await message.reply_text(composed_caption, reply_markup=reply_markup, parse_mode="HTML")

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
            result = await session.execute(select(User).where(User.telegram_id == user_id))
            db_user = result.scalars().first()

            result = await session.execute(select(Service).where(Service.user_id == db_user.id).order_by(Service.id.desc()))
            services = result.scalars().all()

            if not services:
                text = "🌐 <b>سرویس‌های من</b>\n\nشما هیچ سرویس فعالی ندارید!"
                kb = [[KeyboardButton("🔙 بازگشت")]]
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
                    parse_mode="HTML"
                )
                return

            panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
            client_stats = []
            if panel_db:
                xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                try:
                    client_stats = await xui.get_all_client_stats()
                except Exception:
                    pass

            # Build text display with service cards
            text = "🌐 <b>سرویس‌های من</b>\n\n"
            keyboard = []

            for idx, s in enumerate(services, 1):
                exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                status_emoji = "✅" if s.status == "ACTIVE" else "❌"
                svc_meta = parse_service_meta(s.config_link)
                raw_name = svc_meta.get("remark") or s.panel_username or "سرویس متفرقه"
                p_name = escape(f"اشتراک {idx}: {raw_name}")
                email = svc_meta.get("email", "")

                usage_str = ""
                if client_stats and email:
                    for cs in client_stats:
                        if cs.get("email") == email:
                            total = cs.get("total", 0) // (1024**3)
                            used = (cs.get("up", 0) + cs.get("down", 0)) // (1024**3)
                            usage_str = f"📊 استفاده: {used}/{total}GB" if total > 0 else f"📊 مصرف شده: {used}GB"
                            break

                days_left = "نامحدود"
                if s.expire_date:
                    days_left_val = max(0, (s.expire_date - datetime.now()).days)
                    days_left = str(days_left_val)

                # Glass-style card
                text += f"┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                text += f"🔹 <b>{p_name}</b>    {status_emoji}\n"
                text += f"📅 انقضا: {exp}\n"
                if usage_str:
                    text += f"{usage_str}  |  ⏳ {days_left} روز\n"
                else:
                    text += f"⏳ {days_left} روز\n"
                text += f"┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"

                # Add buttons only for active services
                if s.status == "ACTIVE":
                    keyboard.append([
                        KeyboardButton(f"🔗 ساب #{idx}"),
                        KeyboardButton(f"🎯 کانفیگ #{idx}"),
                        KeyboardButton(f"🔁 تمدید #{idx}")
                    ])

            keyboard.append([KeyboardButton("🔙 بازگشت")])

            # Delete and resend with ReplyKeyboardMarkup
            try:
                await query.message.delete()
            except:
                pass

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text,
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
                parse_mode="HTML"
            )

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text: return
    text = msg.text
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    # Handle service action buttons first (e.g., "🔗 ساب #1", "🎯 کانفیگ #1", "🔁 تمدید #1")
    if text.startswith("🔗 ساب #") or text.startswith("🎯 کانفیگ #") or text.startswith("🔁 تمدید #"):
        try:
            svc_idx = int(text.split("#")[1])
            async with AsyncSessionLocal() as session:
                user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
                services = (await session.execute(select(Service).where(Service.user_id == user_db.id).order_by(Service.id.desc()))).scalars().all()

                if svc_idx <= 0 or svc_idx > len(services):
                    await update.message.reply_text("❌ سرویس نامعتبر")
                    return

                service = services[svc_idx - 1]

                if text.startswith("🔗 ساب"):
                    await handle_v2ray_delivery_action(update, context, service, "sub")
                elif text.startswith("🎯 کانفیگ"):
                    await handle_v2ray_delivery_action(update, context, service, "cfg")
                elif text.startswith("🔁 تمدید"):
                    await update.message.reply_text(
                        "برای تمدید سرویس، از دکمه زیر استفاده کنید:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 تمدید سرویس", callback_data=f"renew_svc_{service.id}")]
                        ])
                    )
        except Exception as e:
            logger.error(f"Error parsing service button: {e}")
            await update.message.reply_text("❌ خطای پردازش")
        return

    if text == "🔙 بازگشت":
        await send_start_menu(update.message, update.effective_user, update, context)
        return

    if text == "🛒 فروشگاه":
        shop_en = await settings.get_setting("menu_shop", "on")
        if shop_en != "on":
            await update.message.reply_text("❌ فروشگاه در حال حاضر بسته است.")
            return
        # shop_nav needs callback_query; build menu inline
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

        if text == "🔙 بازگشت":
            await send_start_menu(update.message, update.effective_user, update, context)
            return

        # Display services
        async with AsyncSessionLocal() as session:
            from database.models import Order
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            services = (await session.execute(select(Service).where(Service.user_id == user_db.id).order_by(Service.id.desc()))).scalars().all()

            panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
            client_stats = []
            if panel_db:
                xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                try:
                    client_stats = await xui.get_all_client_stats()
                except Exception:
                    pass

            msg = "🌐 <b>سرویس‌های من</b>\n\n"
            keyboard = []

            if not services:
                msg += "شما هیچ سرویس فعالی ندارید!"
            else:
                for idx, s in enumerate(services, 1):
                    exp = s.expire_date.strftime("%Y-%m-%d") if s.expire_date else "نامحدود"
                    status_emoji = "✅" if s.status == "ACTIVE" else "❌"
                    svc_meta = parse_service_meta(s.config_link)
                    p_name = escape(svc_meta.get("remark") or s.panel_username or "سرویس متفرقه")
                    email = svc_meta.get("email", "")

                    usage_str = ""
                    if client_stats and email:
                        for cs in client_stats:
                            if cs.get("email") == email:
                                total = cs.get("total", 0) // (1024**3)
                                used = (cs.get("up", 0) + cs.get("down", 0)) // (1024**3)
                                usage_str = f"📊 استفاده: {used}/{total}GB" if total > 0 else f"📊 مصرف شده: {used}GB"
                                break

                    days_left = "نامحدود"
                    if s.expire_date:
                        days_left_val = max(0, (s.expire_date - datetime.now()).days)
                        days_left = str(days_left_val)

                    # Glass-style card per service
                    msg += "┏━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    msg += f"🔹 <b>{p_name}</b>    {status_emoji}\n"
                    msg += f"📅 انقضا: {exp}\n"
                    if usage_str:
                        msg += f"{usage_str}  |  ⏳ {days_left} روز\n"
                    else:
                        msg += f"⏳ {days_left} روز\n"
                    msg += "┗━━━━━━━━━━━━━━━━━━━━━━━━┛\n"

                    if s.status == "ACTIVE":
                        keyboard.append([
                            KeyboardButton(f"🔗 ساب #{idx}"),
                            KeyboardButton(f"🎯 کانفیگ #{idx}"),
                            KeyboardButton(f"🔁 تمدید #{idx}")
                        ])

            keyboard.append([KeyboardButton("🔙 بازگشت")])
            await update.message.reply_text(msg, parse_mode="HTML", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
            
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
        btn = safe_copy_button(link, "📋 کپی لینک")
        keyboard = [
            [InlineKeyboardButton("📤 ارسال برای دوستان", url=f"https://t.me/share/url?url={link}&text={encoded_text}")],
        ]
        if btn:
            keyboard.append([btn])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif text == "🧪 سرور تست":
        test_en = await settings.get_setting("menu_test_server", "off")
        if test_en != "on":
            await update.message.reply_text("❌ سرور تست در حال حاضر غیرفعال است.")
            return
        user_id = update.effective_user.id
        async with AsyncSessionLocal() as session:
            user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
            # Check one-per-user
            existing = (await session.execute(select(TestServerAssignment).where(TestServerAssignment.user_id == user_db.id))).scalars().first()
            if existing:
                await update.message.reply_text("شما قبلاً سرور تست دریافت کرده‌اید.")
                return

            base = await settings.get_setting("test_server_base_name", "test")
            vol = float(await settings.get_setting("test_server_volume_gb", "1"))
            dur = int(await settings.get_setting("test_server_duration_days", "1"))
            inb = int(await settings.get_setting("test_server_inbound_id", "1"))

            like_pattern = f"{base}%"
            cnt = (await session.execute(select(func.count(TestServerAssignment.id)).where(TestServerAssignment.server_name.like(like_pattern)))).scalar() or 0
            seq = cnt + 1
            server_name = f"{base}{seq}"
            expire_dt = datetime.utcnow() + timedelta(days=dur)

            assign = TestServerAssignment(user_id=user_db.id, template_id=None, server_name=server_name, panel_id=inb, expire_date=expire_dt)
            session.add(assign)
            svc = Service(user_id=user_db.id, config_link=None, panel_username=server_name, status="ACTIVE", expire_date=expire_dt)
            session.add(svc)
            await session.commit()

        try:
            # Prefer XUI panel provisioning (XUIApi imported at module level)
            panel_db = None
            async with AsyncSessionLocal() as session:
                panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
            cfg = None
            links = []
            panel_display_name = server_name
            client_uuid = None
            sub_id = None
            if panel_db:
                xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                client_uuid = await xui.add_client(inb, server_name, total_gb=vol, expire_days=dur)
                if client_uuid:
                    links = await xui.get_client_links(server_name)
                    if links:
                        cfg = links[0]
                    else:
                        sub_id = await xui.get_client_subscription_id(inb, server_name)
                        sub_path = await settings.get_setting('xui_sub_path', '/sub/')
                        if sub_id:
                            cfg = xui.build_subscription_url(sub_id, sub_path)
                        else:
                            cfg = await xui.build_direct_link(inb, client_uuid, server_name)

                    # Derive panel display name
                    try:
                        inbound = await xui.get_inbound(inb)
                        client_entries = []
                        if inbound:
                            if isinstance(inbound.get('clients'), list):
                                client_entries = inbound.get('clients')
                            else:
                                settings_raw = inbound.get('settings')
                                if isinstance(settings_raw, str):
                                    import json
                                    try:
                                        settings_js = json.loads(settings_raw)
                                        client_entries = settings_js.get('clients') or []
                                    except Exception:
                                        client_entries = []
                        for c in client_entries:
                            if str(c.get('id')) == str(client_uuid) or str(c.get('email')) == str(server_name) or str(c.get('subId')) == str(server_name):
                                panel_display_name = c.get('email') or c.get('subId') or c.get('remark') or panel_display_name
                                break
                    except Exception:
                        pass

                await xui.close()
            if not cfg:
                from services.vpn_panel import vpn_panel
                cfg = await vpn_panel.create_user(server_name, data_limit=vol, expire_days=dur)
            async with AsyncSessionLocal() as session:
                s = (await session.execute(select(Service).where(Service.user_id == user_db.id).order_by(Service.id.desc()))).scalars().first()
                if s:
                    s.config_link = cfg
                    s.panel_username = panel_display_name
                    await session.commit()

            # Deliver to user similar to shop servers
            try:
                from core.v2ray_delivery import send_individual_configs_delivery, send_subscription_delivery, fetch_subscription_configs, make_qr_bytes, format_config_item_text, safe_copy_button
                sub_code = panel_display_name or server_name
                product_name = panel_display_name or server_name
                usage_info = f"مدت: {dur} روز\nحجم: {vol} GB"

                if cfg and isinstance(cfg, str) and cfg.startswith('http') and '/sub/' in cfg:
                    await send_subscription_delivery(context.bot, update.effective_chat.id, sub_url=cfg, sub_code=sub_code, product_name=product_name)
                else:
                    # use any links we already retrieved from the panel; if none, try fetch from cfg
                    if not links and cfg and isinstance(cfg, str) and cfg.startswith('http'):
                        links = await fetch_subscription_configs(cfg)
                    if links:
                        await send_individual_configs_delivery(context.bot, update.effective_chat.id, links=links, sub_code=sub_code, product_name=product_name, usage_info=usage_info)
                    else:
                        if cfg:
                            qr = make_qr_bytes(cfg)
                            caption = format_config_item_text(1,1,cfg,product_name,usage_info)
                            btn = safe_copy_button(cfg, "📋 کپی لینک")
                            kb = InlineKeyboardMarkup([[btn]]) if btn else None
                            await context.bot.send_photo(update.effective_chat.id, photo=qr, caption=caption, parse_mode='HTML', reply_markup=kb)
                        else:
                            await context.bot.send_message(update.effective_chat.id, f"🎁 سرور تست برای شما فعال شد: <code>{product_name}</code>\n\n{usage_info}", parse_mode='HTML')
            except Exception as e:
                logger.exception(f"Delivery failed: {e}")

        except Exception as e:
            logger.exception(f"Provisioning test server failed: {e}")
            cfg = None

        await update.message.reply_text(f"✅ سرور تست برای شما فعال شد: <code>{server_name}</code>", parse_mode="HTML")
        if cfg:
            await update.message.reply_text(f"لینک کانفیگ: {cfg}")
        return

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
        if is_v2ray and len(links) == 1:
            link = links[0]
            caption = format_config_item_text(1, 1, link, c_title)
            btn_list = copy_button_row(link, "📋 کپی لینک")
            btn_list.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_free_list")])
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_photo(
                query.message.chat_id,
                photo=make_qr_bytes(link),
                caption=f"🎁 <b>کانفیگ رایگان: {c_title}</b>\n\nکشور: {c_country}\n\n{caption}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(btn_list),
            )
            return
        if is_v2ray:
            msg += f"لینک/کد:\n<code>{escape(config_text)}</code>"
            btn = safe_copy_button(config_text, "📋 کپی لینک سرور")
            if btn:
                btn_list.append([btn])
        else:
            for i, link in enumerate(links, 1):
                msg += f"🔗 لینک {i}:\n<code>{escape(link)}</code>\n\n"
                btn = safe_copy_button(link, f"📋 کپی لینک {i}")
                if btn:
                    btn_list.append([btn])
        
        btn_list.append([InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_free_list")])
        try:
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btn_list))
        except Exception as e:
            if "Message is not modified" not in str(e):
                raise e

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



