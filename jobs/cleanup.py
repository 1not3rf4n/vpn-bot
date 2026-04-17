import asyncio
import logging
from datetime import datetime
from sqlalchemy.future import select
from sqlalchemy import delete
from database.models import AsyncSessionLocal, FreeConfig

logger = logging.getLogger(__name__)

async def free_config_cleanup_job(application):
    """Periodically removes expired free configurations from the database"""
    while True:
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                # Find expired configs
                result = await session.execute(delete(FreeConfig).where(FreeConfig.expire_date < now))
                deleted_count = result.rowcount
                if deleted_count > 0:
                    await session.commit()
                    logger.info(f"Cleaned up {deleted_count} expired free configurations.")
                else:
                    await session.rollback()
        except Exception as e:
            logger.error(f"Error in free_config_cleanup_job: {e}")
        
        # Check every 1 hour (3600 seconds)
        await asyncio.sleep(3600)
