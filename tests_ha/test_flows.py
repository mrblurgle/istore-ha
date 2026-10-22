"""Config entry migration, reauth, reconfigure and setup error handling."""

from unittest.mock import AsyncMock, patch

import aiohttp
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.istore_heatpump.api import IStoreAuthError
from custom_components.istore_heatpump.const import DOMAIN

V1_DATA = {"access_token": "old-token", "parent_id": "parent-1", "mdm_id": "mdm-1"}
V2_DATA = {**V1_DATA, "username": "me@example.com", "password": "pw"}
CREDS = {"access_token": "new-token", "parent_id": "parent-1", "mdm_id": "mdm-1"}
MEASUREMENTS = {"code": 10000, "data": {"mdm-1": {"points": {"WH.TopTemp": {"value": 55}}}}}

API = "custom_components.istore_heatpump.api.iStoreApi"
FLOW_AUTH = "custom_components.istore_heatpump.config_flow.authenticate"


def _patch_api(measurements=None, measurements_error=None):
    """Patch the network calls made during setup."""
    get_measurements = AsyncMock(return_value=measurements or MEASUREMENTS)
    if measurements_error is not None:
        get_measurements.side_effect = measurements_error
    return (
        patch(f"{API}.get_architecture", AsyncMock(return_value={"data": {}})),
        patch(f"{API}.get_attributes", AsyncMock(return_value={"data": {}})),
        patch(f"{API}.get_measurements", get_measurements),
    )


async def _setup(hass, entry, **kwargs):
    p1, p2, p3 = _patch_api(**kwargs)
    with p1, p2, p3:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_v1_entry_migrates_and_asks_for_credentials(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=V1_DATA)
    await _setup(hass, entry)

    assert entry.version == 2
    assert entry.data == V1_DATA
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_reauth_stores_credentials_and_loads(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=V1_DATA)
    await _setup(hass, entry)
    flow = hass.config_entries.flow.async_progress()[0]

    p1, p2, p3 = _patch_api()
    with patch(FLOW_AUTH, AsyncMock(return_value=CREDS)), p1, p2, p3:
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"username": "me@example.com", "password": "pw"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["username"] == "me@example.com"
    assert entry.data["password"] == "pw"
    assert entry.data["access_token"] == "new-token"
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_reauth_bad_password_shows_error(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=V1_DATA)
    await _setup(hass, entry)
    flow = hass.config_entries.flow.async_progress()[0]

    with patch(FLOW_AUTH, AsyncMock(side_effect=IStoreAuthError("bad"))):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"username": "me@example.com", "password": "wrong"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_updates_credentials(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry)
    assert entry.state is config_entries.ConfigEntryState.LOADED

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    p1, p2, p3 = _patch_api()
    with patch(FLOW_AUTH, AsyncMock(return_value=CREDS)), p1, p2, p3:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "new@example.com", "password": "pw2"}
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data["username"] == "new@example.com"
    assert entry.data["password"] == "pw2"


async def test_reconfigure_rejects_other_device(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry)

    result = await entry.start_reconfigure_flow(hass)
    with patch(FLOW_AUTH, AsyncMock(return_value={**CREDS, "mdm_id": "other"})):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "x@example.com", "password": "pw"}
        )

    assert result["reason"] == "wrong_device"
    assert entry.data["username"] == "me@example.com"


async def test_network_down_at_startup_retries(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry, measurements_error=aiohttp.ClientConnectionError("offline"))
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_bad_credentials_at_startup_start_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry, measurements_error=IStoreAuthError("bad"))
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_network_drop_makes_entities_unavailable_then_recovers(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    with patch(f"{API}.get_measurements", AsyncMock(side_effect=aiohttp.ClientConnectionError("offline"))):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert entry.state is config_entries.ConfigEntryState.LOADED

    with patch(f"{API}.get_measurements", AsyncMock(return_value=MEASUREMENTS)):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is True


async def test_relogin_during_poll_does_not_reload_entry(hass):
    """Re-login writes the new token into entry.data; that must not reload the entry."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=V2_DATA)
    await _setup(hass, entry)
    api = hass.data[DOMAIN][entry.entry_id]["api"]

    with patch("custom_components.istore_heatpump.api.authenticate", AsyncMock(return_value=CREDS)), \
            patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await api.re_authenticate()
        await hass.async_block_till_done()

    assert entry.data["access_token"] == "new-token"
    reload.assert_not_called()
