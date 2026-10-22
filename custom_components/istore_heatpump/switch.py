import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, COMMAND_REFRESH_DELAY
from .sensor import _get_point_value

_LOGGER = logging.getLogger(__name__)

POWER_POINT = "WH.OnOff"
BOOSTER_POINT = "PUB_WH.Booster"
TIMER1_ON = "PRI_RE_WH.Timer1On"
TIMER2_ON = "PRI_RE_WH.Timer2On"


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    api = data["api"]
    coordinator = data["coordinator"]

    entities = [
        IStorePowerSwitch(coordinator, api),
        IStoreBoosterSwitch(coordinator, api),
        IStoreTimerSwitch(coordinator, api, TIMER1_ON, "Timer 1"),
        IStoreTimerSwitch(coordinator, api, TIMER2_ON, "Timer 2"),
    ]

    async_add_entities(entities)


class BaseIStoreSwitch(CoordinatorEntity, SwitchEntity):
    """Base class for iStore switches."""

    control_point = None
    name_suffix = None

    def __init__(self, coordinator, api):
        super().__init__(coordinator)
        self.api = api
        self._attr_name = f"iStore {self.name_suffix}"
        safe_key = self.control_point.lower().replace(".", "_")
        self._attr_unique_id = f"istore_{api.mdm_id}_{safe_key}"
        self._attr_device_info = api.device_info

    @property
    def is_on(self):
        value = _get_point_value(self.coordinator, self.api.mdm_id, self.control_point)
        return value == 1 if value is not None else None

    async def async_turn_on(self):
        if self.control_point == POWER_POINT:
            await self.api.set_onoff("Power", 1)
        elif self.control_point == BOOSTER_POINT:
            await self.api.set_onoff("Booster", 1)
        else:
            await self._set_timer(1)

        self._update_is_on_cache(True)
        self.async_write_ha_state()
        await asyncio.sleep(COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self):
        if self.control_point == POWER_POINT:
            await self.api.set_onoff("Power", 0)
        elif self.control_point == BOOSTER_POINT:
            await self.api.set_onoff("Booster", 2)
        else:
            await self._set_timer(0)

        self._update_is_on_cache(False)
        self.async_write_ha_state()
        await asyncio.sleep(COMMAND_REFRESH_DELAY)
        await self.coordinator.async_request_refresh()

    def _update_is_on_cache(self, state_on):
        """Optimistically update coordinator cache for instant UI feedback."""
        mdmid = self.api.mdm_id
        data = self.coordinator.data
        if data and mdmid in data and "points" in data[mdmid]:
            points = data[mdmid]["points"]
            if self.control_point in points:
                if state_on:
                    points[self.control_point]["value"] = 1
                elif self.control_point == BOOSTER_POINT:
                    points[self.control_point]["value"] = 2
                else:
                    points[self.control_point]["value"] = 0

    async def _set_timer(self, value):
        """Set timer on/off via batch write to preserve other timer settings."""
        await self.api.async_write_timer_settings(self.coordinator, {self.control_point: value})


class IStorePowerSwitch(BaseIStoreSwitch):
    control_point = POWER_POINT
    name_suffix = "Power"
    _attr_icon = "mdi:power"


class IStoreBoosterSwitch(BaseIStoreSwitch):
    control_point = BOOSTER_POINT
    name_suffix = "Booster"
    _attr_icon = "mdi:lightning-bolt"


class IStoreTimerSwitch(BaseIStoreSwitch):
    _OFF_POINT_MAP = {
        "PRI_RE_WH.Timer1On": "PRI_RE_WH.Timer1Off",
        "PRI_RE_WH.Timer2On": "PRI_RE_WH.Timer2Off",
    }

    def __init__(self, coordinator, api, control_point, name_suffix):
        self.control_point = control_point
        self.name_suffix = name_suffix
        self._off_point = self._OFF_POINT_MAP.get(
            control_point, control_point.replace("On", "Off")
        )
        super().__init__(coordinator, api)
        self._attr_icon = "mdi:timer"
        # v1 unique_id format — keeps existing switch.istore_timer_1/2 entities
        self._attr_unique_id += "_switch"

    async def async_turn_on(self):
        """Enable the timer — sets both On and Off flags."""
        try:
            await self.api.async_write_timer_settings(self.coordinator, {
                self.control_point: 1,
                self._off_point: 1,
            })
            self._update_cache(1)
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to enable timer: %s", e)
            raise
        finally:
            await asyncio.sleep(COMMAND_REFRESH_DELAY)
            try:
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.warning("Timer refresh after enable failed: %s", e)

    async def async_turn_off(self):
        """Disable the timer — sets both On and Off flags to 0."""
        try:
            await self.api.async_write_timer_settings(self.coordinator, {
                self.control_point: 0,
                self._off_point: 0,
            })
            self._update_cache(0)
            self.async_write_ha_state()
        except Exception as e:
            _LOGGER.error("Failed to disable timer: %s", e)
            raise
        finally:
            await asyncio.sleep(COMMAND_REFRESH_DELAY)
            try:
                await self.coordinator.async_request_refresh()
            except Exception as e:
                _LOGGER.warning("Timer refresh after disable failed: %s", e)

    def _update_cache(self, value):
        """Optimistically update coordinator cache for instant UI feedback."""
        mdmid = self.api.mdm_id
        data = self.coordinator.data
        if data and mdmid in data and "points" in data[mdmid]:
            points = data[mdmid]["points"]
            if self.control_point in points:
                points[self.control_point]["value"] = value
            if self._off_point in points:
                points[self._off_point]["value"] = value
