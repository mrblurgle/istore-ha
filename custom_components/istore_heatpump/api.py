from __future__ import annotations

import asyncio
import base64
import json
import logging
import aiohttp
from aiohttp import ClientTimeout
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from .const import DEFAULT_WORK_MODE

_LOGGER = logging.getLogger(__name__)

# iStore API uses inconsistent success codes across endpoints.
# 0, 200, and 10000 all indicate success depending on the endpoint.
_VALID_CODES = {0, 200, 10000}

# Returned with HTTP 200 when the session token has expired:
# {"code": 30000, "msg": "please sign in", "detail": "Please login first."}
_SESSION_EXPIRED_CODE = 30000

# 30-second total timeout prevents hung connections from stalling the event loop
_DEFAULT_TIMEOUT = ClientTimeout(total=30, connect=10)

# Timer-related points sent in batch writes (all must go together per API)
_TIMER_POINTS = [
    "PRI_RE_WH.Timer1On",
    "PRI_RE_WH.Timer1OnTime",
    "PRI_RE_WH.Timer1Off",
    "PRI_RE_WH.Timer1OffTime",
    "PRI_RE_WH.Timer2On",
    "PRI_RE_WH.Timer2OnTime",
    "PRI_RE_WH.Timer2Off",
    "PRI_RE_WH.Timer2OffTime",
    "PUB_WH.WorkMode",
]

_MEASUREMENT_POINTS = [
    "WH.OnOff",
    "WH.TargetTemp",
    "WH.TopTemp",
    "WH.BottomTemp",
    "PUB_WH.CompressorStatus",
    "PUB_WH.EnvirTemp",
    "PUB_WH.SuctionTemp",
    "PUB_WH.CoilTemp",
    "PUB_WH.Booster",
    "PRI_RE_WH.Timer1On",
    "PRI_RE_WH.Timer1OnTime",
    "PRI_RE_WH.Timer1Off",
    "PRI_RE_WH.Timer1OffTime",
    "PRI_RE_WH.Timer2On",
    "PRI_RE_WH.Timer2OnTime",
    "PRI_RE_WH.Timer2Off",
    "PRI_RE_WH.Timer2OffTime",
    "PUB_WH.WorkMode",
    "WH.TargetTempMin",
    "WH.TargetTempMax",
    "PUB_WH.4WayStatus",
    "PUB_WH.FanSpeed",
    "PUB_WH.DefrostStatus",
]


# ──────────────────────────────────────────────────────────────────────────────
# Custom exception types
# ──────────────────────────────────────────────────────────────────────────────


class IStoreAuthError(Exception):
    """Authentication failed due to invalid credentials."""


class IStoreApiError(Exception):
    """iStore API returned an error response."""


# ──────────────────────────────────────────────────────────────────────────────
# Authentication helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _get_public_key(session: aiohttp.ClientSession) -> tuple[str, str]:
    """Return (publicKey_b64, strategy) from the iStore public-key endpoint."""
    url = "https://home.istore.net.au/hossain-bff/framework/v1.0/user/public-key"
    async with session.get(url) as resp:
        body = await resp.json(content_type=None)
        if body.get("code") != 0:
            raise IStoreApiError(f"public-key API error: code={body.get('code')}")
        data = body["data"]
        return data["publicKey"], data["strategy"]


def _encrypt_password(public_key_b64: str, password: str) -> str:
    """Encrypt password with the server's RSA public key.

    iStore uses RSA OAEP with SHA-256 for BOTH the main hash and the MGF1 hash.
    """
    key_der = base64.b64decode(public_key_b64)
    public_key = serialization.load_der_public_key(key_der, backend=default_backend())
    encrypted = public_key.encrypt(
        password.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode("utf-8")


async def _login(
    session: aiohttp.ClientSession,
    strategy: str,
    username: str,
    encrypted_password: str,
) -> tuple[str, str]:
    """POST /user/login — returns (access_token, org_id)."""
    url = "https://home.istore.net.au/hossain-bff/framework/v1.0/user/login"
    payload = {
        "strategy": strategy,
        "account": username,
        "password": encrypted_password,
    }
    async with session.post(url, json=payload) as resp:
        body = await resp.json(content_type=None)
        _LOGGER.debug("login response code: %s", body.get("code"))
        if body.get("code") != 0:
            error_code = body.get("code")
            raise IStoreAuthError(f"login failed: {body.get('message', f'code={error_code}')}")
        data = body["data"]
        access_token = data["accessToken"]
        org_id = data["organizations"][0]["id"]
        return access_token, org_id


async def _set_session(
    session: aiohttp.ClientSession, access_token: str, org_id: str
) -> str:
    """POST /user/set-session — returns companyId."""
    url = "https://home.istore.net.au/hossain-bff/framework/v1.0/user/set-session"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.post(url, json={"orgId": org_id}, headers=headers) as resp:
        body = await resp.json(content_type=None)
        _LOGGER.debug("set-session response code: %s", body.get("code"))
        if body.get("code") != 0:
            error_code = body.get("code")
            raise IStoreApiError(f"set-session failed: {body.get('message', f'code={error_code}')}")
        return body["data"]["companyId"]


async def _get_app_id(session: aiohttp.ClientSession, access_token: str) -> str:
    """GET /user/category/app/resource/list — extract appId for Univers_EMS in Smart Grid."""
    url = "https://home.istore.net.au/app-portal/web/v1/user/category/app/resource/list?basicType=0"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with session.get(url, headers=headers) as resp:
        body = await resp.json(content_type=None)
        _LOGGER.debug("app/resource/list code: %s", body.get("code"))
        if body.get("code") not in (0, 200):
            error_code = body.get("code")
            raise IStoreApiError(f"app resource list failed: {body.get('message', f'code={error_code}')}")

        categories = body["data"]["categories"]
        for cat in categories:
            if cat.get("name") == "Smart Grid":
                for app in cat.get("apps", []):
                    if app.get("code") == "Univers_EMS":
                        return app["id"]
        raise IStoreApiError("Could not find Univers_EMS app under Smart Grid category")


async def _get_site_id(
    session: aiohttp.ClientSession, access_token: str, app_id: str
) -> str:
    """POST /user/app/asset/tree — extract siteId for 'Istore home owner' device."""
    url = (
        f"https://home.istore.net.au/app-portal/web/v1/user/app/asset/tree"
        f"?appId={app_id}&needAssociateAsset=true&resourceTypes=all"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with session.post(url, data="null", headers=headers) as resp:
        body = await resp.json(content_type=None)
        _LOGGER.debug("asset/tree code: %s", body.get("code"))
        if body.get("code") not in (0, 200):
            error_code = body.get("code")
            raise IStoreApiError(f"asset tree failed: {body.get('message', f'code={error_code}')}")

        for top_child in body["data"].get("children", []):
            for mid_child in top_child.get("children", []):
                if mid_child.get("name") == "Istore home owner":
                    for leaf in mid_child.get("children", []):
                        site_id = leaf.get("id")
                        if site_id:
                            return site_id
        raise IStoreApiError("Could not find site under 'Istore home owner'")


async def _get_device_id(
    session: aiohttp.ClientSession, access_token: str, site_id: str
) -> str:
    """POST /asset-hierarchy — extract mdmId for Res_WaterHeater under the given siteId."""
    url = "https://home.istore.net.au/encompassbffservice/encompass-bff/asset-service/v1.0/asset-hierarchy"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = urlencode(
        {
            "mdmIds": site_id,
            "mdmTypes": "Res_WaterHeater",
            "attributes": "name,mdmType",
            "locale": "en-US",
        }
    )
    async with session.post(url, data=payload, headers=headers) as resp:
        body = await resp.json(content_type=None)
        _LOGGER.debug("asset-hierarchy code: %s", body.get("code"))
        if body.get("code") != 10000:
            msg = body.get("msg", f"code={body.get('code')}")
            raise IStoreApiError(f"asset hierarchy failed: {msg}")

        site_data = body["data"].get(site_id, {})
        wh_list = site_data.get("mdmObjects", {}).get("Res_WaterHeater", [])
        if not wh_list:
            raise IStoreApiError(f"No Res_WaterHeater device found under site {site_id}")
        return wh_list[0]["mdmId"]


# ──────────────────────────────────────────────────────────────────────────────
# Public auth entry-point
# ──────────────────────────────────────────────────────────────────────────────


def _mask_id(value: str) -> str:
    """Return truncated identifier for safe debug logging."""
    if len(value) <= 7:
        return "****"
    return value[:4] + "..." + value[-4:]


async def authenticate(username: str, password: str) -> dict:
    """Full login flow.

    Returns a dict with keys:
        access_token, parent_id (siteId), mdm_id (device mdmId)
    """
    async with aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT) as session:
        pub_key_b64, strategy = await _get_public_key(session)
        encrypted_pw = _encrypt_password(pub_key_b64, password)
        access_token, org_id = await _login(session, strategy, username, encrypted_pw)
        await _set_session(session, access_token, org_id)  # companyId returned but not needed downstream
        app_id = await _get_app_id(session, access_token)
        _LOGGER.debug("Univers_EMS appId: %s", _mask_id(app_id))
        parent_id = await _get_site_id(session, access_token, app_id)
        _LOGGER.debug("site_id (parent_id): %s", _mask_id(parent_id))
        mdm_id = await _get_device_id(session, access_token, parent_id)
        _LOGGER.debug("device mdm_id: %s", _mask_id(mdm_id))

    return {
        "access_token": access_token,
        "parent_id": parent_id,
        "mdm_id": mdm_id,
    }


# ──────────────────────────────────────────────────────────────────────────────
# API client
# ──────────────────────────────────────────────────────────────────────────────

class iStoreApi:
    def __init__(
        self,
        username: str,
        password: str,
        access_token: str,
        parent_id: str,
        mdm_id: str,
        hass,
        entry=None,
    ):
        self.username = username
        self.password = password
        self.access_token = access_token
        self.parent_id = parent_id
        self.mdm_id = mdm_id
        self.hass = hass
        # ConfigEntry to persist refreshed tokens into (None in tests/scripts)
        self.entry = entry

        # Populated during setup
        self.arch_data = None
        self.attrib_data = None
        self.device_info = None
        self.tank_volume = None

        # Prevents concurrent re-auth attempts
        self._auth_lock = asyncio.Lock()
        self._session = None

    async def _get_session(self):
        """Return a shared aiohttp session for the poll cycle."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
        return self._session

    async def close(self):
        """Close the shared session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def re_authenticate(self, stale_token: str | None = None):
        """Re-run the full auth flow and refresh stored credentials.

        stale_token is the token the failed request used. If another caller
        has already replaced it while we waited for the lock, skip the login.
        """
        async with self._auth_lock:
            if stale_token is not None and self.access_token != stale_token:
                return
            if not self.username or not self.password:
                raise IStoreAuthError("No iStore username/password stored")

            _LOGGER.debug("iStore: re-authenticating...")
            creds = await authenticate(self.username, self.password)
            if creds["mdm_id"] != self.mdm_id:
                _LOGGER.warning(
                    "iStore: login returned a different device (%s, was %s)",
                    _mask_id(creds["mdm_id"]), _mask_id(self.mdm_id),
                )
            self.access_token = creds["access_token"]
            self.parent_id = creds["parent_id"]
            self.mdm_id = creds["mdm_id"]
            _LOGGER.debug("iStore: re-authentication successful")

            # Persist so a restart starts with a working token
            if self.entry is not None:
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={
                        **self.entry.data,
                        "access_token": self.access_token,
                        "parent_id": self.parent_id,
                        "mdm_id": self.mdm_id,
                    },
                )

    async def _post(self, url, headers, **kwargs) -> tuple[int, dict | None]:
        """POST with one re-login and retry if the session has expired.

        iStore signals an expired session either with HTTP 401 or with
        HTTP 200 and {"code": 30000, "msg": "please sign in"}.
        Returns (status, parsed JSON body or None).
        """
        session = await self._get_session()
        for attempt in range(2):
            token = self.access_token
            headers["Authorization"] = f"Bearer {token}"
            async with session.post(url, headers=headers, **kwargs) as resp:
                status = resp.status
                text = await resp.text()
            try:
                body = json.loads(text)
            except ValueError:
                body = None

            expired = status == 401 or (
                isinstance(body, dict) and body.get("code") == _SESSION_EXPIRED_CODE
            )
            if not expired:
                return status, body
            if attempt == 0:
                _LOGGER.info("iStore: session expired, logging in again")
                await self.re_authenticate(stale_token=token)

        raise IStoreApiError("iStore session still expired after re-login")

    # -------------------------------------------------------------------------
    # Asset hierarchy
    # -------------------------------------------------------------------------
    async def get_architecture(self):
        url = "https://home.istore.net.au/encompassbffservice/encompass-bff/asset-service/v1.0/asset-hierarchy"
        payload = urlencode({
            "mdmIds": self.parent_id,
            "mdmTypes": "Res_WaterHeater",
            "attributes": "name,mdmType",
            "locale": "en-US",
        })
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        status, body = await self._post(url, headers, data=payload)
        if status != 200 or body is None:
            raise IStoreApiError(f"iStore hierarchy API failed: {status}")
        return body

    # -------------------------------------------------------------------------
    # Device attributes
    # -------------------------------------------------------------------------
    async def get_attributes(self):
        url = (
            "https://home.istore.net.au/encompassbffservice/"
            "encompass-bff/anti-timeseries/v1.0/attributes?"
            "attributes=DeviceState,modelName,name,sn,manufacturerName,macCode,capacity,ratedCapacity,tankVolume,modelCapacity"
        )
        payload = urlencode({
            "withI18n": "true",
            "mdmIds": self.mdm_id,
            "locale": "en-US",
        })
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        status, body = await self._post(url, headers, data=payload)
        if status != 200 or body is None:
            raise IStoreApiError(f"iStore attributes API failed: {status}")
        return body

    # -------------------------------------------------------------------------
    # Measurements
    # -------------------------------------------------------------------------
    async def get_measurements(self):
        url = (
            "https://home.istore.net.au/encompassbffservice/"
            "encompass-bff/anti-timeseries/v1.0/measurement-points"
        )
        payload = urlencode(
            {"mdmIds": self.mdm_id, "pointIds": ",".join(_MEASUREMENT_POINTS)}
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

        status, body = await self._post(url, headers, data=payload)
        if status != 200 or body is None:
            raise IStoreApiError(f"iStore measurement API returned HTTP {status}")
        if not isinstance(body.get("data"), dict):
            raise IStoreApiError(
                f"iStore measurement API error: code={body.get('code')} msg={body.get('msg')}"
            )
        return body

    # -------------------------------------------------------------------------
    # Control (On/Off/Booster)
    # -------------------------------------------------------------------------
    async def set_onoff(self, point, value):
        url = "https://home.istore.net.au/hossain-bff/connect/v1.0/device/control"
        if point == "Power":
            control_point = "WH.OnOff"
        elif point == "Booster":
            control_point = "PUB_WH.Booster"
        else:
            return

        payload = [
            {"assetId": self.mdm_id, "controlPointId": control_point, "value": value}
        ]
        headers = {"Content-Type": "application/json"}

        _LOGGER.debug("iStore control request: %s", control_point)
        _status, res_json = await self._post(url, headers, json=payload)
        res_json = res_json or {}
        _LOGGER.debug("iStore control response code: %s", res_json.get("code"))
        if res_json.get("code") not in _VALID_CODES:
            raise IStoreApiError(f"Control failed: {res_json}")
        return res_json

    # -------------------------------------------------------------------------
    # Timer batch control
    # -------------------------------------------------------------------------
    async def set_timers_batch(self, timer_settings: dict):
        url = "https://home.istore.net.au/hossain-bff/connect/v1.0/device/control"
        payload = [
            {"assetId": self.mdm_id, "controlPointId": point_id, "value": value}
            for point_id, value in timer_settings.items()
        ]
        headers = {"Content-Type": "application/json"}

        _LOGGER.debug("iStore batch timer request: %d points", len(payload))
        _status, res_json = await self._post(url, headers, json=payload)
        res_json = res_json or {}
        _LOGGER.debug("iStore batch timer response code: %s", res_json.get("code"))
        if res_json.get("code") not in _VALID_CODES:
            raise IStoreApiError(f"Batch timer update failed: {res_json}")
        return res_json

    async def async_write_timer_settings(self, coordinator, updates: dict):
        """Read all timer points from coordinator, apply updates, write as batch."""
        if not coordinator or not coordinator.data:
            raise IStoreApiError("Coordinator data not available to build timer batch")

        points_data = coordinator.data.get(self.mdm_id, {}).get("points", {})

        def _coerce(point, raw):
            if point.endswith("Time"):
                return str(raw) if raw is not None else "00:00"
            try:
                return int(raw)
            except (ValueError, TypeError):
                return DEFAULT_WORK_MODE if point == "PUB_WH.WorkMode" else 0

        batch = {}
        for point in _TIMER_POINTS:
            raw = points_data.get(point, {}).get("value")
            batch[point] = _coerce(point, raw)

        for point, value in updates.items():
            batch[point] = _coerce(point, value)

        return await self.set_timers_batch(batch)

    # -------------------------------------------------------------------------
    # Asset name update
    # -------------------------------------------------------------------------
    async def update_asset_name(self, name):
        url = "https://home.istore.net.au/hossain-bff/monitor/v1.0/asset/update"
        payload = {"assetId": self.mdm_id, "name": name}
        headers = {"Content-Type": "application/json"}

        status, res_json = await self._post(url, headers, json=payload)
        if status != 200 or res_json is None:
            raise IStoreApiError(f"Failed to update asset name: {status}")
        if res_json.get("code") not in _VALID_CODES:
            raise IStoreApiError(
                f"Update failed with code: {res_json.get('code')}"
            )
        return True
