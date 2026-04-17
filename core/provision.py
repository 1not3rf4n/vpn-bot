import logging
from sqlalchemy.future import select
from datetime import datetime, timedelta
from database.models import AsyncSessionLocal, User, Product, Service, Order, XUIPanel
from core.xui import XUIApi
from core.settings import get_setting

logger = logging.getLogger(__name__)

async def provision_order_and_notify(order_id: int, bot):
    """
    Called when an order enters PAID status.
    It creates the Service (hitting X-UI if V2RAY),
    saves it to DB, and sends the user an order confirmation DM.
    """
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
        
        delivery_note = product.description or "جهت تحویل کانفیگ به پشتیبانی پیام دهید."
        config_link = None
        
        logger.info(f"Provisioning order {order_id}: product={product.name}, type={product.product_type}, panel_id={product.panel_id}")
        
        if product.product_type == 'V2RAY':
            panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
            if panel_db:
                client = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                inbound_id = product.panel_id or 1
                
                # Build client name: duration_volume_username_orderID (unique)
                dur_str = f"{product.duration_days}D"
                vol_str = f"{product.volume_gb}GB" if product.volume_gb > 0 else "Unlim"
                uname = user.username or str(user.telegram_id)
                email = f"{dur_str}_{vol_str}_{uname}_{order.id}"
                
                # Remark for the link (shown in V2ray apps)
                remark = f"{dur_str}_{vol_str}_{uname}"
                
                total_gb = product.volume_gb or 0
                logger.info(f"Provisioning V2RAY: panel={panel_db.url}, inbound={inbound_id}, email={email}, vol={total_gb}GB")
                
                uuid_res = await client.add_client(inbound_id, email, total_gb, product.duration_days)
                if uuid_res:
                    direct_link = await client.build_direct_link(inbound_id, uuid_res, remark)
                    if direct_link:
                        config_link = direct_link
                        delivery_note = f"✅ سرور شما با موفقیت ساخته شد!\n\n<b>لینک مستقیم اتصال:</b>\n\n<code>{direct_link}</code>"
                        logger.info(f"V2RAY provisioned OK: email={email}")
                    else:
                        delivery_note = "❌ سرور ساخته شد ولی لینک ساخته نشد. لطفا به پشتیبانی پیام دهید."
                else:
                    delivery_note = "❌ خطای سیستمی رخ داد و سرور اتوماتیک ساخته نشد! لطفا این فاکتور را برای پشتیبانی ارسال کنید."
                    logger.error(f"V2RAY provision FAILED for order {order.id}")
                await client.close()
            else:
                delivery_note = "❌ ادمین هنوز سرور متصل X-UI را به ربات معرفی نکرده است. لطفا به پشتیبانی پیام دهید."
                
        svc.config_link = (config_link or delivery_note) + f"\n\nکد رهگیری: {sub_code}"
        session.add(svc)
        await session.commit()
        
        try:
            from html import escape
            raw_msg = await get_setting("order_confirm_msg", "✅ سفارش شما تایید شد.\n\nکد اشتراک: {sub_code}\nمحصول: {product_name}")
            p_name = escape(str(product.name if product else 'محصول'))
            text = raw_msg.replace("{sub_code}", f"<code>{sub_code}</code>").replace("{product_name}", f"<b>{p_name}</b>")
            
            if config_link:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
                keys = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 کپی لینک سرور", copy_text=CopyTextButton(text=config_link))]
                ])
                final_text = f"{text}\n\n➖➖➖➖➖\n📦 <b>تحویل سرویس:</b>\n\n✅ سرور ساخته شد!\n\n<b>لینک مستقیم (کپی کنید):</b>\n\n<code>{config_link}</code>"
                await bot.send_message(user.telegram_id, final_text, parse_mode="HTML", reply_markup=keys)
            else:
                final_text = f"{text}\n\n➖➖➖➖➖\n📦 <b>تحویل سرویس:</b>\n\n{delivery_note}"
                await bot.send_message(user.telegram_id, final_text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending confirm: {e}")
