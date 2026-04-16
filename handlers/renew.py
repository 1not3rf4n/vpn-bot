"""
V2RAY Service Renewal Handler
Allows users to renew volume + expiry date on their existing V2RAY services.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import (ContextTypes, ConversationHandler, CallbackQueryHandler,
                          MessageHandler, CommandHandler, filters)
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, User, Service, Product, Order, XUIPanel
from core.xui import XUIApi
import core.settings as settings
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

(RENEW_CHOOSE_PLAN, RENEW_CONFIRM) = range(90, 92)

CANCEL_BTN = [[InlineKeyboardButton("🔙 انصراف", callback_data="renew_cancel")]]


async def start_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User clicked 'Renew Service #X'"""
    query = update.callback_query
    await query.answer()
    
    svc_id = int(query.data.split("_")[2])
    user_id = query.from_user.id
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
        svc = (await session.execute(select(Service).where(Service.id == svc_id, Service.user_id == user_db.id))).scalars().first()
        
        if not svc:
            await query.edit_message_text("❌ سرویس یافت نشد.")
            return ConversationHandler.END
        
        context.user_data['renew_svc_id'] = svc_id
        
        # Find V2RAY products to offer for renewal
        v2_products = (await session.execute(
            select(Product).where(Product.product_type == 'V2RAY', Product.is_active == True)
        )).scalars().all()
        
        if not v2_products:
            await query.edit_message_text("❌ هیچ پلن تمدیدی در دسترس نیست.")
            return ConversationHandler.END
        
        exp = svc.expire_date.strftime("%Y-%m-%d") if svc.expire_date else "نامحدود"
        text = f"🔄 **تمدید سرویس**\n\nسرویس: {svc.panel_username}\nانقضای فعلی: {exp}\n\nیک پلن تمدید انتخاب کنید:\n"
        
        keys = []
        for p in v2_products:
            vol_txt = f"{p.volume_gb}GB" if p.volume_gb > 0 else "نامحدود"
            label = f"📦 {p.name} | {p.duration_days} روز | {vol_txt} | {p.price:,.0f}T"
            keys.append([InlineKeyboardButton(label, callback_data=f"renew_plan_{p.id}")])
        
        keys.append(CANCEL_BTN[0])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
        return RENEW_CHOOSE_PLAN


async def renew_choose_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a renewal plan."""
    query = update.callback_query
    await query.answer()
    
    prod_id = int(query.data.split("_")[2])
    user_id = query.from_user.id
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
        product = (await session.execute(select(Product).where(Product.id == prod_id))).scalars().first()
        
        if not product or not user_db:
            await query.edit_message_text("❌ محصول یافت نشد.")
            return ConversationHandler.END
        
        context.user_data['renew_prod_id'] = prod_id
        
        vol_txt = f"{product.volume_gb}GB" if product.volume_gb > 0 else "نامحدود"
        text = (
            f"🔄 **تایید تمدید**\n\n"
            f"پلن: {product.name}\n"
            f"مدت: {product.duration_days} روز\n"
            f"حجم: {vol_txt}\n"
            f"قیمت: {product.price:,.0f} تومان\n\n"
            f"💰 موجودی فعلی شما: {user_db.wallet_balance:,.0f} تومان\n\n"
        )
        
        if user_db.wallet_balance < product.price:
            text += "❌ موجودی کیف پول شما کافی نیست. لطفا اول شارژ کنید."
            keys = [
                [InlineKeyboardButton("💳 شارژ کیف پول", callback_data="wallet_add")],
                CANCEL_BTN[0]
            ]
        else:
            text += "آیا تمدید انجام شود؟"
            keys = [
                [InlineKeyboardButton("✅ بله، تمدید کن", callback_data="renew_confirm")],
                CANCEL_BTN[0]
            ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keys), parse_mode="Markdown")
        return RENEW_CONFIRM


async def renew_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the renewal."""
    query = update.callback_query
    await query.answer()
    
    svc_id = context.user_data.get('renew_svc_id')
    prod_id = context.user_data.get('renew_prod_id')
    user_id = query.from_user.id
    
    async with AsyncSessionLocal() as session:
        user_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalars().first()
        svc = (await session.execute(select(Service).where(Service.id == svc_id))).scalars().first()
        product = (await session.execute(select(Product).where(Product.id == prod_id))).scalars().first()
        
        if not user_db or not svc or not product:
            await query.edit_message_text("❌ خطا در پردازش.")
            return ConversationHandler.END
        
        if user_db.wallet_balance < product.price:
            await query.edit_message_text("❌ موجودی کافی نیست.")
            return ConversationHandler.END
        
        # Deduct wallet
        user_db.wallet_balance -= product.price
        
        # Update service expiry
        if svc.expire_date and svc.expire_date > datetime.utcnow():
            # Add days to existing expiry
            svc.expire_date = svc.expire_date + timedelta(days=product.duration_days)
        else:
            # Set new expiry from now
            svc.expire_date = datetime.utcnow() + timedelta(days=product.duration_days)
        
        svc.status = "ACTIVE"
        
        # Try to update on X-UI panel
        panel_db = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
        xui_result = False
        logger.info(f"Renewal: panel={'found' if panel_db else 'NONE'}, config_link={'yes' if svc.config_link else 'NONE'}")
        
        if panel_db and svc.config_link:
            try:
                import json as jsonmod
                config = svc.config_link.split("\n")[0].strip()
                logger.info(f"Renewal: config first line = {config[:60]}")
                
                client_uuid = None
                if config.startswith("vless://"):
                    client_uuid = config.split("vless://")[1].split("@")[0]
                elif config.startswith("vmess://"):
                    import base64
                    decoded = jsonmod.loads(base64.b64decode(config.split("vmess://")[1]).decode())
                    client_uuid = decoded.get('id', '')
                
                logger.info(f"Renewal: extracted UUID = {client_uuid}")
                    
                if client_uuid:
                    xui = XUIApi(panel_db.url, panel_db.username, panel_db.password)
                    login_ok = await xui.login()
                    logger.info(f"Renewal: XUI login = {login_ok}")
                    
                    res = await xui.session.post(f"{xui.url}/xui/inbound/list")
                    body = res.json()
                    found_email = None
                    found_inbound_id = None
                    
                    if body.get('success'):
                        for inb in body.get('obj', []):
                            settings_data = jsonmod.loads(inb['settings']) if isinstance(inb['settings'], str) else inb['settings']
                            for cl in settings_data.get('clients', []):
                                if cl.get('id') == client_uuid:
                                    found_email = cl['email']
                                    found_inbound_id = inb['id']
                                    break
                            if found_email:
                                break
                    
                    logger.info(f"Renewal: found_email={found_email}, found_inbound={found_inbound_id}")
                    
                    if found_email and found_inbound_id:
                        total_gb = product.volume_gb or 0
                        expire_days = product.duration_days
                        
                        ok_update = await xui.update_client(
                            found_inbound_id, client_uuid, found_email,
                            total_gb, expire_days
                        )
                        ok_reset = await xui.reset_client_traffic(found_inbound_id, found_email)
                        
                        xui_result = ok_update
                        logger.info(f"Renewal DONE: update={ok_update}, reset={ok_reset}")
                    else:
                        logger.error(f"Renewal: client UUID {client_uuid} not found in any inbound")
                    
                    await xui.close()
            except Exception as e:
                logger.error(f"Renewal X-UI error: {e}", exc_info=True)
        
        await session.commit()
        
        exp_str = svc.expire_date.strftime("%Y-%m-%d")
        vol_txt = f"{product.volume_gb}GB" if product.volume_gb > 0 else "نامحدود"
        
        result_msg = "✅" if xui_result else "⚠️"
        panel_note = "سرور پنل آپدیت شد." if xui_result else "آپدیت پنل انجام نشد؛ لطفا به پشتیبانی اطلاع دهید."
        
        text = (
            f"🔄 **تمدید انجام شد!**\n\n"
            f"{result_msg} {panel_note}\n\n"
            f"پلن: {product.name}\n"
            f"حجم جدید: {vol_txt}\n"
            f"انقضای جدید: {exp_str}\n"
            f"مبلغ کسر شده: {product.price:,.0f} تومان"
        )
        
        await query.edit_message_text(text, parse_mode="Markdown")
    
    return ConversationHandler.END


async def renew_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ عملیات تمدید لغو شد.")
    return ConversationHandler.END


def get_renew_conv_handler():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_renew, pattern=r"^renew_svc_\d+$")
        ],
        states={
            RENEW_CHOOSE_PLAN: [CallbackQueryHandler(renew_choose_plan, pattern=r"^renew_plan_\d+$")],
            RENEW_CONFIRM: [CallbackQueryHandler(renew_confirm, pattern=r"^renew_confirm$")]
        },
        fallbacks=[
            CallbackQueryHandler(renew_cancel, pattern=r"^renew_cancel$"),
            CommandHandler("cancel", renew_cancel)
        ]
    )
