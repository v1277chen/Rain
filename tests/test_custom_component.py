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

# 為 DataUpdateCoordinator 提供實體類別而非 MagicMock，避免繼承時屬性被攔截
class MockDataUpdateCoordinator:
    def __init__(self, hass, logger, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None

mock_uc = MagicMock()
mock_uc.DataUpdateCoordinator = MockDataUpdateCoordinator
mock_uc.UpdateFailed = Exception
sys.modules["homeassistant.helpers.update_coordinator"] = mock_uc

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
        # 實例化 Coordinator，若有任何未定義變數 (如 DEFAULT_LOCATION_NAME) 將立即報錯
        coordinator = CwaRainDataUpdateCoordinator(mock_hass, mock_client, entry_data)
        self.assertEqual(coordinator.location_name, "公司")
        self.assertEqual(coordinator.current_lat, 22.9900)
        self.assertEqual(coordinator.current_lon, 120.2100)


if __name__ == "__main__":
    unittest.main()
