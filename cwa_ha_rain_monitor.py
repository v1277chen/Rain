#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
中央氣象署 (CWA) 雨量觀測資料整合至 Home Assistant 監控服務
檔案名稱：cwa_ha_rain_monitor.py
作者：Antigravity
功能簡述：
    1. 介接氣象署 O-A0002-001 (自動雨量站觀測資料) REST API。
    2. 使用 Haversine 公式計算住家至各測站之大圓球面距離。
    3. 支援鎖定指定測站（安南、臺南市北區、永康、安定）或依距離動態選取最近 4 站。
    4. 讀取各測站「過去 10 分鐘累積降水量 (Past10Min)」。
    5. 彙整最大雨量值、多站投票邏輯與單站驟雨判定。
    6. 採用 Marshall-Palmer 氣象公式粗略反推雷達迴波強度 (dBZ)。
    7. 具備連續判定防抖動 (Debounce) 與磁滯冷卻 (Hysteresis) 機制，
       精準切換 Home Assistant 之 input_boolean 與感測器狀態。
==============================================================================
"""

import sys
import os
import math
import time
import json
import logging
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime

# 嘗試載入 requests 與 yaml 套件，若未安裝則提示使用者
try:
    import requests
except ImportError:
    print("【錯誤】未安裝 requests 套件，請執行：pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("【錯誤】未安裝 pyyaml 套件，請執行：pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# 設定日誌記錄格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("RainMonitor")


# ==============================================================================
# 第一部分：數學與氣象物理模型工具函式
# ==============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    計算地球表面兩點經緯度之間的大圓距離 (Great-circle distance)。

    計算公式：
        a = sin²(Δφ / 2) + cos(φ1) * cos(φ2) * sin²(Δλ / 2)
        c = 2 * atan2(√a, √(1−a))
        d = R * c

    參數說明：
        lat1 (float): 起點緯度 (單位：十進制度數 Decimal Degrees)。
        lon1 (float): 起點經度 (單位：十進制度數 Decimal Degrees)。
        lat2 (float): 終點緯度 (單位：十進制度數 Decimal Degrees)。
        lon2 (float): 終點經度 (單位：十進制度數 Decimal Degrees)。

    回傳值：
        float: 兩點間之地面直線球面距離 (單位：公里 km)，四捨五入至小數點後第 2 位。
    """
    # 地球平均半徑 (公里)
    earth_radius_km: float = 6371.0

    # 將十進制度數轉換為弧度
    rad_lat1: float = math.radians(lat1)
    rad_lat2: float = math.radians(lat2)
    delta_lat: float = math.radians(lat2 - lat1)
    delta_lon: float = math.radians(lon2 - lon1)

    # 套用 Haversine 演算法
    a: float = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(rad_lat1) * math.cos(rad_lat2) * (math.sin(delta_lon / 2.0) ** 2)
    )
    c: float = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    distance: float = earth_radius_km * c

    return round(distance, 2)


def calculate_estimated_dbz(past_10min_rain_mm: float) -> float:
    """
    依據過去 10 分鐘累積雨量 (mm)，反推雷達迴波強度估計值 (dBZ)。

    計算原理：
        1. 等效小時雨量降水率 R (mm/hr) = 過去 10 分鐘降水量 * 6。
        2. 套用氣象學經典 Marshall-Palmer 關係式：Z = 200 * (R ^ 1.6)。
        3. 雷達迴波強度定義：dBZ = 10 * log10(Z)。
        4. 當 R <= 0 或無降雨時，dBZ 回傳 0.0。
        5. 限制合理物理上限至 70.0 dBZ。

    參數說明：
        past_10min_rain_mm (float): 過去 10 分鐘累積雨量 (單位：毫米 mm)。

    回傳值：
        float: 反推之估計雷達迴波強度 (單位：dBZ)，取小數點後第 1 位。
    """
    if past_10min_rain_mm <= 0.0:
        return 0.0

    # 換算為等效小時降水率 R (mm/hr)
    rainfall_rate_mm_per_hr: float = past_10min_rain_mm * 6.0

    # 極小微量雨滴保護 (避免 log 產生負無窮大或極小負值)
    if rainfall_rate_mm_per_hr < 0.05:
        return 15.0  # 約略代表雲層微雨邊緣之反射率

    try:
        # Z-R 經驗公式 (Marshall & Palmer, 1948)
        # Z = 200 * (R ** 1.6)
        # dBZ = 10 * log10(Z) = 10 * (log10(200) + 1.6 * log10(R))
        z_factor: float = 200.0 * (rainfall_rate_mm_per_hr ** 1.6)
        dbz: float = 10.0 * math.log10(z_factor)
        # 限制在氣象雷達合理常態範圍 0.0 ~ 70.0 dBZ
        dbz_clamped: float = max(0.0, min(70.0, dbz))
        return round(dbz_clamped, 1)
    except (ValueError, OverflowError):
        return 0.0


# ==============================================================================
# 第二部分：中央氣象署 (CWA) API 資料抓取與解析模組
# ==============================================================================

class CwaRainDataFetcher:
    """
    負責與中央氣象署開放資料平台介接，抓取自動雨量站資料 (O-A0002-001) 並解析。
    """

    def __init__(self, api_token: str, dataset_id: str = "O-A0002-001", timeout: int = 15):
        """
        初始化 CwaRainDataFetcher 物件。

        參數說明：
            api_token (str): 氣象署開放資料平台授權碼。
            dataset_id (str): 資料集代碼，預設為 "O-A0002-001"。
            timeout (int): HTTP 連線超時時間 (秒)。
        """
        self.api_token: str = api_token
        self.dataset_id: str = dataset_id
        self.timeout: int = timeout
        self.base_url: str = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{self.dataset_id}"

    def fetch_raw_stations(self) -> List[Dict[str, Any]]:
        """
        向中央氣象署 API 發送 GET 請求，取得所有自動雨量站之觀測原始資料。

        回傳值：
            List[Dict[str, Any]]: 包含各測站資訊之原始字典列表。若失敗則回傳空列表。
        """
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-CWARainMonitor/1.0"
        }
        params = {
            "Authorization": self.api_token
        }

        try:
            logger.info("正在連線氣象署 API (資料集: %s) 抓取雨量資料...", self.dataset_id)
            response = requests.get(self.base_url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            if not data.get("success") or str(data.get("success")).lower() != "true":
                logger.error("氣象署 API 回應狀態非 success: %s", data.get("message", "無訊息"))
                return []

            # 相容新舊版欄位結構 (新版為 records.Station，舊版或部分規格為 records.location)
            records = data.get("records", {})
            stations = records.get("Station") or records.get("location") or []
            logger.info("成功抓取氣象署資料，共取得 %d 個測站記錄", len(stations))
            return stations

        except requests.exceptions.RequestException as exc:
            logger.error("連線氣象署 API 時發生網路例外錯誤: %s", exc)
            return []
        except json.JSONDecodeError as exc:
            logger.error("解析氣象署 API 回傳之 JSON 時失敗: %s", exc)
            return []

    @staticmethod
    def extract_station_info(station_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        從單一測站的原始資料字典中，標準化提取測站編號、名稱、經緯度及過去 10 分鐘雨量。

        特別處理規則：
            - 氣象署常以 -99.0 代表儀器故障/無資料，-998.0 代表微量降雨 (<0.1mm)。
            - 本函式將負數異常值過濾歸零，確保運算穩定。

        參數說明：
            station_dict (Dict[str, Any]): 氣象署 API 回傳之單一測站原始字典資料。

        回傳值：
            Optional[Dict[str, Any]]: 標準化後之測站字典，若解析失敗則回傳 None。
        """
        try:
            # 1. 測站 ID 與名稱
            station_id: str = station_dict.get("StationId") or station_dict.get("stationId", "")
            station_name: str = station_dict.get("StationName") or station_dict.get("locationName", "")

            # 2. 經緯度解析 (支援 Coordinates 陣列或直接欄位)
            lat: float = 0.0
            lon: float = 0.0
            geo_info = station_dict.get("GeoInfo", {})
            coordinates = geo_info.get("Coordinates", [])
            if coordinates and isinstance(coordinates, list):
                for coord in coordinates:
                    if coord.get("CoordinateName") == "WGS84" or "StationLatitude" in coord:
                        lat = float(coord.get("StationLatitude", 0.0))
                        lon = float(coord.get("StationLongitude", 0.0))
                        break
            if lat == 0.0 and lon == 0.0:
                # 備用語意解析 (舊版格式)
                lat = float(station_dict.get("lat") or station_dict.get("StationLatitude") or 0.0)
                lon = float(station_dict.get("lon") or station_dict.get("StationLongitude") or 0.0)

            # 3. 過去 10 分鐘雨量 Past10Min 解析
            past_10min: float = 0.0
            rainfall_elem = station_dict.get("RainfallElement", {})

            if "Past10Min" in rainfall_elem:
                raw_val = rainfall_elem["Past10Min"].get("Precipitation", 0.0)
                past_10min = float(raw_val)
            else:
                # 舊版 weatherElement 列表解析備援
                weather_elements = station_dict.get("weatherElement", [])
                for elem in weather_elements:
                    name = elem.get("elementName", "")
                    if name in ["PAST_10_MIN", "MIN_10", "Now"]:
                        val_str = elem.get("elementValue", {}).get("value", "0.0")
                        past_10min = float(val_str)
                        break

            # 異常值過濾：氣象署 -99 代表故障，-998 代表雨跡(微量)
            if past_10min < 0:
                past_10min = 0.0

            return {
                "station_id": str(station_id).strip(),
                "station_name": str(station_name).strip(),
                "latitude": lat,
                "longitude": lon,
                "past_10min_rain": round(past_10min, 2)
            }

        except Exception as exc:
            logger.debug("解析測站資料結構異常: %s (內容: %s)", exc, station_dict)
            return None


# ==============================================================================
# 第三部分：測站評估與距離篩選模組
# ==============================================================================

class StationEvaluator:
    """
    負責計算測站距離並挑選目標 4 站進行雨量統計。
    支援鎖定特定測站 (fixed) 與依離家距離自動挑選最近 4 站 (auto) 模式。
    """

    def __init__(self, home_lat: float, home_lon: float, mode: str = "fixed",
                 target_stations: Optional[List[Dict[str, str]]] = None):
        """
        初始化測站評估器。

        參數說明：
            home_lat (float): 住家緯度。
            home_lon (float): 住家經度。
            mode (str): 篩選模式，'fixed' 為鎖定指定清單，'auto' 為動態抓取最近 4 站。
            target_stations (Optional[List[Dict[str, str]]]): 指定之測站代碼與名稱清單。
        """
        self.home_lat: float = home_lat
        self.home_lon: float = home_lon
        self.mode: str = mode.lower()
        self.target_stations: List[Dict[str, str]] = target_stations or []
        self.target_station_ids: set = {s["id"] for s in self.target_stations}
        # 記錄前一次選取的 4 座測站 ID 列表，用於比對是否有站點更換
        self.current_station_ids: List[str] = []

    def update_home_location(self, new_lat: float, new_lon: float) -> bool:
        """
        動態更新住家經緯度座標。

        用途說明：
            當從 Home Assistant 的 zone.home 或外部設定檔偵測到住家座標變更時呼叫此函式。
            若座標確有變動，則更新內部數值並回傳 True，觸發測站重新評估。

        參數說明：
            new_lat (float): 新的住家緯度。
            new_lon (float): 新的住家經度。

        回傳值：
            bool: 若經緯度與原數值不同且數值有效則回傳 True，否則回傳 False。
        """
        if new_lat == 0.0 and new_lon == 0.0:
            return False

        # 以小數點後 4 位（精度約 11 公尺）判定是否有位移
        if round(self.home_lat, 4) != round(new_lat, 4) or round(self.home_lon, 4) != round(new_lon, 4):
            logger.info("【住家位置變更】緯度: %.4f -> %.4f | 經度: %.4f -> %.4f",
                        self.home_lat, new_lat, self.home_lon, new_lon)
            self.home_lat = new_lat
            self.home_lon = new_lon
            return True
        return False

    def select_four_stations(self, all_stations_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        依據模式挑選出 4 個監控測站，並計算各站離住家之 Haversine 距離。
        當模式為 'auto' 時，會自動由全台測站中計算距離並挑選最近 4 站；
        若偵測到挑選之測站清單異動，會記錄日誌提醒使用者。

        參數說明：
            all_stations_data (List[Dict[str, Any]]): 氣象署標準化後之所有測站資訊列表。

        回傳值：
            List[Dict[str, Any]]: 排序後之 4 個目標測站詳細資訊清單 (含 distance_km)。
        """
        stations_with_dist: List[Dict[str, Any]] = []

        for st in all_stations_data:
            st_id = st["station_id"]
            st_lat = st["latitude"]
            st_lon = st["longitude"]

            # 若座標有效則計算與家距離，若為 0 則預設一個大數字
            if st_lat > 0 and st_lon > 0:
                dist = haversine_distance(self.home_lat, self.home_lon, st_lat, st_lon)
            else:
                dist = 999.9

            st_copy = dict(st)
            st_copy["distance_km"] = dist
            stations_with_dist.append(st_copy)

        # 模式判定
        if self.mode == "fixed" and self.target_station_ids:
            # 僅保留指定代碼清單內的測站
            selected = [s for s in stations_with_dist if s["station_id"] in self.target_station_ids]
            # 依離家距離由近到遠排序
            selected.sort(key=lambda x: x["distance_km"])
            result = selected[:4]
            logger.info("【固定測站模式】鎖定指定測站，已依距離排序取得 %d 站", len(result))
        else:
            # 動態模式：排除無經緯度或異常之測站 (例如距離 > 900 km)，依離家距離由近到遠排序取最近 4 站
            valid_stations = [s for s in stations_with_dist if s["distance_km"] < 900.0]
            valid_stations.sort(key=lambda x: x["distance_km"])
            result = valid_stations[:4]
            logger.info("【自動距離模式】已依據目前住家座標 (%.4f, %.4f) 自動挑選距離最近的 4 座測站",
                        self.home_lat, self.home_lon)

        # 檢查測站組合是否有更換
        new_ids = [s["station_id"] for s in result]
        if self.current_station_ids and new_ids != self.current_station_ids:
            old_names = self.current_station_ids
            new_names = [f"{s['station_name']}({s['station_id']})" for s in result]
            logger.warning("【測站清單異動】監控目標測站已變更！目前最新 4 站：%s", ", ".join(new_names))
        self.current_station_ids = new_ids

        return result


# ==============================================================================
# 第四部分：降雨判定與雙開關防抖動 (Debounce) 狀態機
# ==============================================================================

class RainDebounceStateMachine:
    """
    雨量判定與防抖動狀態機。
    負責維護「正在下雨 (is_raining)」與「雨雲接近預警 (rain_approaching)」兩組開關狀態，
    避免短暫微雨停歇或測站資料抖動造成頻繁開關。
    """

    def __init__(
        self,
        rain_detected_mm: float = 0.1,
        stations_rain_count: int = 2,
        heavy_rain_single_station_mm: float = 1.5,
        debounce_on_count: int = 1,
        debounce_off_count: int = 3
    ):
        """
        初始化狀態機。

        參數說明：
            rain_detected_mm (float): 單站認定有雨之最低雨量 (mm)。
            stations_rain_count (int): 一般降雨時，需達到有雨之最少測站數量 (預設: 2)。
            heavy_rain_single_station_mm (float): 單站認定大雨/驟雨之門檻 (mm)。
            debounce_on_count (int): 轉為 ON 所需連續滿足次數 (預設: 1，快速反應)。
            debounce_off_count (int): 轉為 OFF 所需連續無雨冷卻次數 (例如 3 次 = 15 分鐘)。
        """
        self.rain_detected_mm: float = rain_detected_mm
        self.stations_rain_count: int = stations_rain_count
        self.heavy_rain_single_station_mm: float = heavy_rain_single_station_mm
        self.debounce_on_count: int = debounce_on_count
        self.debounce_off_count: int = debounce_off_count

        # 狀態機內部狀態變數
        self.is_raining: bool = False
        self.rain_approaching: bool = False

        # 連續計數器
        self.consecutive_rain_detected_cycles: int = 0
        self.consecutive_dry_cycles: int = 0

    def evaluate(self, selected_stations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        輸入 4 個目標測站資料，執行降雨條件判定與防抖動狀態更新。

        判定邏輯：
            1. 統計雨量 >= rain_detected_mm 的測站數 (active_rain_stations_count)。
            2. 取得 4 站中過去 10 分鐘最大雨量 (max_rain_10min)。
            3. 當次降雨觸發 (raw_rain_trigger)：
               - 條件 A：active_rain_stations_count >= stations_rain_count (至少 2 站有雨)
               - 條件 B：max_rain_10min >= heavy_rain_single_station_mm (單站雨量夠大)
            4. 防抖動計算：
               - 若 raw_rain_trigger 為 True：連續雨天計數累加，連續乾燥計數歸零。
                 當連續雨天計數 >= debounce_on_count 時，is_raining 設為 True。
               - 若 raw_rain_trigger 為 False：連續乾燥計數累加，連續雨天計數歸零。
                 當連續乾燥計數 >= debounce_off_count 時，is_raining 設為 False。
            5. 雨雲接近預警 (rain_approaching)：
               - 條件：至少有一站有雨 (active_rain_stations_count >= 1) 或正在下雨 (is_raining == True)。
               - 解除：只有在所有站皆無雨且冷卻期滿時才轉為 False。

        參數說明：
            selected_stations (List[Dict[str, Any]]): 4 個目標測站資料清單。

        回傳值：
            Dict[str, Any]: 彙整後之狀態評估結果字典。
        """
        # 標註各站是否有雨
        active_stations_count: int = 0
        max_rain_10min: float = 0.0

        for st in selected_stations:
            rain = st.get("past_10min_rain", 0.0)
            if rain > max_rain_10min:
                max_rain_10min = rain
            is_st_raining = rain >= self.rain_detected_mm
            st["is_raining"] = is_st_raining
            if is_st_raining:
                active_stations_count += 1

        # 當前即時條件判定
        two_stations_rain: bool = (active_stations_count >= self.stations_rain_count)
        single_station_heavy: bool = (max_rain_10min >= self.heavy_rain_single_station_mm)
        raw_rain_trigger: bool = two_stations_rain or single_station_heavy

        # 防抖動邏輯計算
        if raw_rain_trigger:
            self.consecutive_rain_detected_cycles += 1
            self.consecutive_dry_cycles = 0
            if self.consecutive_rain_detected_cycles >= self.debounce_on_count:
                self.is_raining = True
        else:
            self.consecutive_dry_cycles += 1
            self.consecutive_rain_detected_cycles = 0
            # 磁滯防抖動：必須連續 N 個週期無雨才關閉下雨狀態
            if self.consecutive_dry_cycles >= self.debounce_off_count:
                self.is_raining = False

        # 雨雲接近預警 (rain_approaching) 判定
        # 條件：至少 1 站有雨，或目前仍判定為正在下雨
        if active_stations_count >= 1 or self.is_raining:
            self.rain_approaching = True
        else:
            # 當所有測站無雨且乾燥冷卻週期達到時才關閉預警
            if self.consecutive_dry_cycles >= self.debounce_off_count:
                self.rain_approaching = False

        # 反推雷達迴波估計值
        estimated_dbz: float = calculate_estimated_dbz(max_rain_10min)

        # 計算離解除停雨還需要幾次輪詢
        dry_cycles_remaining = max(0, self.debounce_off_count - self.consecutive_dry_cycles) if self.is_raining else 0

        summary = {
            "max_rain_10min": max_rain_10min,
            "estimated_dbz": estimated_dbz,
            "active_stations_count": active_stations_count,
            "raw_rain_trigger": raw_rain_trigger,
            "is_raining": self.is_raining,
            "rain_approaching": self.rain_approaching,
            "consecutive_rain_cycles": self.consecutive_rain_detected_cycles,
            "consecutive_dry_cycles": self.consecutive_dry_cycles,
            "cooldown_remaining_cycles": dry_cycles_remaining,
            "stations_detail": selected_stations,
            "timestamp": datetime.now().isoformat()
        }

        return summary


# ==============================================================================
# 第五部分：Home Assistant REST API 連動模組
# ==============================================================================

class HomeAssistantSync:
    """
    負責將雨量監控與預警結果透過 REST API 寫入 Home Assistant 實體中。
    """

    def __init__(self, base_url: str, access_token: str, entities_config: Dict[str, str], enabled: bool = True):
        """
        初始化 Home Assistant 同步器。

        參數說明：
            base_url (str): Home Assistant 服務端點 URL (例如: http://homeassistant.local:8123)。
            access_token (str): 長效存取權杖 (Long-Lived Access Token)。
            entities_config (Dict[str, str]): 實體代碼對應設定。
            enabled (bool): 是否真正發送 HTTP 請求 (除錯模式可關閉)。
        """
        self.base_url: str = base_url.rstrip("/")
        self.access_token: str = access_token
        self.entities_config: Dict[str, str] = entities_config
        self.enabled: bool = enabled
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def fetch_ha_zone_coordinates(self, zone_entity: str = "zone.home") -> Optional[Tuple[float, float]]:
        """
        向 Home Assistant 查詢指定區域 (預設為 zone.home) 之最新經緯度座標。

        用途說明：
            當使用者在 Home Assistant 前端介面變更住家位置時，可藉由本 API 自動同步最新經緯度，
            無須手動編輯設定檔或重啟容器。

        參數說明：
            zone_entity (str): Home Assistant 區域實體代碼，預設為 "zone.home"。

        回傳值：
            Optional[Tuple[float, float]]: (緯度, 經度) 數組，若查詢失敗或未啟用連線則回傳 None。
        """
        if not self.enabled:
            return None

        url = f"{self.base_url}/api/states/{zone_entity}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                attributes = data.get("attributes", {})
                lat = attributes.get("latitude")
                lon = attributes.get("longitude")
                if lat is not None and lon is not None:
                    return float(lat), float(lon)
            else:
                logger.debug("查詢 HA %s 狀態失敗: HTTP %d", zone_entity, resp.status_code)
                return None
        except Exception as exc:
            logger.debug("連線 HA 查詢 zone.home 經緯度時發生異常: %s", exc)
            return None
        return None

    def update_state(self, entity_id: str, state_value: str, attributes: Dict[str, Any]) -> bool:
        """
        透過 POST /api/states/<entity_id> 更新 HA 實體狀態及屬性。

        參數說明：
            entity_id (str): HA 實體名稱 (如 input_boolean.is_raining)。
            state_value (str): 實體狀態值 ("on", "off" 或數值字串)。
            attributes (Dict[str, Any]): 實體附帶之屬性字典。

        回傳值：
            bool: 更新成功回傳 True，失敗回傳 False。
        """
        if not self.enabled:
            logger.info("【模擬連動】HA 同步未啟用，略過更新實體 %s -> %s", entity_id, state_value)
            return True

        url = f"{self.base_url}/api/states/{entity_id}"
        payload = {
            "state": state_value,
            "attributes": attributes
        }

        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if resp.status_code in [200, 201]:
                logger.info("成功同步 HA 實體 [%s] -> 狀態: %s", entity_id, state_value)
                return True
            else:
                logger.error("同步 HA 實體 [%s] 失敗: HTTP %d - %s", entity_id, resp.status_code, resp.text)
                return False
        except Exception as exc:
            logger.error("連線 HA API 時發生例外: %s", exc)
            return False

    def sync_all(
        self,
        evaluation_result: Dict[str, Any],
        home_lat: float = 0.0,
        home_lon: float = 0.0,
        selection_mode: str = "fixed"
    ) -> None:
        """
        將評估結果一次性同步更新至 HA 的兩個 input_boolean 及一個感測器 sensor。

        參數說明：
            evaluation_result (Dict[str, Any]): 狀態機評估回傳之結果摘要字典。
            home_lat (float): 當前計算基準住家緯度。
            home_lon (float): 當前計算基準住家經度。
            selection_mode (str): 測站挑選模式 ('fixed' 或 'auto')。
        """
        is_raining = evaluation_result["is_raining"]
        rain_approaching = evaluation_result["rain_approaching"]
        max_rain = evaluation_result["max_rain_10min"]
        dbz = evaluation_result["estimated_dbz"]

        # 1. 更新 input_boolean.is_raining
        bool_raining_id = self.entities_config.get("boolean_is_raining", "input_boolean.is_raining")
        self.update_state(
            entity_id=bool_raining_id,
            state_value="on" if is_raining else "off",
            attributes={
                "friendly_name": "目前正在下雨",
                "icon": "mdi:weather-pouring" if is_raining else "mdi:weather-sunny",
                "max_rain_10min": max_rain,
                "estimated_dbz": dbz,
                "last_updated": evaluation_result["timestamp"]
            }
        )

        # 2. 更新 input_boolean.rain_approaching_warning
        bool_warning_id = self.entities_config.get("boolean_rain_approaching", "input_boolean.rain_approaching_warning")
        self.update_state(
            entity_id=bool_warning_id,
            state_value="on" if rain_approaching else "off",
            attributes={
                "friendly_name": "雨雲接近預警",
                "icon": "mdi:weather-partly-rainy" if rain_approaching else "mdi:weather-cloudy",
                "active_stations": evaluation_result["active_stations_count"],
                "last_updated": evaluation_result["timestamp"]
            }
        )

        # 3. 更新 sensor.cwa_rain_monitor (詳細儀表板感測器)
        sensor_id = self.entities_config.get("sensor_rain_monitor", "sensor.cwa_rain_monitor")
        self.update_state(
            entity_id=sensor_id,
            state_value=str(max_rain),
            attributes={
                "friendly_name": "氣象署雨量綜合監控",
                "icon": "mdi:weather-rainy" if is_raining else "mdi:weather-cloudy",
                "unit_of_measurement": "mm",
                "device_class": "precipitation",
                "state_class": "measurement",
                "max_rain_10min": max_rain,
                "estimated_dbz": dbz,
                "is_raining": is_raining,
                "rain_approaching_warning": rain_approaching,
                "station_selection_mode": selection_mode,
                "home_latitude": round(home_lat, 4),
                "home_longitude": round(home_lon, 4),
                "active_stations_count": evaluation_result["active_stations_count"],
                "consecutive_rain_cycles": evaluation_result["consecutive_rain_cycles"],
                "consecutive_dry_cycles": evaluation_result["consecutive_dry_cycles"],
                "cooldown_remaining_cycles": evaluation_result["cooldown_remaining_cycles"],
                "monitored_stations": [
                    {
                        "id": s["station_id"],
                        "name": s["station_name"],
                        "distance_km": s["distance_km"],
                        "past_10min_mm": s["past_10min_rain"],
                        "is_raining": s.get("is_raining", False)
                    }
                    for s in evaluation_result["stations_detail"]
                ],
                "last_updated": evaluation_result["timestamp"]
            }
        )


# ==============================================================================
# 第六部分：主控調度流程與設定檔讀取
# ==============================================================================

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """
    載入 YAML 設定檔，若不存在則嘗試讀取 config.example.yaml，或以預設結構為基底。
    同時支援以 Docker 環境變數覆寫關鍵設定（適用於 Portainer / Docker Compose 部署環境）。

    支援的環境變數覆寫：
        - CWA_API_TOKEN: 氣象署開放資料授權碼
        - CWA_DATASET_ID: 資料集代碼 (預設: O-A0002-001)
        - HA_BASE_URL: Home Assistant 區網網址 (如 http://192.168.1.100:8123)
        - HA_ACCESS_TOKEN: Home Assistant 長效存取權杖
        - HOME_LATITUDE: 住家緯度 (float)
        - HOME_LONGITUDE: 住家經度 (float)
        - STATION_SELECTION_MODE: 測站挑選模式 ('fixed' 或 'auto')
        - POLLING_INTERVAL_SECONDS: 輪詢間隔秒數 (int，預設: 300)
        - RAIN_DETECTED_MM: 單站微雨判定門檻 (float，預設: 0.1)
        - HEAVY_RAIN_MM: 單站驟雨判定門檻 (float，預設: 1.5)
        - DEBOUNCE_OFF_COUNT: 停雨冷卻連續次數 (int，預設: 3)
        - DEBOUNCE_ON_COUNT: 降雨觸發連續次數 (int，預設: 1)

    參數說明：
        config_path (str): 設定檔路徑。

    回傳值：
        Dict[str, Any]: 彙整並覆寫環境變數後之設定字典。
    """
    config: Dict[str, Any] = {}
    target_path = config_path

    if os.path.exists(target_path):
        with open(target_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        fallback = "config.example.yaml"
        if os.path.exists(fallback):
            logger.warning("未找到 %s，改用範本檔案 %s 載入預設設定", target_path, fallback)
            with open(fallback, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
        else:
            logger.warning("未找到任何設定檔，將完全依賴環境變數與預設值初始化。")
            config = {
                "cwa": {"api_token": "", "dataset_id": "O-A0002-001", "timeout_seconds": 15},
                "location": {
                    "home_latitude": 23.0150,
                    "home_longitude": 120.2050,
                    "station_selection_mode": "fixed",
                    "target_stations": [
                        {"id": "C2O950", "name": "安南"},
                        {"id": "C0X100", "name": "臺南市北區"},
                        {"id": "467420", "name": "永康"},
                        {"id": "C0X150", "name": "安定"}
                    ]
                },
                "thresholds": {
                    "rain_detected_mm": 0.1,
                    "stations_rain_count": 2,
                    "heavy_rain_single_station_mm": 1.5,
                    "debounce_on_count": 1,
                    "debounce_off_count": 3,
                    "polling_interval_seconds": 300
                },
                "home_assistant": {
                    "enabled": True,
                    "base_url": "http://homeassistant.local:8123",
                    "access_token": "",
                    "entities": {
                        "boolean_is_raining": "input_boolean.is_raining",
                        "boolean_rain_approaching": "input_boolean.rain_approaching_warning",
                        "sensor_rain_monitor": "sensor.cwa_rain_monitor"
                    }
                }
            }

    # 確保主要層級字典結構完整
    config.setdefault("cwa", {})
    config.setdefault("location", {})
    config.setdefault("thresholds", {})
    config.setdefault("home_assistant", {})

    # 讀取並覆寫環境變數 (適用於 Portainer Stacks)
    if os.getenv("CWA_API_TOKEN"):
        config["cwa"]["api_token"] = os.getenv("CWA_API_TOKEN")
        logger.info("已透過環境變數 CWA_API_TOKEN 覆寫氣象署金鑰")
    if os.getenv("CWA_DATASET_ID"):
        config["cwa"]["dataset_id"] = os.getenv("CWA_DATASET_ID")

    if os.getenv("HA_BASE_URL"):
        config["home_assistant"]["base_url"] = os.getenv("HA_BASE_URL")
        logger.info("已透過環境變數 HA_BASE_URL 覆寫 HA 網址: %s", config["home_assistant"]["base_url"])
    if os.getenv("HA_ACCESS_TOKEN"):
        config["home_assistant"]["access_token"] = os.getenv("HA_ACCESS_TOKEN")
        logger.info("已透過環境變數 HA_ACCESS_TOKEN 覆寫 HA 存取權杖")

    if os.getenv("HOME_LATITUDE"):
        try:
            config["location"]["home_latitude"] = float(os.getenv("HOME_LATITUDE"))
        except ValueError:
            pass
    if os.getenv("HOME_LONGITUDE"):
        try:
            config["location"]["home_longitude"] = float(os.getenv("HOME_LONGITUDE"))
        except ValueError:
            pass
    if os.getenv("STATION_SELECTION_MODE"):
        config["location"]["station_selection_mode"] = os.getenv("STATION_SELECTION_MODE")

    # 是否自動從 HA zone.home 同步住家座標 (預設啟用 True)
    if os.getenv("AUTO_SYNC_HA_ZONE"):
        val = os.getenv("AUTO_SYNC_HA_ZONE", "").strip().lower()
        config["location"]["auto_sync_ha_zone"] = val not in ["false", "0", "no"]
    else:
        config["location"].setdefault("auto_sync_ha_zone", True)

    if os.getenv("POLLING_INTERVAL_SECONDS"):
        try:
            config["thresholds"]["polling_interval_seconds"] = int(os.getenv("POLLING_INTERVAL_SECONDS"))
        except ValueError:
            pass
    if os.getenv("RAIN_DETECTED_MM"):
        try:
            config["thresholds"]["rain_detected_mm"] = float(os.getenv("RAIN_DETECTED_MM"))
        except ValueError:
            pass
    if os.getenv("HEAVY_RAIN_MM"):
        try:
            config["thresholds"]["heavy_rain_single_station_mm"] = float(os.getenv("HEAVY_RAIN_MM"))
        except ValueError:
            pass
    if os.getenv("DEBOUNCE_OFF_COUNT"):
        try:
            config["thresholds"]["debounce_off_count"] = int(os.getenv("DEBOUNCE_OFF_COUNT"))
        except ValueError:
            pass
    if os.getenv("DEBOUNCE_ON_COUNT"):
        try:
            config["thresholds"]["debounce_on_count"] = int(os.getenv("DEBOUNCE_ON_COUNT"))
        except ValueError:
            pass

    return config


def run_single_cycle(
    fetcher: CwaRainDataFetcher,
    evaluator: StationEvaluator,
    state_machine: RainDebounceStateMachine,
    ha_sync: HomeAssistantSync,
    auto_sync_ha_zone: bool = True
) -> Dict[str, Any]:
    """
    執行單次雨量擷取、判定與同步循環。

    參數說明：
        fetcher (CwaRainDataFetcher): 氣象署抓取物件。
        evaluator (StationEvaluator): 測站評估與距離篩選物件。
        state_machine (RainDebounceStateMachine): 狀態機物件。
        ha_sync (HomeAssistantSync): HA 連動同步物件。
        auto_sync_ha_zone (bool): 是否自動向 HA zone.home 取得最新住家經緯度。

    回傳值：
        Dict[str, Any]: 當次評估彙整結果。
    """
    # 0. 若啟用自動向 HA 同步住家位置，嘗試向 HA 取得最新經緯度並更新評估器
    if auto_sync_ha_zone and ha_sync.enabled:
        zone_coords = ha_sync.fetch_ha_zone_coordinates("zone.home")
        if zone_coords:
            ha_lat, ha_lon = zone_coords
            evaluator.update_home_location(ha_lat, ha_lon)

    # 1. 抓取氣象署測站資料
    raw_stations = fetcher.fetch_raw_stations()
    if not raw_stations:
        logger.warning("本次未取得測站資料，跳過本次狀態更新。")
        return {}

    # 2. 提取標準化欄位
    parsed_stations = []
    for raw in raw_stations:
        info = fetcher.extract_station_info(raw)
        if info:
            parsed_stations.append(info)

    # 3. 挑選目標 4 站並計算距離
    selected_stations = evaluator.select_four_stations(parsed_stations)
    if not selected_stations:
        logger.error("無法篩選出目標測站！請檢查測站代碼或經緯度設定。")
        return {}

    logger.info("=== 監控測站降雨即時數據 ===")
    for st in selected_stations:
        logger.info("  [%s %s] 距離家: %.2f km | 過去10分雨量: %.2f mm",
                    st["station_id"], st["station_name"], st["distance_km"], st["past_10min_rain"])

    # 4. 狀態機防抖動判定
    result = state_machine.evaluate(selected_stations)

    logger.info("=== 判定結論 ===")
    logger.info("  最大10分雨量: %.2f mm | 推估雷達迴波: %.1f dBZ | 有雨測站數: %d",
                result["max_rain_10min"], result["estimated_dbz"], result["active_stations_count"])
    logger.info("  【正在下雨 is_raining】: %s (連續有雨:%d, 連續無雨:%d, 離解除還差:%d)",
                result["is_raining"], result["consecutive_rain_cycles"],
                result["consecutive_dry_cycles"], result["cooldown_remaining_cycles"])
    logger.info("  【雨雲接近預警 rain_approaching】: %s", result["rain_approaching"])

    # 5. 同步至 Home Assistant
    ha_sync.sync_all(
        evaluation_result=result,
        home_lat=evaluator.home_lat,
        home_lon=evaluator.home_lon,
        selection_mode=evaluator.mode
    )

    return result


def main():
    """
    主程式進入點，負責啟動定時輪詢迴圈。
    """
    logger.info("正在啟動中央氣象署雨量監控服務...")

    # 載入設定
    config = load_config()

    cwa_cfg = config.get("cwa", {})
    loc_cfg = config.get("location", {})
    th_cfg = config.get("thresholds", {})
    ha_cfg = config.get("home_assistant", {})

    # 初始化模組
    fetcher = CwaRainDataFetcher(
        api_token=cwa_cfg.get("api_token", ""),
        dataset_id=cwa_cfg.get("dataset_id", "O-A0002-001"),
        timeout=cwa_cfg.get("timeout_seconds", 15)
    )

    evaluator = StationEvaluator(
        home_lat=loc_cfg.get("home_latitude", 23.0150),
        home_lon=loc_cfg.get("home_longitude", 120.2050),
        mode=loc_cfg.get("station_selection_mode", "fixed"),
        target_stations=loc_cfg.get("target_stations", [])
    )

    state_machine = RainDebounceStateMachine(
        rain_detected_mm=th_cfg.get("rain_detected_mm", 0.1),
        stations_rain_count=th_cfg.get("stations_rain_count", 2),
        heavy_rain_single_station_mm=th_cfg.get("heavy_rain_single_station_mm", 1.5),
        debounce_on_count=th_cfg.get("debounce_on_count", 1),
        debounce_off_count=th_cfg.get("debounce_off_count", 3)
    )

    ha_sync = HomeAssistantSync(
        base_url=ha_cfg.get("base_url", "http://homeassistant.local:8123"),
        access_token=ha_cfg.get("access_token", ""),
        entities_config=ha_cfg.get("entities", {}),
        enabled=ha_cfg.get("enabled", True)
    )

    interval = th_cfg.get("polling_interval_seconds", 300)
    auto_sync_ha_zone = loc_cfg.get("auto_sync_ha_zone", True)

    # 檢查是否為單次執行模式 (例如 CLI 參數 --once)
    if "--once" in sys.argv:
        logger.info("執行單次抓取與測試模式 (--once)...")
        run_single_cycle(fetcher, evaluator, state_machine, ha_sync, auto_sync_ha_zone=auto_sync_ha_zone)
        logger.info("單次執行完畢，結束程式。")
        return

    logger.info("進入常駐輪詢模式，每隔 %d 秒 (%.1f 分鐘) 更新一次 (測站模式: %s)...",
                interval, interval / 60.0, evaluator.mode)
    try:
        while True:
            try:
                run_single_cycle(fetcher, evaluator, state_machine, ha_sync, auto_sync_ha_zone=auto_sync_ha_zone)
            except Exception as exc:
                logger.error("執行輪詢循環時發生未預期錯誤: %s", exc, exc_info=True)

            logger.info("休眠 %d 秒後進行下一次輪詢...", interval)
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("接收到中斷訊號 (Ctrl+C)，安全停止服務。")


if __name__ == "__main__":
    main()

