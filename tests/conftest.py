"""Shared test fixtures and HA mocking for iStore heat pump unit tests."""

import sys
from unittest.mock import MagicMock


# ── Mock Home Assistant modules before any custom_component import ──────────
# This must run at module level, before pytest collects test files that
# import from custom_components.istore_heatpump.*.

# Base CoordinatorEntity mock — stores coordinator, nothing else.
class _MockCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


# Sensor entity mock
class _MockSensorEntity:
    def __init__(self, *args, **kwargs):
        pass


# Binary sensor entity mock
class _MockBinarySensorEntity:
    def __init__(self, *args, **kwargs):
        pass


# Switch entity mock
class _MockSwitchEntity:
    def __init__(self, *args, **kwargs):
        pass


# Time entity mock
class _MockTimeEntity:
    def __init__(self, *args, **kwargs):
        pass


# Select entity mock
class _MockSelectEntity:
    def __init__(self, *args, **kwargs):
        pass


# Text entity mock
class _MockTextEntity:
    def __init__(self, *args, **kwargs):
        pass


# DataUpdateCoordinator mock
class _MockDataUpdateCoordinator:
    pass


# DeviceInfo mock (captures constructor args for assertions)
class _MockDeviceInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __eq__(self, other):
        if not isinstance(other, _MockDeviceInfo):
            return False
        return self.__dict__ == other.__dict__

    def __repr__(self):
        return f"DeviceInfo({self.__dict__})"


# Format MAC (identity for testing)
def _format_mac(mac: str) -> str:
    return mac.upper() if mac else mac


# Build mock module objects
_mock_ha_components_sensor = MagicMock()
_mock_ha_components_sensor.SensorEntity = _MockSensorEntity

_mock_ha_components_binary_sensor = MagicMock()
_mock_ha_components_binary_sensor.BinarySensorEntity = _MockBinarySensorEntity

_mock_ha_components_switch = MagicMock()
_mock_ha_components_switch.SwitchEntity = _MockSwitchEntity

_mock_ha_components_time = MagicMock()
_mock_ha_components_time.TimeEntity = _MockTimeEntity

_mock_ha_components_select = MagicMock()
_mock_ha_components_select.SelectEntity = _MockSelectEntity

_mock_ha_components_text = MagicMock()
_mock_ha_components_text.TextEntity = _MockTextEntity

_mock_ha_helpers_update_coordinator = MagicMock()
_mock_ha_helpers_update_coordinator.CoordinatorEntity = _MockCoordinatorEntity
_mock_ha_helpers_update_coordinator.DataUpdateCoordinator = _MockDataUpdateCoordinator

_mock_ha_helpers_device_registry = MagicMock()
_mock_ha_helpers_device_registry.DeviceInfo = _MockDeviceInfo
_mock_ha_helpers_device_registry.CONNECTION_NETWORK_MAC = "mac"
_mock_ha_helpers_device_registry.format_mac = _format_mac

_mock_ha_const = MagicMock()

# Register in sys.modules so 'import homeassistant.components.sensor' works
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.exceptions"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = _mock_ha_components_sensor
sys.modules["homeassistant.components.binary_sensor"] = _mock_ha_components_binary_sensor
sys.modules["homeassistant.components.switch"] = _mock_ha_components_switch
sys.modules["homeassistant.components.time"] = _mock_ha_components_time
sys.modules["homeassistant.components.select"] = _mock_ha_components_select
sys.modules["homeassistant.components.number"] = MagicMock()
sys.modules["homeassistant.components.text"] = _mock_ha_components_text
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.update_coordinator"] = _mock_ha_helpers_update_coordinator
sys.modules["homeassistant.helpers.device_registry"] = _mock_ha_helpers_device_registry
sys.modules["homeassistant.helpers.entity"] = MagicMock()
sys.modules["homeassistant.const"] = _mock_ha_const
sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()


# ── Shared fixtures ─────────────────────────────────────────────────────────


def make_coordinator(mdm_id="test-mdm-id", points_dict=None):
    """Build a mock coordinator with fake measurement data.

    Args:
        mdm_id: The device ID that appears as a key in coordinator.data.
        points_dict: Dict of {point_name: {"value": <value>}}.

    Returns:
        MagicMock with .data = {mdm_id: {"points": points_dict}}.
    """
    if points_dict is None:
        points_dict = {}
    coordinator = MagicMock()
    coordinator.data = {mdm_id: {"points": points_dict}}
    return coordinator


def make_api(mdm_id="test-mdm-id", device_info=None, attrib_data=None, tank_volume=None):
    """Build a mock iStoreApi with minimal attributes.

    Args:
        mdm_id: The device mdm_id.
        device_info: DeviceInfo object or None.
        attrib_data: Dict matching the API response structure for attributes.
        tank_volume: Override tank volume in liters. None means not set (fallback).

    Returns:
        MagicMock with .mdm_id and optional attributes.
    """
    api = MagicMock()
    api.mdm_id = mdm_id
    api.device_info = device_info
    api.attrib_data = attrib_data
    api.tank_volume = tank_volume
    return api


def make_entry(options=None):
    """Build a mock ConfigEntry with options.

    Args:
        options: Dict of option key/value pairs.

    Returns:
        MagicMock with .options that supports .get(key, default).
    """
    opts = options or {}
    entry = MagicMock()
    entry.options = MagicMock()

    def _get(key, default=None):
        return opts.get(key, default)

    entry.options.get = _get
    return entry
