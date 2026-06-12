import logging
import random
from sqlalchemy.future import select
from datetime import datetime, timedelta
from database.models import AsyncSessionLocal, User, Product, Service, Order, XUIPanel, Category
from core.xui import XUIApi
from core.settings import get_setting, set_setting
from core.config import ADMIN_IDS
from core.v2ray_delivery import (
    allocate_v2ray_server_names,
    apply_remark_to_link,
    build_service_config_link,
    delivery_choice_keyboard,
    format_order_confirm_with_delivery,
)

logger = logging.getLogger(__name__)

def _sanitize_email(email: str) -> str:
    return "".join(c for c in (email or "") if c.isalnum() or c in "-_").strip()

async def provision_order_and_notify(order_id: int, bot, custom_server_name: str = None):
    """
    Called when an order enters PAID status.
    It creates the Service (hitting X-UI if V2RAY),
    saves it to DB, and sends the user an order confirmation DM.
    
    Args:
        order_id: The order ID to provision
        bot: Telegram bot instance
        custom_server_name: Optional custom server name for V2RAY services
    """
    logger.info(f"provision_order_and_notify called: order_id={order_id}, custom_server_name={custom_server_name}")
    
    # Always get serial for random email generation
    # (custom_server_name only affects the display remark, not the panel email)
    server_serial = 0
    serial_needs_increment = False
    try:
        current_serial = int(await get_setting("v2ray_server_serial", "0") or "0")
        server_serial = current_serial + 1
        serial_needs_increment = True
    except ValueError:
        server_serial = 1
        serial_needs_increment = True
    
    async with AsyncSessionLocal() as session:
        order = (await session.execute(select(Order).where(Order.id == order_id))).scalars().first()
        if not order or order.status != "PAID":
            return
            
        user = (await session.execute(select(User).where(User.id == order.user_id))).scalars().first()
        product = (await session.execute(select(Product).where(Product.id == order.product_id))).scalars().first()
        
        if not user or not product:
            return
            
        # Check if service already generated to avoid duplication
        existing = (await session.execute(select(Service).where(Service.config_link.like(f"%#SUB-{order.id}%")))).scalars().first()
        if existing:
            return
            
        svc = Service(user_id=user.id, status="ACTIVE")
        if getattr(product, 'duration_days', None):
            svc.expire_date = datetime.utcnow() + timedelta(days=product.duration_days)
            order.expire_date = svc.expire_date
        
        sub_code = f"#SUB-{order.id}"
        svc.panel_username = sub_code

        # Load category to check if it has a custom delivery message
        category = None
        if product.category_id:
            category = (await session.execute(select(Category).where(Category.id == product.category_id))).scalars().first()

        delivery_note = "جهت تحویل کانفیگ به پشتیبانی پیام دهید."
        if category and category.delivery_msg:
            delivery_note = category.delivery_msg
        elif product.description:
            delivery_note = product.description

        config_link = None
        client_email = ""
        client_uuid = ""
        remark = ""
        inbound_id = product.panel_id or 1
        
        logger.info(f"Provisioning order {order_id}: product={product.name}, type={product.product_type}, panel_id={product.panel_id}")
        
        if product.product_type == 'V2RAY':
            panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
            
            if panel_db:
                logger.info(f"XUI panel found: url={panel_db.url}, username={panel_db.username}")
                client = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                
                # Use custom server name or generate random
                if not client.logged_in and not await client.login():
                    logger.error(f"Failed to login to XUI panel: {client.last_error}")

                # Always generate random email for panel subscription ID
                # Custom name is only used as display remark, not as the email
                max_attempts = 10
                email = None
                for attempt in range(max_attempts):
                    next_email, next_remark = await allocate_v2ray_server_names(serial=server_serial)

                    # Check if email already exists on panel
                    email_exists = False
                    try:
                        if client.logged_in:
                            # Prefer direct links API which is more reliable for existence
                            try:
                                links_for_email = await client.get_client_links(next_email)
                                if links_for_email:
                                    email_exists = True
                            except Exception:
                                # Fallback to scanning clientStats
                                inbounds = await client.list_inbounds()
                                for ib in inbounds:
                                    for cs in ib.get("clientStats", []):
                                        if cs.get("email") == next_email:
                                            email_exists = True
                                            break
                                    if email_exists:
                                        break
                    except Exception as e:
                        logger.warning(f"Could not check existing emails reliably: {e}")

                    if not email_exists:
                        email = next_email
                        remark = next_remark
                        break

                    logger.info(f"Email {next_email} already exists on panel, incrementing serial to {server_serial + 1}")
                    server_serial += 1

                # If still not unique after attempts, fallback to append a short random suffix
                if not email:
                    import secrets
                    rand = secrets.token_hex(3)
                    # Use last generated next_email as base
                    email = f"{next_email}-{rand}"
                    remark = f"@{email}"
                    logger.info(f"Falling back to random suffix, using email {email}")

                # Use custom name as display remark if provided
                if custom_server_name:
                    custom_remark = _sanitize_email(custom_server_name)
                    remark = f"@{custom_remark}"
                    logger.info(f"Using custom server name as remark: {remark} (panel email: {email})")

                client_email = email
                logger.info(f"Server name generated: {email} (serial={server_serial}, remark={remark})")

                total_gb = product.volume_gb or 0
                logger.info(
                    f"Provisioning V2RAY: panel={panel_db.url}, inbound={inbound_id}, "
                    f"name={remark}, email={email}, vol={total_gb}GB"
                )

                # Try to add client, retry with new serial if duplicate email error
                uuid_res = None
                max_add_attempts = 5
                for add_attempt in range(max_add_attempts):
                    uuid_res = await client.add_client(inbound_id, email, total_gb, product.duration_days)
                    if uuid_res:
                        break
                    
                    # Check if error is due to duplicate email
                    err = client.last_error or ""
                    if "duplicate" in err.lower() or "exists" in err.lower() or "already" in err.lower():
                        # Email exists, try next serial
                        server_serial += 1
                        email, remark = await allocate_v2ray_server_names(serial=server_serial)
                        client_email = email
                        logger.info(f"Retrying with new serial {server_serial}, email={email}")
                        if add_attempt < max_add_attempts - 1:
                            continue
                    
                    logger.warning(f"add_client attempt {add_attempt + 1} failed: {client.last_error}")
                
                if uuid_res:
                    client_uuid = uuid_res
                    # Build direct link from THIS inbound specifically
                    direct_link = await client.build_direct_link(inbound_id, uuid_res, remark)
                    if direct_link:
                        config_link = direct_link
                        delivery_note = f"✅ سرور شما با موفقیت ساخته شد!\n\n<b>لینک مستقیم اتصال:</b>\n\n<code>{direct_link}</code>"
                        logger.info(f"V2RAY provisioned OK: {remark}, inbound={inbound_id}, api={client.api_mode}")
                    else:
                        delivery_note = "❌ سرور ساخته شد ولی لینک ساخته نشد. لطفا به پشتیبانی پیام دهید."
                else:
                    err_detail = client.last_error or "نامشخص"
                    inbounds = await client.list_inbounds()
                    ib_ids = [i.get("id") for i in inbounds]
                    delivery_note = (
                        "❌ خطای سیستمی رخ داد و سرور اتوماتیک ساخته نشد!\n"
                        f"جزئیات: <code>{err_detail[:200]}</code>\n"
                        f"Inbound محصول: {inbound_id} | Inboundهای پنل: {ib_ids}\n"
                        "لطفا این فاکتور را برای پشتیبانی ارسال کنید."
                    )
                    logger.error(
                        f"V2RAY provision FAILED order={order.id} inbound={inbound_id} "
                        f"email={email} err={err_detail} panel_inbounds={ib_ids}"
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"⚠️ <b>خطای ساخت V2RAY</b>\nسفارش: #{order.id}\nInbound: {inbound_id}\n"
                                f"خطا: <code>{err_detail[:300]}</code>\nInboundهای پنل: {ib_ids}",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                    await client.close()
            else:
                delivery_note = "❌ ادمین هنوز سرور متصل X-UI را به ربات معرفی نکرده است. لطفا به پشتیبانی پیام دهید."
                  
        if config_link:
            svc.config_link = build_service_config_link(
                config_link,
                sub_code,
                client_email,
                inbound_id,
                client_uuid,
                remark=remark if product.product_type == "V2RAY" else "",
                serial=server_serial if product.product_type == "V2RAY" else 0,
            )
        else:
            svc.config_link = f"{delivery_note}\n\nکد رهگیری: {sub_code}"
        session.add(svc)
        await session.flush()
        svc_id = svc.id
        
        # Referral System
        if user.referred_by_id:
            try:
                inviter = await session.get(User, user.referred_by_id)
                if inviter:
                    ref_percent = int(await get_setting("referral_percent", "10"))
                    commission = order.amount * (ref_percent / 100)
                    if commission > 0:
                        inviter.wallet_balance += commission
                        logger.info(f"Referral reward: {commission} given to user {inviter.id} for order {order.id}")
                        
                        try:
                            msg_text = (
                                f"🎁 <b>تبریک! هدیه معرفی دوستان</b>\n\n"
                                f"دوست شما یک خرید موفق انجام داد و مبلغ <b>{commission:,.0f} تومان</b> "
                                f"پورسانت ({ref_percent}٪) به کیف پول شما اضافه شد! ✨"
                            )
                            await bot.send_message(inviter.telegram_id, msg_text, parse_mode="HTML")
                        except Exception as ne:
                            logger.error(f"Failed to notify inviter {inviter.telegram_id}: {ne}")
            except Exception as re:
                logger.error(f"Referral system error: {re}")
        
        await session.commit()
        
        # Increment serial AFTER session commit to avoid DB lock
        if serial_needs_increment:
            from core.settings import set_setting
            try:
                await set_setting("v2ray_server_serial", str(server_serial))
            except Exception as se:
                logger.error(f"Failed to increment server serial: {se}")
        
        try:
            from html import escape
            raw_msg = await get_setting("order_confirm_msg", "✅ سفارش شما تایید شد.\n\nکد اشتراک: {sub_code}\nمحصول: {product_name}")
            p_name = escape(str(product.name if product else 'محصول'))
            text = raw_msg.replace("{sub_code}", f"<code>{sub_code}</code>").replace("{product_name}", f"<b>{p_name}</b>")
            
            if config_link and product.product_type == 'V2RAY':
                cat_del_msg = category.delivery_msg if (category and category.delivery_msg) else ""
                final_text = format_order_confirm_with_delivery(
                    text, sub_code, str(product.name), cat_del_msg
                )
                await bot.send_message(
                    user.telegram_id,
                    final_text,
                    parse_mode="HTML",
                    reply_markup=delivery_choice_keyboard(svc_id),
                )
            elif config_link:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
                keys = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 کپی لینک سرور", copy_text=CopyTextButton(text=config_link))]
                ])
                cat_del_msg = category.delivery_msg if (category and category.delivery_msg) else ""
                if cat_del_msg:
                    final_text = f"{text}\n\n➖➖➖➖➖\n📦 <b>تحویل سرویس:</b>\n\n{cat_del_msg}\n\n<b>لینک مستقیم (کپی کنید):</b>\n\n<code>{config_link}</code>"
                else:
                    final_text = f"{text}\n\n➖➖➖➖➖\n📦 <b>تحویل سرویس:</b>\n\n✅ سرور ساخته شد!\n\n<b>لینک مستقیم (کپی کنید):</b>\n\n<code>{config_link}</code>"
                await bot.send_message(user.telegram_id, final_text, parse_mode="HTML", reply_markup=keys)
            else:
                final_text = f"{text}\n\n➖➖➖➖➖\n📦 <b>تحویل سرویس:</b>\n\n{delivery_note}"
                await bot.send_message(user.telegram_id, final_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending confirm: {e}")
