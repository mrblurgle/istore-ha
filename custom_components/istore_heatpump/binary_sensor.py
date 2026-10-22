from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .sensor import _get_point_value

BINARY_SENSORS = [
    # (key, point_id, name, enabled_by_default)
    # Enabled by default: useful standalone sensors
    ("running_state", "PUB_WH.CompressorStatus", "Running State", True),
    ("booster_state", "PUB_WH.Booster", "Booster State", True),
    ("4way_status", "PUB_WH.4WayStatus", "4 Way Valve", True),
    ("fan_status", "PUB_WH.FanSpeed", "Fan Status", True),
    ("defrost_status", "PUB_WH.DefrostStatus", "Defrost Status", True),
    # v1 "Running State" (heat pump powered on); kept for existing dashboards
    ("power_on", "WH.OnOff", "Power On", True),
    # Disabled by default: redundant with switch entities or duplicate readings
    ("compressor_status", "PUB_WH.CompressorStatus", "Compressor Status", False),
    ("timer1_on", "PRI_RE_WH.Timer1On", "Timer 1 Enabled", False),
    ("timer1_off", "PRI_RE_WH.Timer1Off", "Timer 1 Disabled", False),
    ("timer2_on", "PRI_RE_WH.Timer2On", "Timer 2 Enabled", False),
    ("timer2_off", "PRI_RE_WH.Timer2Off", "Timer 2 Disabled", False),
]

# v1 unique_id suffixes for sensors that existed before, so existing entities
# keep their entity IDs and history. v1 "running_state" reported WH.OnOff (not
# the compressor), so it maps to power_on rather than running_state.
LEGACY_UNIQUE_ID_SUFFIX = {
    "power_on": "running_state_wh_onoff",
    "booster_state": "booster_pub_wh_booster",
    "4way_status": "4_way_status_pub_wh_4waystatus",
    "fan_status": "fan_status_pub_wh_fanspeed",
    "defrost_status": "defrost_status_pub_wh_defroststatus",
    "compressor_status": "compressor_status_pub_wh_compressorstatus",
}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    api = data["api"]

    entities = []
    for key, point, name, enabled in BINARY_SENSORS:
        entities.append(
            IStoreBinarySensor(coordinator, api, key, point, name, enabled)
        )

    async_add_entities(entities)


class IStoreBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for iStore on/off states."""

    def __init__(self, coordinator, api, key, point, name, enabled=True):
        super().__init__(coordinator)
        self.api = api
        self.key = key
        self.point = point
        self._attr_name = name
        suffix = LEGACY_UNIQUE_ID_SUFFIX.get(key, key)
        self._attr_unique_id = f"istore_{api.mdm_id}_{suffix}"
        self._attr_device_info = api.device_info
        self._attr_entity_registry_enabled_default = enabled

    @property
    def is_on(self):
        value = _get_point_value(self.coordinator, self.api.mdm_id, self.point)
        if value is None:
            return False

        # Booster: 1=On, 2=Off
        if self.point == "PUB_WH.Booster":
            return value == 1

        # 4WayStatus, FanSpeed, DefrostStatus: check 1 or "1"
        if self.point in ("PUB_WH.4WayStatus", "PUB_WH.FanSpeed", "PUB_WH.DefrostStatus"):
            return value in (1, "1", True)

        # Timer On/Off: 1 = enabled
        return value == 1
