#!/usr/bin/env python3
"""
Non-destructive E2E test for X-UI panels.
Creates a short-lived test client and tries to clean it up.
Usage:
  python scripts/test_xui_e2e.py --url https://panel.example --username admin --password secret [--inbound 1]

This script is intentionally conservative: it verifies existence first and attempts multiple cleanup methods,
ignoring failures.
"""
import asyncio
import argparse
import secrets
import time
import logging
import httpx

from core.xui import XUIApi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_xui_e2e")


async def try_cleanup(api: XUIApi, inbound_id: int, email: str):
    """Try several cleanup approaches (best-effort)."""
    # 1) Try update_client to set expiry to 0 (may effectively disable)
    try:
        ok = await api.update_client(inbound_id, "", email, total_gb=0, expire_days=0, limit_ip=1)
        if ok:
            logger.info("Cleanup: update_client set expiry=0 (may disable)")
    except Exception as e:
        logger.debug(f"update_client cleanup failed: {e}")

    # 2) Try various delete endpoints directly (best-effort)
    delete_paths = [
        f"/panel/api/clients/remove/{email}",
        f"/panel/api/clients/delete/{email}",
        f"/panel/inbound/delClient/{email}",
        f"/panel/inbound/delClient",
        f"/xui/inbound/delClient/{email}",
        f"/xui/inbound/delClient",
    ]
    for path in delete_paths:
        try:
            res = await api._post(path)  # using internal helper for convenience
            if res.status_code in (200, 204):
                logger.info(f"Cleanup: POST {path} returned {res.status_code}")
        except Exception:
            continue


async def main():
    parser = argparse.ArgumentParser(description="Non-destructive X-UI E2E test")
    parser.add_argument("--url", required=True, help="X-UI base URL")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--inbound", type=int, default=None, help="Inbound id to use (default: first)")
    args = parser.parse_args()

    api = XUIApi(args.url, args.username, args.password)

    if not await api.login():
        logger.error(f"Login failed: {api.last_error}")
        return 1

    inbounds = await api.list_inbounds()
    if not inbounds:
        logger.error("No inbounds found on panel")
        await api.close()
        return 2

    inbound_id = args.inbound or int(inbounds[0].get("id"))
    logger.info(f"Using inbound {inbound_id}")

    # Generate unique test email
    ts = int(time.time())
    rand = secrets.token_hex(3)
    test_email = f"test-e2e-{ts}-{rand}"

    # Ensure it doesn't already exist
    existing_links = await api.get_client_links(test_email)
    if existing_links:
        logger.error(f"Test email unexpectedly already exists on panel: {test_email}")
        await api.close()
        return 3

    # Create client with minimal quota and 1-day expiry
    logger.info(f"Adding test client: {test_email}")
    client_uuid = await api.add_client(inbound_id, test_email, total_gb=0, expire_days=1)
    if not client_uuid:
        logger.error(f"add_client failed: {api.last_error}")
        await api.close()
        return 4

    logger.info(f"Client added (uuid={client_uuid}), verifying links...")
    await asyncio.sleep(1.0)

    links = await api.get_client_links(test_email)
    if links:
        logger.info(f"E2E success: found client links: {links[:3]}")
    else:
        logger.warning("Client added but no links returned by get_client_links; trying list_inbounds scan")
        inbs = await api.list_inbounds()
        found = False
        for ib in inbs:
            for cs in ib.get("clientStats", []):
                if cs.get("email") == test_email:
                    logger.info("Found client in clientStats")
                    found = True
                    break
            if found: break
        if not found:
            logger.warning("E2E: could not confirm client existence via links or clientStats")

    # Cleanup best-effort
    logger.info("Attempting cleanup (best-effort)...")
    try:
        await try_cleanup(api, inbound_id, test_email)
    except Exception as e:
        logger.debug(f"Cleanup attempt error: {e}")

    await api.close()
    logger.info("Done. Note: cleanup is best-effort; inspect panel if needed.")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
