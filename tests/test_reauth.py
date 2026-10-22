"""Tests for session-expiry handling (HTTP 401 and code 30000) and v1 unique_id compatibility."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.istore_heatpump import api as api_mod
from custom_components.istore_heatpump.api import iStoreApi, IStoreApiError, IStoreAuthError
from custom_components.istore_heatpump.binary_sensor import IStoreBinarySensor, BINARY_SENSORS
from custom_components.istore_heatpump.switch import IStoreTimerSwitch
from custom_components.istore_heatpump.text import IStoreTimerText
from tests.conftest import make_api, make_coordinator

EXPIRED = {"code": 30000, "msg": "please sign in", "detail": "Please login first.", "logoutHref": "eos"}
OK = {"code": 10000, "data": {"mdm-1": {"points": {}}}}


class _Resp:
    def __init__(self, status, body):
        self.status = status
        self._text = body if isinstance(body, str) else json.dumps(body)

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_api(responses, entry=None):
    """iStoreApi whose session returns the given (status, body) responses in order."""
    api = iStoreApi("user", "pw", "old-token", "parent-1", "mdm-1", MagicMock(), entry)
    session = MagicMock()
    session.closed = False
    seen_tokens = []

    def _post(url, headers=None, **kwargs):
        seen_tokens.append(headers["Authorization"])
        return _Resp(*responses.pop(0))

    session.post = MagicMock(side_effect=_post)
    api._session = session
    return api, seen_tokens


NEW_CREDS = {"access_token": "new-token", "parent_id": "parent-1", "mdm_id": "mdm-1"}


@pytest.mark.asyncio
async def test_code_30000_triggers_relogin_and_retry():
    api, tokens = _make_api([(200, EXPIRED), (200, OK)])
    with patch.object(api_mod, "authenticate", AsyncMock(return_value=NEW_CREDS)) as auth:
        body = await api.get_measurements()
    assert body == OK
    auth.assert_awaited_once_with("user", "pw")
    assert tokens == ["Bearer old-token", "Bearer new-token"]


@pytest.mark.asyncio
async def test_http_401_triggers_relogin_and_retry():
    api, tokens = _make_api([(401, ""), (200, OK)])
    with patch.object(api_mod, "authenticate", AsyncMock(return_value=NEW_CREDS)):
        body = await api.get_measurements()
    assert body == OK
    assert tokens[-1] == "Bearer new-token"


@pytest.mark.asyncio
async def test_still_expired_after_relogin_raises_api_error():
    api, _ = _make_api([(200, EXPIRED), (200, EXPIRED)])
    with patch.object(api_mod, "authenticate", AsyncMock(return_value=NEW_CREDS)):
        with pytest.raises(IStoreApiError):
            await api.get_measurements()


@pytest.mark.asyncio
async def test_bad_credentials_raise_auth_error():
    api, _ = _make_api([(200, EXPIRED)])
    with patch.object(api_mod, "authenticate", AsyncMock(side_effect=IStoreAuthError("bad"))):
        with pytest.raises(IStoreAuthError):
            await api.get_measurements()


@pytest.mark.asyncio
async def test_missing_credentials_raise_auth_error():
    api, _ = _make_api([(200, EXPIRED)])
    api.username = None
    with pytest.raises(IStoreAuthError):
        await api.get_measurements()


@pytest.mark.asyncio
async def test_relogin_skipped_when_token_already_refreshed():
    api, _ = _make_api([])
    api.access_token = "fresh-token"
    with patch.object(api_mod, "authenticate", AsyncMock()) as auth:
        await api.re_authenticate(stale_token="old-token")
    auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_relogin_persists_token_to_entry():
    entry = MagicMock()
    entry.data = {"username": "user", "password": "pw", "access_token": "old-token"}
    api, _ = _make_api([(200, EXPIRED), (200, OK)], entry=entry)
    with patch.object(api_mod, "authenticate", AsyncMock(return_value=NEW_CREDS)):
        await api.get_measurements()
    update = api.hass.config_entries.async_update_entry
    update.assert_called_once()
    assert update.call_args.kwargs["data"]["access_token"] == "new-token"
    assert update.call_args.kwargs["data"]["password"] == "pw"


@pytest.mark.asyncio
async def test_error_reply_without_data_raises_api_error():
    api, _ = _make_api([(200, {"code": 50000, "msg": "server error"})])
    with pytest.raises(IStoreApiError):
        await api.get_measurements()


# ── v1 unique_id compatibility ──────────────────────────────────────────────

def test_binary_sensor_v1_unique_ids():
    api = make_api(mdm_id="M")
    coordinator = make_coordinator(mdm_id="M")
    ids = {
        key: IStoreBinarySensor(coordinator, api, key, point, name, enabled)._attr_unique_id
        for key, point, name, enabled in BINARY_SENSORS
    }
    assert ids["power_on"] == "istore_M_running_state_wh_onoff"
    assert ids["booster_state"] == "istore_M_booster_pub_wh_booster"
    assert ids["4way_status"] == "istore_M_4_way_status_pub_wh_4waystatus"
    assert ids["fan_status"] == "istore_M_fan_status_pub_wh_fanspeed"
    assert ids["defrost_status"] == "istore_M_defrost_status_pub_wh_defroststatus"
    assert ids["compressor_status"] == "istore_M_compressor_status_pub_wh_compressorstatus"
    assert ids["running_state"] == "istore_M_running_state"
    assert len(set(ids.values())) == len(ids)


def test_timer_switch_v1_unique_id():
    api = make_api(mdm_id="M")
    switch = IStoreTimerSwitch(make_coordinator(mdm_id="M"), api, "PRI_RE_WH.Timer1On", "Timer 1")
    assert switch._attr_unique_id == "istore_M_pri_re_wh_timer1on_switch"


def test_timer_text_v1_unique_id_and_value():
    coordinator = make_coordinator(
        mdm_id="M", points_dict={"PRI_RE_WH.Timer1OnTime": {"value": "9:30"}}
    )
    text = IStoreTimerText(coordinator, make_api(mdm_id="M"), "PRI_RE_WH.Timer1OnTime", "T1 On")
    assert text._attr_unique_id == "istore_M_pri_re_wh_timer1ontime_text"
    assert text.native_value == "09:30"
