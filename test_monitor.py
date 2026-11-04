#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
中央氣象署雨量監控服務 - 單元測試與模擬驗證腳本
檔案名稱：test_monitor.py
功能簡述：
    1. 驗證 Haversine 大圓球面距離運算。
    2. 驗證 Marshall-Palmer 雨量反推雷達迴波 (dBZ) 模型。
    3. 模擬全降雨生活情境，驗證防抖動 (Debounce) 與磁滯冷卻機制。
    4. 驗證測站資料提取與容錯能力。
==============================================================================
"""

import unittest
import math
from cwa_ha_rain_monitor import (
    haversine_distance,
    calculate_estimated_dbz,
    CwaRainDataFetcher,
    StationEvaluator,
    RainDebounceStateMachine
)


class TestRainMonitorPhysics(unittest.TestCase):
    """
    測試地球物理距離公式與氣象經驗公式
    """

    def test_haversine_distance(self):
        """
        測試 Haversine 公式計算經緯度大圓距離。
        測試座標：
            住家 (臺南市安南區約 23.0150, 120.2050)
            臺南市北區測站 (約 23.0039, 120.2183)
            距離應落在 1 ~ 3 公里之間。
        """
        dist = haversine_distance(23.0150, 120.2050, 23.0039, 120.2183)
        self.assertGreater(dist, 1.0)
        self.assertLess(dist, 3.0)

        # 兩點相同時，距離應為 0
        dist_zero = haversine_distance(23.0, 120.0, 23.0, 120.0)
        self.assertEqual(dist_zero, 0.0)

    def test_calculate_estimated_dbz(self):
        """
        測試過去 10 分鐘雨量反推雷達迴波強度 (dBZ)。
        """
        # 無降雨時 dBZ 應為 0.0
        self.assertEqual(calculate_estimated_dbz(0.0), 0.0)
        self.assertEqual(calculate_estimated_dbz(-1.0), 0.0)

        # 過去 10 分鐘 0.5 mm -> 小時雨量 3.0 mm/hr
        # Z = 200 * (3.0 ^ 1.6) ≈ 1157.07
        # 10 * log10(1157.07) ≈ 30.6 dBZ (一般對應黃綠色弱降水)
        dbz_05 = calculate_estimated_dbz(0.5)
        self.assertAlmostEqual(dbz_05, 30.6, delta=0.5)

        # 過去 10 分鐘 2.0 mm -> 小時雨量 12.0 mm/hr
        # Z = 200 * (12.0 ^ 1.6) ≈ 10672.4
        # 10 * log10(10672.4) ≈ 40.3 dBZ (對應黃橙色中強降雨)
        dbz_20 = calculate_estimated_dbz(2.0)
        self.assertAlmostEqual(dbz_20, 40.3, delta=0.5)


class TestStationExtractor(unittest.TestCase):
    """
    測試資料解析與容錯處理
    """

    def test_extract_station_info_normal(self):
        """
        測試標準 API 結構解析
        """
        mock_raw = {
            "StationId": "C0X100",
            "StationName": "臺南市北區",
            "GeoInfo": {
                "Coordinates": [
                    {
                        "CoordinateName": "WGS84",
                        "StationLatitude": 23.0039,
                        "StationLongitude": 120.2183
                    }
                ]
            },
            "RainfallElement": {
                "Past10Min": {"Precipitation": "1.5"}
            }
        }
        res = CwaRainDataFetcher.extract_station_info(mock_raw)
        self.assertIsNotNone(res)
        self.assertEqual(res["station_id"], "C0X100")
        self.assertEqual(res["station_name"], "臺南市北區")
        self.assertEqual(res["past_10min_rain"], 1.5)
        self.assertAlmostEqual(res["latitude"], 23.0039)
        self.assertAlmostEqual(res["longitude"], 120.2183)

    def test_extract_station_info_anomaly(self):
        """
        測試異常值 -99 (故障) 與 -998 (微雨) 是否正確歸零
        """
        mock_raw = {
            "StationId": "C2O950",
            "StationName": "安南",
            "RainfallElement": {
                "Past10Min": {"Precipitation": -99.0}
            }
        }
        res = CwaRainDataFetcher.extract_station_info(mock_raw)
        self.assertIsNotNone(res)
        self.assertEqual(res["past_10min_rain"], 0.0)


class TestRainDebounceStateMachine(unittest.TestCase):
    """
    測試狀態機之防抖動 (Debounce) 與磁滯冷卻行為
    """

    def setUp(self):
        # 門檻：單站有雨 0.1mm，2站有雨認定下雨，單站 1.5mm 驟雨立即觸發
        # 連續 1 次 ON，連續 3 次無雨才 OFF
        self.sm = RainDebounceStateMachine(
            rain_detected_mm=0.1,
            stations_rain_count=2,
            heavy_rain_single_station_mm=1.5,
            debounce_on_count=1,
            debounce_off_count=3
        )

    def create_mock_stations(self, r1: float, r2: float, r3: float, r4: float):
        return [
            {"station_id": "C2O950", "station_name": "安南", "past_10min_rain": r1, "distance_km": 1.2},
            {"station_id": "C0X100", "station_name": "臺南市北區", "past_10min_rain": r2, "distance_km": 2.1},
            {"station_id": "467420", "station_name": "永康", "past_10min_rain": r3, "distance_km": 4.5},
            {"station_id": "C0X150", "station_name": "安定", "past_10min_rain": r4, "distance_km": 5.8},
        ]

    def test_full_scenario_simulation(self):
        """
        完整情境模擬：
        T0: 全晴天 (0,0,0,0) -> 均為 False
        T1: 雨雲接近，僅 1 站微雨 (0.2, 0, 0, 0) -> is_raining=False, rain_approaching=True
        T2: 2 站有雨 (0.5, 0.3, 0, 0) -> is_raining=True, rain_approaching=True
        T3: 間歇停雨 1 週期 (0, 0, 0, 0) -> 防抖動生效，is_raining 仍應維持 True！
        T4: 間歇停雨 2 週期 (0, 0, 0, 0) -> 防抖動生效，is_raining 仍應維持 True！
        T5: 第 3 週期仍無雨 (0, 0, 0, 0) -> 達 3 次門檻，is_raining 轉 False, rain_approaching 轉 False
        T6: 突發單站暴雨 (0, 2.0, 0, 0) -> 觸發單站大雨判定，is_raining 立即轉 True
        """
        # T0: 全晴天
        res0 = self.sm.evaluate(self.create_mock_stations(0.0, 0.0, 0.0, 0.0))
        self.assertFalse(res0["is_raining"])
        self.assertFalse(res0["rain_approaching"])
        self.assertEqual(res0["max_rain_10min"], 0.0)

        # T1: 1 站微雨 -> 雨雲接近預警觸發，但尚未判定正在下雨
        res1 = self.sm.evaluate(self.create_mock_stations(0.2, 0.0, 0.0, 0.0))
        self.assertFalse(res1["is_raining"], "僅1站微雨不應觸發正在下雨")
        self.assertTrue(res1["rain_approaching"], "1站有雨應觸發雨雲接近預警")

        # T2: 2 站有雨 -> 觸發正在下雨
        res2 = self.sm.evaluate(self.create_mock_stations(0.5, 0.3, 0.0, 0.0))
        self.assertTrue(res2["is_raining"], "2站達標應觸發正在下雨")
        self.assertTrue(res2["rain_approaching"])

        # T3: 突然 1 週期無雨 -> 測試防抖動，不可立即變 False
        res3 = self.sm.evaluate(self.create_mock_stations(0.0, 0.0, 0.0, 0.0))
        self.assertTrue(res3["is_raining"], "防抖動第1次停雨，狀態應維持 True")
        self.assertEqual(res3["consecutive_dry_cycles"], 1)
        self.assertEqual(res3["cooldown_remaining_cycles"], 2)

        # T4: 第 2 週期依然無雨 -> 防抖動繼續保持
        res4 = self.sm.evaluate(self.create_mock_stations(0.0, 0.0, 0.0, 0.0))
        self.assertTrue(res4["is_raining"], "防抖動第2次停雨，狀態應維持 True")
        self.assertEqual(res4["consecutive_dry_cycles"], 2)
        self.assertEqual(res4["cooldown_remaining_cycles"], 1)

        # T5: 第 3 週期依然無雨 -> 累積 3 週期達到冷卻門檻，轉為 False
        res5 = self.sm.evaluate(self.create_mock_stations(0.0, 0.0, 0.0, 0.0))
        self.assertFalse(res5["is_raining"], "已達連續3週期無雨，應轉為 False")
        self.assertFalse(res5["rain_approaching"], "已完全冷卻停雨，預警亦應解除")

        # T6: 單站驟雨 (單站 2.0mm，其餘 0.0mm) -> 立即觸發正在下雨
        res6 = self.sm.evaluate(self.create_mock_stations(0.0, 2.0, 0.0, 0.0))
        self.assertTrue(res6["is_raining"], "單站達 2.0mm 應立即判定為正在下雨")
        self.assertTrue(res6["rain_approaching"])
        self.assertEqual(res6["max_rain_10min"], 2.0)
        self.assertGreater(res6["estimated_dbz"], 35.0)


class TestAutoStationSelection(unittest.TestCase):
    """
    測試自動距離模式 (auto) 與住家經緯度動態切換測站功能
    """

    def setUp(self):
        # 建立模擬的全台/跨區域測站資料
        self.mock_all_stations = [
            # 臺南地區測站
            {"station_id": "C2O950", "station_name": "安南", "latitude": 23.0475, "longitude": 120.1831, "past_10min_rain": 0.0},
            {"station_id": "C0X100", "station_name": "臺南市北區", "latitude": 23.0039, "longitude": 120.2183, "past_10min_rain": 0.0},
            {"station_id": "467420", "station_name": "永康", "latitude": 23.0384, "longitude": 120.2359, "past_10min_rain": 0.0},
            {"station_id": "C0X150", "station_name": "安定", "latitude": 23.1064, "longitude": 120.2347, "past_10min_rain": 0.0},
            {"station_id": "C0X110", "station_name": "善化", "latitude": 23.1342, "longitude": 120.2975, "past_10min_rain": 0.0},
            # 高雄地區測站
            {"station_id": "467440", "station_name": "高雄", "latitude": 22.5660, "longitude": 120.3157, "past_10min_rain": 0.0},
            {"station_id": "C0V730", "station_name": "左營", "latitude": 22.6853, "longitude": 120.2968, "past_10min_rain": 0.0},
            {"station_id": "C0V740", "station_name": "楠梓", "latitude": 22.7291, "longitude": 120.3242, "past_10min_rain": 0.0},
            {"station_id": "C0V680", "station_name": "鳳山", "latitude": 22.6289, "longitude": 120.3575, "past_10min_rain": 0.0},
        ]

    def test_auto_selection_tainan(self):
        """
        住家位於臺南安南區 (23.0150, 120.2050) 時，自動模式應挑選臺南的 4 站
        """
        evaluator = StationEvaluator(home_lat=23.0150, home_lon=120.2050, mode="auto")
        selected = evaluator.select_four_stations(self.mock_all_stations)

        self.assertEqual(len(selected), 4)
        selected_ids = [s["station_id"] for s in selected]

        # 臺南最近的 4 站應為 安南、北區、永康、安定
        self.assertIn("C2O950", selected_ids)
        self.assertIn("C0X100", selected_ids)
        self.assertIn("467420", selected_ids)
        self.assertIn("C0X150", selected_ids)
        # 高雄的測站不應該出現在前 4 名
        self.assertNotIn("467440", selected_ids)

        # 檢查距離由近到遠排序
        distances = [s["distance_km"] for s in selected]
        self.assertEqual(distances, sorted(distances))

    def test_dynamic_location_update(self):
        """
        測試當住家座標動態更新至高雄 (22.6900, 120.3000) 時，測站會自動動態換成高雄最近 4 站
        """
        evaluator = StationEvaluator(home_lat=23.0150, home_lon=120.2050, mode="auto")
        # 初始在臺南
        evaluator.select_four_stations(self.mock_all_stations)

        # 模擬住家搬家或 HA zone.home 座標更新至高雄楠梓/左營附近
        moved = evaluator.update_home_location(new_lat=22.6900, new_lon=120.3000)
        self.assertTrue(moved, "座標改變時 update_home_location 應回傳 True")

        # 重新評估測站
        new_selected = evaluator.select_four_stations(self.mock_all_stations)
        new_selected_ids = [s["station_id"] for s in new_selected]

        # 高雄左營、楠梓應在最近 4 站中
        self.assertIn("C0V730", new_selected_ids)
        self.assertIn("C0V740", new_selected_ids)
        # 原本臺南的安定、善化不應在高雄前 4 站中
        self.assertNotIn("C0X150", new_selected_ids)
        self.assertNotIn("C0X110", new_selected_ids)


if __name__ == "__main__":
    unittest.main()

