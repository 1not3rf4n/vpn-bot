import asyncio, sys
sys.path.insert(0, r"C:\Users\USER\Desktop\Telegram-bot.worktrees\agents-design-menu-button-updates")
from core.settings import get_setting

async def main():
    val = await get_setting('v2ray_server_serial', None)
    pref = await get_setting('v2ray_server_prefix', None)
    print('v2ray_server_serial=', val)
    print('v2ray_server_prefix=', pref)

asyncio.run(main())
