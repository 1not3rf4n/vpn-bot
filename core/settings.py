from sqlalchemy.future import select
from database.models import AsyncSessionLocal, Setting

async def get_setting(key: str, default=None):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Setting).where(Setting.key == key))
        setting = result.scalars().first()
        return setting.value if setting else default

async def set_setting(key: str, value: str):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Setting).where(Setting.key == key))
        setting = result.scalars().first()
        if setting:
            setting.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()

async def ensure_defaults():
    defaults = {
        "start_message": "سلام! به ربات فروشگاهی ما خوش آمدید.",
        "forced_channel": "", # ID without @, if empty -> OFF
        "admin_card": "6037990000000000",
        "panel_enabled": "False", # "True" / "False"
        "crypto_address": "Txxxxxx..."
    }
    for k, v in defaults.items():
        if await get_setting(k) is None:
            await set_setting(k, v)
