"""Live check of iStore login and automatic re-login (not part of the integration).

Logs in with your iStore credentials, reads measurements, then corrupts the
access token and reads again to prove the client logs in again by itself when
iStore rejects the session (HTTP 401 or {"code": 30000, "msg": "please sign in"}).

Needs only aiohttp and cryptography (no Home Assistant). Talks only to
home.istore.net.au. Never prints the password or tokens.

PowerShell:
    $env:ISTORE_USERNAME = "you@example.com"
    $env:ISTORE_PASSWORD = Read-Host -MaskInput "iStore password"
    .venv\\Scripts\\python.exe tools\\live_auth_check.py
    Remove-Item Env:ISTORE_PASSWORD
"""

import asyncio
import importlib
import logging
import os
import sys
import types
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "istore_heatpump"

# Import api.py (and its relative .const import) without running the
# package __init__, which needs Home Assistant.
_pkg = types.ModuleType("istore_heatpump")
_pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["istore_heatpump"] = _pkg
api_mod = importlib.import_module("istore_heatpump.api")


def _points(body, mdm_id):
    points = body["data"][mdm_id]["points"]
    return {p: points.get(p, {}).get("value") for p in ("WH.TopTemp", "WH.BottomTemp", "WH.OnOff")}


async def main() -> int:
    username = os.environ.get("ISTORE_USERNAME")
    password = os.environ.get("ISTORE_PASSWORD")
    if not username or not password:
        print("Set ISTORE_USERNAME and ISTORE_PASSWORD first.")
        return 2

    print("1. Logging in...")
    creds = await api_mod.authenticate(username, password)
    print(f"   OK: parent_id={api_mod._mask_id(creds['parent_id'])} mdm_id={api_mod._mask_id(creds['mdm_id'])}")

    api = api_mod.iStoreApi(
        username, password, creds["access_token"], creds["parent_id"], creds["mdm_id"], hass=None
    )
    try:
        print("2. Reading measurements with the fresh token...")
        print("  ", _points(await api.get_measurements(), api.mdm_id))

        print("3. Corrupting the token and reading again (expect a re-login)...")
        bad_token = "expired-" + api.access_token[-6:]
        api.access_token = bad_token
        body = await api.get_measurements()
        relogged = api.access_token != bad_token
        print("  ", _points(body, api.mdm_id))
        print(f"   Re-login happened: {relogged}")

        print("4. Reading once more with the renewed token...")
        print("  ", _points(await api.get_measurements(), api.mdm_id))
    finally:
        await api.close()

    print("PASS" if relogged else "FAIL: token was not renewed")
    return 0 if relogged else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="   [%(levelname)s] %(message)s")
    sys.exit(asyncio.run(main()))
