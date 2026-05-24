#!/usr/bin/env python3
"""Test X-UI panel connection. Run on server: python scripts/test_panel.py"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from database.models import AsyncSessionLocal, XUIPanel
from core.xui import XUIApi, __version__ as xui_version


async def main():
    print(f"XUI module version: {xui_version}")
    async with AsyncSessionLocal() as session:
        panel = (await session.execute(select(XUIPanel).where(XUIPanel.is_active == True))).scalars().first()
    if not panel:
        print("ERROR: No active XUIPanel in database")
        return 1

    print(f"Panel URL: {panel.url}")
    print(f"User: {panel.username}")

    client = XUIApi(panel.url, panel.username, panel.password)
    ok = await client.login()
    print(f"Login: {'OK' if ok else 'FAIL'} | mode={client.api_mode}")
    if not ok:
        print(f"Error: {client.last_error}")
        await client.close()
        return 1

    inbounds = await client.list_inbounds()
    print(f"Inbounds ({len(inbounds)}): {[i.get('id') for i in inbounds]}")

    if inbounds:
        ib_id = inbounds[0]["id"]
        test_email = "zyphervpnsalle_test_delete"
        print(f"Test addClient inbound={ib_id} email={test_email} ...")
        uuid_res = await client.add_client(ib_id, test_email, 0, 1)
        if uuid_res:
            print(f"SUCCESS uuid={uuid_res}")
            links = await client.get_client_links(test_email)
            print(f"Links: {links[:1]}...")
        else:
            print(f"FAIL: {client.last_error}")
            await client.close()
            return 1

    await client.close()
    print("All OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
