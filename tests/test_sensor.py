"""Unit tests for iStore sensor entities: status mappings and thermodynamic calculations."""

from unittest.mock import MagicMock

from custom_components.istore_heatpump.sensor import (
    IStoreStatusSensor, IStoreRemainingHotWater, IStoreRawHotVolume, IStoreShowerTimeRemaining,
    _get_tank_volume,
)
from custom_components.istore_heatpump.__init__ import _parse_tank_volume
from custom_components.istore_heatpump.const import TANK_VOLUME_L
from tests.conftest import make_coordinator, make_api, make_entry


class TestStatusSensor:
    """Work mode and on/off mapping tests."""

    def test_work_mode_standby(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 0}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "Standby"

    def test_work_mode_heating(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 1}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "Heating"

    def test_work_mode_eco(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 2}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "Eco"

    def test_work_mode_hybrid(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 3}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "Hybrid"

    def test_work_mode_boost(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 4}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "Boost"

    def test_work_mode_unknown_falls_through(self):
        coordinator = make_coordinator(points_dict={"PUB_WH.WorkMode": {"value": 99}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value == "99"

    def test_onoff_on(self):
        coordinator = make_coordinator(points_dict={"WH.OnOff": {"value": 1}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "WH.OnOff", "power_mode")
        assert sensor.native_value == "On"

    def test_onoff_off(self):
        coordinator = make_coordinator(points_dict={"WH.OnOff": {"value": 0}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "WH.OnOff", "power_mode")
        assert sensor.native_value == "Off"

    def test_missing_data_returns_none(self):
        coordinator = MagicMock()
        coordinator.data = None
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value is None

    def test_missing_point_returns_none(self):
        coordinator = make_coordinator(points_dict={"OTHER.Point": {"value": 1}})
        api = make_api()
        sensor = IStoreStatusSensor(coordinator, api, "PUB_WH.WorkMode", "work_mode")
        assert sensor.native_value is None


class TestRemainingHotWater:
    """Linear stratification model tests."""

    def test_fully_above_tempering(self):
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 366.4

    def test_partially_above_tempering(self):
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 55}, "WH.BottomTemp": {"value": 30}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        # y = (55-50)/(55-30) = 0.2, hot_avg=(55+50)/2=52.5
        # liters = 270 * 0.2 * (52.5-15)/(50-15) = 57.9
        assert sensor.native_value == 57.9

    def test_fully_below_tempering(self):
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 40}, "WH.BottomTemp": {"value": 20}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_tempering_below_cold_returns_zero(self):
        entry = make_entry(options={"cold_water_temp": 60, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 65}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_top_equals_bottom_above_tempering(self):
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 60}, "WH.BottomTemp": {"value": 60}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        # bottom(60) >= tempering(50) → whole tank: 270*(60-15)/(50-15)=347.1
        assert sensor.native_value == 347.1

    def test_top_equals_bottom_below_tempering(self):
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 30}, "WH.BottomTemp": {"value": 30}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_default_cold_and_tempering(self):
        entry = make_entry(options={})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 366.4

    def test_missing_temperatures_returns_none(self):
        entry = make_entry()
        coordinator = make_coordinator(points_dict={"WH.TopTemp": {"value": 70}})
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value is None

    def test_no_data_returns_none(self):
        coordinator = MagicMock()
        coordinator.data = None
        entry = make_entry()
        api = make_api()
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value is None


class TestRawHotVolume:
    """Tests for IStoreRawHotVolume — raw volume without mixing."""

    def test_fully_above_tempering(self):
        """top=70, bottom=55, tempering=50 → entire 180L tank is hot."""
        entry = make_entry(options={"tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreRawHotVolume(coordinator, api, entry)
        assert sensor.native_value == 270.0

    def test_stratified_partial(self):
        """top=55, bottom=30, tempering=50 → y=0.2 → 54L raw volume."""
        entry = make_entry(options={"tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 55}, "WH.BottomTemp": {"value": 30}
        })
        api = make_api()
        sensor = IStoreRawHotVolume(coordinator, api, entry)
        assert sensor.native_value == 54.0

    def test_fully_below_tempering(self):
        """top=40, bottom=20, tempering=50 → no water above tempering."""
        entry = make_entry(options={"tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 40}, "WH.BottomTemp": {"value": 20}
        })
        api = make_api()
        sensor = IStoreRawHotVolume(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_missing_data_returns_none(self):
        coordinator = MagicMock()
        coordinator.data = None
        entry = make_entry()
        api = make_api()
        sensor = IStoreRawHotVolume(coordinator, api, entry)
        assert sensor.native_value is None

    def test_180l_tank_full_hot(self):
        """Real-world case: 180L tank, bottom=59, tempering=50 → 180L raw."""
        entry = make_entry(options={"tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 61.5}, "WH.BottomTemp": {"value": 59}
        })
        api = make_api(tank_volume=180)
        sensor = IStoreRawHotVolume(coordinator, api, entry)
        assert sensor.native_value == 180.0


class TestShowerTimeRemaining:
    """Mixing calculation tests."""

    def test_full_tank_estimate(self):
        entry = make_entry(options={"cold_water_temp": 15, "shower_temp": 40, "shower_flow_rate": 9.0})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        # avg = 62.5, mixing = (62.5-15)/(40-15) = 1.9, eq_vol = 270*1.9 = 513, 513/9 = 57.0
        assert sensor.native_value == 57.0

    def test_partial_tank(self):
        entry = make_entry(options={"cold_water_temp": 15, "shower_temp": 40, "shower_flow_rate": 9.0})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 50}, "WH.BottomTemp": {"value": 30}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        # y = (50-40)/(50-30) = 0.5, hot_avg=(50+40)/2=45
        # minutes = (270*0.5*(45-15)) / (9*(40-15)) = 18.0
        assert sensor.native_value == 18.0

    def test_cold_tank_zero_minutes(self):
        entry = make_entry(options={"cold_water_temp": 15, "shower_temp": 40, "shower_flow_rate": 9.0})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 20}, "WH.BottomTemp": {"value": 15}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_shower_temp_below_cold_returns_zero(self):
        entry = make_entry(options={"cold_water_temp": 50, "shower_temp": 40, "shower_flow_rate": 9.0})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_default_options(self):
        entry = make_entry(options={})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        assert sensor.native_value == 57.0

    def test_avg_temp_at_cold_returns_zero(self):
        entry = make_entry(options={"cold_water_temp": 15, "shower_temp": 40, "shower_flow_rate": 9.0})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 15}, "WH.BottomTemp": {"value": 15}
        })
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        assert sensor.native_value == 0.0

    def test_no_data_returns_none(self):
        coordinator = MagicMock()
        coordinator.data = None
        entry = make_entry()
        api = make_api()
        sensor = IStoreShowerTimeRemaining(coordinator, api, entry)
        assert sensor.native_value is None


class TestTankVolume:
    """Tests for _get_tank_volume — priority order."""

    def test_options_override_wins(self):
        """Explicit >0 in options overrides everything."""
        entry = make_entry(options={"tank_volume": 180})
        api = make_api(tank_volume=270)
        assert _get_tank_volume(api, entry) == 180.0

    def test_api_value_used_when_options_zero(self):
        """Options=0 means auto-detect, use API value."""
        entry = make_entry(options={"tank_volume": 0})
        api = make_api(tank_volume=340)
        assert _get_tank_volume(api, entry) == 340.0

    def test_fallback_when_options_zero_and_no_api(self):
        """When both are unavailable, use default constant."""
        entry = make_entry(options={"tank_volume": 0})
        api = make_api(tank_volume=None)
        assert _get_tank_volume(api, entry) == TANK_VOLUME_L

    def test_fallback_when_no_options(self):
        """No options set, use API value."""
        entry = make_entry(options={})
        api = make_api(tank_volume=180)
        assert _get_tank_volume(api, entry) == 180.0

    def test_override_with_api_discovery(self):
        """Thermo sensor uses 180L when api.tank_volume = 180.
        bottom(55) >= tempering(50) → 180*(62.5-15)/(50-15)=244.3."""
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api(tank_volume=180)
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 244.3

    def test_override_via_options(self):
        """Explicit tank_volume=200 in options, API has 270.
        bottom(55) >= tempering(50) → 200*(62.5-15)/(50-15)=271.4."""
        entry = make_entry(options={"cold_water_temp": 15, "tempering_temp": 50, "tank_volume": 200})
        coordinator = make_coordinator(points_dict={
            "WH.TopTemp": {"value": 70}, "WH.BottomTemp": {"value": 55}
        })
        api = make_api(tank_volume=270)
        sensor = IStoreRemainingHotWater(coordinator, api, entry)
        assert sensor.native_value == 271.4


class TestParseTankVolume:
    """Tests for _parse_tank_volume — attribute discovery and model name parsing."""

    MDM = "test-mdm-id"

    def _attrib(self, **kwargs):
        return {"data": {self.MDM: kwargs}}

    def test_direct_capacity(self):
        result = _parse_tank_volume(self._attrib(capacity=270), self.MDM)
        assert result == 270

    def test_rated_capacity_fallback(self):
        result = _parse_tank_volume(self._attrib(ratedCapacity=180), self.MDM)
        assert result == 180

    def test_tank_volume_attribute(self):
        result = _parse_tank_volume(self._attrib(tankVolume=340), self.MDM)
        assert result == 340

    def test_model_capacity_fallback(self):
        result = _parse_tank_volume(self._attrib(modelCapacity=200), self.MDM)
        assert result == 200

    def test_priority_order_capacity_first(self):
        result = _parse_tank_volume(
            self._attrib(capacity=270, ratedCapacity=999), self.MDM
        )
        assert result == 270

    def test_model_name_regex_fallback(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {"modelName": "270L"}}},
            self.MDM,
            model_name="270L",
        )
        assert result == 270

    def test_model_name_without_capacity_attr(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {"modelName": "270L"}}},
            self.MDM,
            model_name="270L",
        )
        assert result == 270

    def test_model_name_numeric_only(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="340"
        )
        assert result == 340

    def test_model_name_without_l_suffix(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="270"
        )
        assert result == 270

    def test_out_of_range_low_rejected(self):
        result = _parse_tank_volume(self._attrib(capacity=30), self.MDM)
        assert result is None

    def test_out_of_range_high_rejected(self):
        result = _parse_tank_volume(self._attrib(capacity=600), self.MDM)
        assert result is None

    def test_model_name_out_of_range_rejected(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="10L"
        )
        assert result is None

    def test_istore_270l_model_code(self):
        """Leading product code (015) must not be mistaken for the capacity."""
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="PASHW015-270LD-FLO2-R290"
        )
        assert result == 270

    def test_istore_180l_model_code(self):
        """A 180L unit must not fall back to the 270L default."""
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="PASHW008-180LD-NM-R290"
        )
        assert result == 180

    def test_refrigerant_code_not_mistaken_for_capacity(self):
        """R290 is the refrigerant; the capacity is the number followed by L."""
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="R290-270L"
        )
        assert result == 270

    def test_model_name_l_with_space(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="180 L"
        )
        assert result == 180

    def test_model_name_without_capacity_rejected(self):
        """A code with no L-suffixed number and no bare number gives no volume."""
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name="PASHW015-R290"
        )
        assert result is None

    def test_none_attrib_data(self):
        result = _parse_tank_volume(None, self.MDM)
        assert result is None

    def test_empty_attrib_data(self):
        result = _parse_tank_volume({}, self.MDM)
        assert result is None

    def test_no_matching_attributes(self):
        result = _parse_tank_volume({"data": {self.MDM: {}}}, self.MDM)
        assert result is None

    def test_float_capacity_truncated(self):
        result = _parse_tank_volume(self._attrib(capacity=270.9), self.MDM)
        assert result == 270

    def test_invalid_capacity_not_crash(self):
        result = _parse_tank_volume(
            self._attrib(capacity="nonsense"), self.MDM
        )
        assert result is None

    def test_no_model_name_fallback(self):
        result = _parse_tank_volume(
            {"data": {self.MDM: {}}}, self.MDM, model_name=None
        )
        assert result is None
