from dotenv import load_dotenv
load_dotenv()

import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from core.config import BOT_TOKEN
from database.models import init_db
from core.settings import ensure_defaults

# Import handlers
from handlers.user import start_cmd, user_dashboard_callbacks, main_menu_handler
from handlers.admin import admin_callbacks
from handlers.admin_settings import get_settings_conv_handler, get_settings_routers
from handlers.admin_shop import get_admin_shop_conv_handler, get_admin_shop_routers
from handlers.admin_finance import get_finance_conv_handler, get_finance_routers
from handlers.admin_discounts import get_discount_conv_handler, get_discount_routers
from handlers.wallet import get_wallet_conv_handler, verify_receipt_callback, get_wallet_routers
from handlers.shop import get_shop_handlers
from handlers.support import get_support_conv_handler, get_admin_support_handler, get_support_routers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application):
    logger.info("Initializing database...")
    await init_db()
    logger.info("Ensuring default settings exists...")
    await ensure_defaults()
    
    import asyncio
    from jobs.renewal import smart_renewal_job
    from jobs.cleanup import free_config_cleanup_job
    asyncio.create_task(smart_renewal_job(application))
    asyncio.create_task(free_config_cleanup_job(application))
    
    logger.info("Bot is ready to rock!")

def main():
    if not BOT_TOKEN or BOT_TOKEN == "BOT_TOKEN":
        print("Please configure BOT_TOKEN in core/config.py")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    from handlers.admin_users import get_admin_users_conv_handler, get_admin_users_routers
    from handlers.admin_free import get_admin_free_conv, get_admin_free_routers
    from handlers.admin_broadcast import get_broadcast_conv
    
    # Admin Conversations
    application.add_handler(get_admin_users_conv_handler())
    application.add_handler(get_settings_conv_handler())
    application.add_handler(get_admin_shop_conv_handler())
    application.add_handler(get_finance_conv_handler())
    application.add_handler(get_discount_conv_handler())
    application.add_handler(get_admin_free_conv())
    application.add_handler(get_broadcast_conv())
    
    # Financials & Support Conversations
    application.add_handler(get_wallet_conv_handler())
    application.add_handler(get_support_conv_handler())
    application.add_handler(get_admin_support_handler())

    # Renewal
    from handlers.renew import get_renew_conv_handler
    application.add_handler(get_renew_conv_handler())

    # Regular Commands
    application.add_handler(CommandHandler("start", start_cmd))

    # Shop Handlers
    for handler in get_shop_handlers():
        application.add_handler(handler)

    # General Callbacks
    application.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^admin_(panel|cancel|stats|recent_orders|broadcast|free_configs|server_info)"))
    
    for rt in get_settings_routers(): application.add_handler(rt)
    for rt in get_admin_shop_routers(): application.add_handler(rt)
    for rt in get_finance_routers(): application.add_handler(rt)
    for rt in get_discount_routers(): application.add_handler(rt)
    for rt in get_support_routers(): application.add_handler(rt)
    for rt in get_wallet_routers(): application.add_handler(rt)
    for rt in get_admin_free_routers(): application.add_handler(rt)
    for rt in get_admin_users_routers(): application.add_handler(rt)

    application.add_handler(CallbackQueryHandler(verify_receipt_callback, pattern="^(verify|reject)_receipt_"))
    async def log_call(update, context):
        logger.info(f"Callback data received: {update.callback_query.data} from user {update.effective_user.id}")
    application.add_handler(CallbackQueryHandler(log_call), group=-1)

    application.add_handler(CallbackQueryHandler(user_dashboard_callbacks)) # Fallback user callbacks
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), main_menu_handler))

    logger.info("Starting polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
