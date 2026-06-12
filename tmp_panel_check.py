import asyncio, sys, json
sys.path.insert(0, r"C:\Users\USER\Desktop\Telegram-bot.worktrees\agents-design-menu-button-updates")
from core.xui import XUIApi

async def main():
    url = "https://zypher2.not3rf4n.site:8000/jdEGzlSEMO5rb4EEPs"
    user = "not3rf4n"
    pwd = "not3rf4n@@"
    api = XUIApi(url, user, pwd)
    ok = await api.login()
    print("LOGIN", ok, "mode", api.api_mode, "err", api.last_error)
    inb = await api.list_inbounds()
    print("INBOUNDS_COUNT", len(inb))
    try:
        print(json.dumps(inb, ensure_ascii=False, indent=2)[:8000])
    except Exception as e:
        print("INBOUNDS_DUMP_FAILED", e)
    stats = await api.get_all_client_stats()
    print("STATS_COUNT", len(stats))
    try:
        print(json.dumps(stats[:10], ensure_ascii=False, indent=2))
    except:
        pass
    await api.close()

asyncio.run(main())
