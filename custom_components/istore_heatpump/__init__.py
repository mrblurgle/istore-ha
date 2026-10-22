from __future__ import annotations

import logging
import re

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import iStoreApi, IStoreAuthError
from .coordinator import iStoreCoordinator
from .const import (DOMAIN, CONF_USERNAME, CONF_PASSWORD, CONF_ACCESS_TOKEN, CONF_PARENT_ID, CONF_MDM_ID, TANK_VOLUME_L)
from .device import IStoreDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch", "binary_sensor", "text", "time", "select"]


def _parse_tank_volume(attrib_data, mdm_id, model_name=None):
    """Extract tank volume in liters from attribute data.

    Tries direct capacity attributes first, then model name regex.
    Returns int if found, None if not.
    Only accepts capacity values in the plausible range 50-500L.
    """
    if attrib_data and "data" in attrib_data:
        attrs = attrib_data["data"].get(mdm_id, {})

        # Try direct capacity attributes — reject values outside plausible range
        for key in ("capacity", "ratedCapacity", "tankVolume", "modelCapacity"):
            val = attrs.get(key)
            if val is not None:
                try:
                    vol = int(float(val))
                    if 50 <= vol <= 500:
                        return vol
                except (ValueError, TypeError):
                    pass

    # Try model name pattern (e.g., "R290-270L", "340L", "270")
    if model_name:
        match = re.search(r"(\d+)\s*L?", str(model_name), re.IGNORECASE)
        if match:
            vol = int(match.group(1))
            if 50 <= vol <= 500:
                return vol

    return None



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up iStore Heat Pump."""
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    if not username or not password:
        # Entry migrated from v1 (token only) — HA starts the reauth flow
        raise ConfigEntryAuthFailed("iStore username and password are required")

    access_token = entry.data.get(CONF_ACCESS_TOKEN)
    parent_id = entry.data.get(CONF_PARENT_ID)
    mdm_id = entry.data.get(CONF_MDM_ID)

    api = iStoreApi(username, password, access_token, parent_id, mdm_id, hass, entry)

    # Fetch device details for DeviceInfo
    try:
        api.arch_data = await api.get_architecture()
    except IStoreAuthError as e:
        await api.close()
        raise ConfigEntryAuthFailed(str(e)) from e
    except Exception as e:
        _LOGGER.warning("Failed to fetch architecture for DeviceInfo: %s", e)
        api.arch_data = None

    try:
        api.attrib_data = await api.get_attributes()
    except IStoreAuthError as e:
        await api.close()
        raise ConfigEntryAuthFailed(str(e)) from e
    except Exception as e:
        _LOGGER.warning("Failed to fetch attributes for DeviceInfo: %s", e)
        api.attrib_data = None

    # Initialize device helper
    istore_device = IStoreDevice(api)
    api.device_info = istore_device.device_info

    # Discover tank volume from API attributes
    model_name = None
    if api.attrib_data and "data" in api.attrib_data:
        model_name = (
            api.attrib_data["data"]
            .get(api.mdm_id, {})
            .get("modelName")
            or api.attrib_data["data"]
            .get(api.mdm_id, {})
            .get("modelId")
        )
    api.tank_volume = _parse_tank_volume(api.attrib_data, api.mdm_id, model_name)
    if api.tank_volume:
        _LOGGER.info("iStore: discovered tank volume: %s L", api.tank_volume)
    else:
        _LOGGER.info("iStore: could not discover tank volume, defaulting to %s L", TANK_VOLUME_L)

    coordinator = iStoreCoordinator(hass, api, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await api.close()
        raise

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "device": istore_device,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options changes reload via OptionsFlowWithReload. No update listener here:
    # re-login writes the new token into entry.data and must not trigger a reload.

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry.

    v1 entries hold only access_token/parent_id/mdm_id. Keep the entry (and its
    entities) and let setup raise ConfigEntryAuthFailed, which starts the
    reauth flow to collect the username and password.
    """
    if config_entry.version > 2:
        return False

    if config_entry.version == 1:
        _LOGGER.info(
            "Migrating iStore config entry from version 1 to 2; "
            "Home Assistant will ask for your iStore username and password"
        )
        hass.config_entries.async_update_entry(config_entry, version=2)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload iStore."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        api = hass.data[DOMAIN].pop(entry.entry_id)["api"]
        await api.close()
    return unload_ok
