import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.future import select
from database.models import AsyncSessionLocal, Order, User

logger = logging.getLogger(__name__)

async def smart_renewal_job(application):
    logger.info("Smart renewal background job started.")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                target_date_start = datetime.utcnow() + timedelta(days=2)
                target_date_end = datetime.utcnow() + timedelta(days=3)
                
                logger.info(f"Checking for renewals between {target_date_start} and {target_date_end}")
                orders = (await session.execute(
                    select(Order)
                    .where(Order.status == 'PAID')
                    .where(Order.expire_date >= target_date_start)
                    .where(Order.expire_date < target_date_end)
                )).scalars().all()
                
                for o in orders:
                    user = (await session.execute(select(User).where(User.id == o.user_id))).scalars().first()
                    if user:
                        text = f"⏳ **یادآوری تمدید سرویس**\n\nکاربر عزیز، اشتراک سفارش `#{o.id}` شما تقریباً ۲ روز دیگر به پایان می‌رسد!\nلطفاً برای جلوگیری از قطعی، از بخش فروشگاه نسبت به خرید مجدد یا شارژ حساب اقدام فرمایید."
                        try:
                            await application.bot.send_message(user.telegram_id, text, parse_mode="Markdown")
                            logger.info(f"Sent renewal reminder to user {user.telegram_id} for order #{o.id}")
                        except Exception as e:
                            logger.error(f"Failed to send renewal to {user.telegram_id}: {e}")
                            
        except Exception as e:
            logger.error(f"Error in renewal job: {e}")
            
        await asyncio.sleep(86400) # Check once a day (24 hours)
