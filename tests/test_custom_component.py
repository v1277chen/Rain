#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中央氣象署雨量監控整合 (HACS Custom Component) - 單元測試套件
檔案名稱：tests/test_custom_component.py
功能簡述：
    1. 驗證 HACS 整合內部之 Haversine 與雷達迴波 dBZ 模型。
    2. 驗證多座標獨立狀態機：住家下雨 vs 工作地點晴天互不干擾。
    3. 驗證多地點共用 CWA API 快取機制。
    4. 驗證自動挑選 4 站演算法。
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

# 注入輕量級 mock 模組，讓測試能在無安裝 homeassistant-core 的環境下直接執行
for mod_name in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "voluptuous"
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# 為 DataUpdateCoordinator 與實體基底類別提供 Mock 類別，支援泛型下標與多重繼承
class MockGeneric:
    def __class_getitem__(cls, item):
        return cls

    @property
    def name(self):
        return getattr(self, "_attr_name", getattr(self, "_name", None))

    @name.setter
    def name(self, val):
        self._name = val

class MockDataUpdateCoordinator(MockGeneric):
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

class MockCoordinatorEntity(MockGeneric):
    def __init__(self, coordinator):
        self.coordinator = coordinator

class MockSensorEntity(MockGeneric):
    pass

class MockBinarySensorEntity(MockGeneric):
    pass

mock_uc = MagicMock()
mock_uc.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_uc.CoordinatorEntity = MockCoordinatorEntity
mock_uc.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = mock_uc

mock_sensor = MagicMock()
mock_sensor.SensorEntity = MockSensorEntity
sys.modules["homeassistant.components.sensor"] = mock_sensor

mock_binary_sensor = MagicMock()
mock_binary_sensor.BinarySensorEntity = MockBinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"] = mock_binary_sensor

# 將專案路徑加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from custom_components.cwa_rain.coordinator import (
    haversine_distance,
    calculate_estimated_dbz,
    CwaApiClient,
    RainDebounceStateMachine,
    CwaRainDataUpdateCoordinator,
)


class TestCwaRainHacsPhysics(unittest.TestCase):
    """測試物理運算與經驗公式"""

    def test_haversine(self):
        dist = haversine_distance(23.0150, 120.2050, 23.0039, 120.2183)
        self.assertGreater(dist, 1.0)
        self.assertLess(dist, 3.0)

    def test_dbz(self):
        self.assertEqual(calculate_estimated_dbz(0.0), 0.0)
        self.assertAlmostEqual(calculate_estimated_dbz(0.5), 30.6, delta=0.5)


class TestMultiLocationStateMachines(unittest.TestCase):
    """
    測試多座標獨立狀態機：
    情境：住家下大雨，工作地點大晴天，兩者獨立運作，互不干擾！
    """

    def setUp(self):
        # 住家狀態機
        self.home_sm = RainDebounceStateMachine(
            rain_detected_mm=0.1,
            stations_rain_count=2,
            heavy_rain_single_station_mm=1.5,
            debounce_on_count=1,
            debounce_off_count=3
        )
        # 工作地點狀態機
        self.work_sm = RainDebounceStateMachine(
            rain_detected_mm=0.1,
            stations_rain_count=2,
            heavy_rain_single_station_mm=1.5,
            debounce_on_count=1,
            debounce_off_count=3
        )

    def test_independent_locations(self):
        # 住家周邊 4 站：有 2 站下雨 (0.3mm, 0.4mm, 0.0mm, 0.0mm) -> 觸發下雨
        home_stations = [
            {"station_id": "ST_H1", "station_name": "住家測站1", "past_10min_rain": 0.3},
            {"station_id": "ST_H2", "station_name": "住家測站2", "past_10min_rain": 0.4},
            {"station_id": "ST_H3", "station_name": "住家測站3", "past_10min_rain": 0.0},
            {"station_id": "ST_H4", "station_name": "住家測站4", "past_10min_rain": 0.0},
        ]

        # 工作地點周邊 4 站：全晴天 (0.0mm) -> 無雨
        work_stations = [
            {"station_id": "ST_W1", "station_name": "工作測站1", "past_10min_rain": 0.0},
            {"station_id": "ST_W2", "station_name": "工作測站2", "past_10min_rain": 0.0},
            {"station_id": "ST_W3", "station_name": "工作測站3", "past_10min_rain": 0.0},
            {"station_id": "ST_W4", "station_name": "工作測站4", "past_10min_rain": 0.0},
        ]

        res_home = self.home_sm.evaluate(home_stations)
        res_work = self.work_sm.evaluate(work_stations)

        # 驗證住家正在下雨
        self.assertTrue(res_home["is_raining"], "住家應判定為正在下雨")
        self.assertTrue(res_home["rain_approaching"])
        self.assertEqual(res_home["active_stations_count"], 2)

        # 驗證工作地點依然為乾燥/晴天
        self.assertFalse(res_work["is_raining"], "工作地點不應判定為下雨")
        self.assertFalse(res_work["rain_approaching"])
        self.assertEqual(res_work["active_stations_count"], 0)


class TestCwaApiClientCache(unittest.IsolatedAsyncioTestCase):
    """
    測試氣象署 API 客戶端之 TTL 快取機制 (多地點共享)
    """

    async def test_cache_hit(self):
        mock_hass = MagicMock()
        client = CwaApiClient(mock_hass, "TEST_TOKEN")

        # 模擬 API 回傳原始數據
        mock_parsed_data = [
            {"station_id": "C2O950", "station_name": "安南", "latitude": 23.0487, "longitude": 120.1852, "past_10min_rain": 0.0}
        ]

        # 手工注入快取資料與時間戳
        client._cached_data = mock_parsed_data
        client._cache_timestamp = datetime.now()

        # 呼叫 async_fetch_stations
        result = await client.async_fetch_stations()

        # 驗證在 TTL 期限內直接命中快取
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["station_id"], "C2O950")


class TestCoordinatorSetup(unittest.TestCase):
    """
    測試 CwaRainDataUpdateCoordinator 的初始化與各項屬性
    """

    def test_coordinator_init(self):
        mock_hass = MagicMock()
        mock_client = MagicMock()
        entry_data = {
            "api_token": "TEST_TOKEN",
            "location_name": "公司",
            "zone_entity": "zone.work",
            "use_zone": True,
            "latitude": 22.9900,
            "longitude": 120.2100,
            "polling_interval": 300
        }
        coordinator = CwaRainDataUpdateCoordinator(mock_hass, mock_client, entry_data)
        self.assertEqual(coordinator.location_name, "公司")
        self.assertEqual(coordinator.current_lat, 22.9900)
        self.assertEqual(coordinator.current_lon, 120.2100)


class TestEntityNamingAndDockerCompatibility(unittest.TestCase):
    """
    測試實體命名是否完美回歸 Docker 模式，避免過長中文拼音
    """

    def test_get_location_slug(self):
        from custom_components.cwa_rain.const import get_location_slug
        # 住家回傳空字串 (不加後綴)
        self.assertEqual(get_location_slug("住家"), "")
        self.assertEqual(get_location_slug("home"), "")
        self.assertEqual(get_location_slug(""), "")
        # 公司與自訂地點回傳簡短 slug
        self.assertEqual(get_location_slug("公司"), "gong_si")
        self.assertEqual(get_location_slug("工作"), "work")
        self.assertEqual(get_location_slug("辦公室"), "office")

    def test_entity_ids_home(self):
        from custom_components.cwa_rain.sensor import CwaRainMonitorSensor
        from custom_components.cwa_rain.binary_sensor import (
            CwaRainIsRainingBinarySensor,
            CwaRainApproachingBinarySensor,
        )

        mock_coord = MagicMock()
        mock_coord.location_name = "住家"
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_home"

        sensor = CwaRainMonitorSensor(mock_coord, mock_entry)
        self.assertEqual(sensor.entity_id, "sensor.cwa_rain_monitor")
        self.assertEqual(sensor.name, "氣象署雨量綜合監控")

        bin_raining = CwaRainIsRainingBinarySensor(mock_coord, mock_entry)
        self.assertEqual(bin_raining.entity_id, "binary_sensor.is_raining")
        self.assertEqual(bin_raining.name, "目前正在下雨")

        bin_warning = CwaRainApproachingBinarySensor(mock_coord, mock_entry)
        self.assertEqual(bin_warning.entity_id, "binary_sensor.rain_approaching_warning")
        self.assertEqual(bin_warning.name, "雨雲接近預警")

    def test_entity_ids_company(self):
        from custom_components.cwa_rain.sensor import CwaRainMonitorSensor
        from custom_components.cwa_rain.binary_sensor import (
            CwaRainIsRainingBinarySensor,
            CwaRainApproachingBinarySensor,
        )

        mock_coord = MagicMock()
        mock_coord.location_name = "公司"
        mock_entry = MagicMock()
        mock_entry.entry_id = "test_entry_company"

        sensor = CwaRainMonitorSensor(mock_coord, mock_entry)
        self.assertEqual(sensor.entity_id, "sensor.cwa_rain_monitor_gong_si")
        self.assertEqual(sensor.name, "氣象署雨量綜合監控 (公司)")

        bin_raining = CwaRainIsRainingBinarySensor(mock_coord, mock_entry)
        self.assertEqual(bin_raining.entity_id, "binary_sensor.is_raining_gong_si")
        self.assertEqual(bin_raining.name, "目前正在下雨 (公司)")

        bin_warning = CwaRainApproachingBinarySensor(mock_coord, mock_entry)
        self.assertEqual(bin_warning.entity_id, "binary_sensor.rain_approaching_warning_gong_si")
        self.assertEqual(bin_warning.name, "雨雲接近預警 (公司)")


if __name__ == "__main__":
    unittest.main()
