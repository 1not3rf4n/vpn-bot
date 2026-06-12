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
        "crypto_address": "Txxxxxx...",

        # Global user-facing feature toggles (on/off)
        "menu_shop": "on",
        "menu_wallet": "on",
        "menu_free_config": "on",
        "menu_renew": "on",

        # Custom server name feature (on/off)
        "custom_server_name_enabled": "on",

        # Payment methods toggles (on/off)
        "card_enabled": "on",
        "crypto_enabled": "off",
        "zarinpal_enabled": "off",
        "tetra98_enabled": "off",

        # Renewal pricing
        "renew_discount_percent": "0",

        # X-UI subscription path (e.g. /sub/ or /xui/sub/)
        "xui_sub_path": "/sub/",

        # V2RAY server naming: @zyphervpnsalle1, @zyphervpnsalle2, ...
        "v2ray_server_prefix": "zyphervpnsalle",
        "v2ray_server_serial": "0",
        # UI: optional menu background image URL for a glass-style header
        "menu_background_url": "",
    }
    for k, v in defaults.items():
        if await get_setting(k) is None:
            await set_setting(k, v)
