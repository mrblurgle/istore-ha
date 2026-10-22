from homeassistant.components.text import TextEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN, COMMAND_REFRESH_DELAY
from .sensor import _get_point_value
import asyncio
import logging
import re

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    coordinator = data["coordinator"]

    entities = [IStoreDeviceName(coordinator, api)]
    for point, name in TIMER_TEXT_POINTS.items():
        entities.append(IStoreTimerText(coordinator, api, point, name))
    async_add_entities(entities)


# HH:MM text versions of the timer times, kept from v1 alongside the time
# entities so existing entity IDs (text.istore_timer1_on, ...) and the
# automations using them keep working.
TIMER_TEXT_POINTS = {
    "PRI_RE_WH.Timer1OnTime": "T1 On",
    "PRI_RE_WH.Timer1OffTime": "T1 Off",
    "PRI_RE_WH.Timer2OnTime": "T2 On",
    "PRI_RE_WH.Timer2OffTime": "T2 Off",
}


class IStoreDeviceName(CoordinatorEntity, TextEntity):
    """Text entity to edit the iStore device name."""

    _attr_icon = "mdi:rename-box"
    _attr_name = "Device Name"
    _attr_native_max = 64

    def __init__(self, coordinator, api):
        super().__init__(coordinator)
        self.api = api
        self._attr_unique_id = f"istore_{api.mdm_id}_device_name"
        self._attr_device_info = api.device_info

    @property
    def native_value(self):
        """Return the current device name."""
        data = self.coordinator.data
        if not data:
            return None

        # Try attrib_data first
        attrib_data = getattr(self.api, "attrib_data", None)
        if attrib_data and "data" in attrib_data:
            device_attrs = attrib_data["data"].get(self.api.mdm_id, {})
            if device_attrs.get("name"):
                return device_attrs["name"]

        # Fallback to arch_data
        arch_data = getattr(self.api, "arch_data", None)
        if arch_data and "data" in arch_data:
            site_data = arch_data["data"].get(self.api.parent_id, {})
            for obj in site_data.get("mdmObjects", {}).get("Res_WaterHeater", []):
                if obj.get("mdmId") == self.api.mdm_id:
                    return obj.get("name", "iStore Heat Pump")

        return "iStore Heat Pump"

    async def async_set_value(self, value: str):
        """Set a new device name on the iStore server and update HA device registry."""
        await self.api.update_asset_name(value)

        # Update the device registry name
        device_registry = async_get_device_registry(self.hass)
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self.api.mdm_id)}
        )
        if device:
            device_registry.async_update_device(device.id, name=value)

        # Trigger a coordinator refresh to pick up the name change
        await self.coordinator.async_request_refresh()


class IStoreTimerText(CoordinatorEntity, TextEntity):
    """Timer on/off time as an HH:MM text entity (v1 compatible)."""

    _attr_icon = "mdi:clock-outline"
    _attr_pattern = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
    _attr_native_min = 5
    _attr_native_max = 5

    def __init__(self, coordinator, api, point, name):
        super().__init__(coordinator)
        self.api = api
        self.point = point
        self._attr_name = name
        safe_key = point.lower().replace(".", "_")
        # v1 unique_id format — do not change, existing entities depend on it
        self._attr_unique_id = f"istore_{api.mdm_id}_{safe_key}_text"
        self._attr_device_info = api.device_info

    @property
    def native_value(self):
        """Return the timer time as HH:MM."""
        raw = _get_point_value(self.coordinator, self.api.mdm_id, self.point)
        match = re.match(r"(\d{1,2}):(\d{2})", str(raw)) if raw is not None else None
        if not match:
            return None
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    async def async_set_value(self, value: str):
        """Set the timer time via batch write (the API rejects single-point timer writes)."""
        try:
            await self.api.async_write_timer_settings(self.coordinator, {self.point: value})

            # Optimistically update coordinator cache for instant UI feedback
            mdmid = self.api.mdm_id
            data = self.coordinator.data
            if data and mdmid in data and "points" in data[mdmid]:
                pts = data[mdmid]["points"]
                if self.point in pts:
                    pts[self.point]["value"] = value
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to set %s to %s: %s", self.point, value, e)
            raise
        finally:
            await asyncio.sleep(COMMAND_REFRESH_DELAY)
            await self.coordinator.async_request_refresh()
