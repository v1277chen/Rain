"""
中央氣象署雨量監控整合 - 非同步資料協調器模組
檔案名稱：coordinator.py
功能簡述：
    1. 實作非同步 API 資料抓取客戶端 (CwaDataClient)，內建 TTL 快取以支援多座標共享，避免頻繁呼叫氣象署 API。
    2. 提供 Haversine 球面大圓距離計算與 Marshall-Palmer 雷達迴波強度 (dBZ) 反推公式。
    3. 實作獨立防抖動狀態機 (RainDebounceStateMachine)，維護降雨與雨雲接近預警狀態。
    4. 實作 CwaRainDataUpdateCoordinator (繼承 HA DataUpdateCoordinator)，負責定期輪詢與實體資料派發。
"""

import math
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional

try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
except ImportError:
    # 提供本地單元測試相容性基底類別 (免安裝 homeassistant 龐大核心套件)
    class HomeAssistant:  # type: ignore
        pass

    class UpdateFailed(Exception):  # type: ignore
        pass

    class DataUpdateCoordinator:  # type: ignore
        def __init__(self, hass, logger, name, update_interval):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None

    def async_get_clientsession(hass):  # type: ignore
        return None

from .const import (
    DOMAIN,
    CWA_API_BASE_URL,
    CONF_API_TOKEN,
    CONF_LOCATION_NAME,
    CONF_ZONE_ENTITY,
    CONF_USE_ZONE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_SELECTION_MODE,
    CONF_AUTO_SYNC_ZONE,
    CONF_TARGET_STATIONS,
    CONF_RAIN_DETECTED_MM,
    CONF_STATIONS_RAIN_COUNT,
    CONF_HEAVY_RAIN_MM,
    CONF_DEBOUNCE_ON_COUNT,
    CONF_DEBOUNCE_OFF_COUNT,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_RAIN_DETECTED_MM,
    DEFAULT_STATIONS_RAIN_COUNT,
    DEFAULT_HEAVY_RAIN_MM,
    DEFAULT_DEBOUNCE_ON_COUNT,
    DEFAULT_DEBOUNCE_OFF_COUNT,
    DEFAULT_SELECTION_MODE,
    DEFAULT_AUTO_SYNC_ZONE,
    MODE_AUTO,
    MODE_FIXED,
)

_LOGGER = logging.getLogger(__name__)


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
        lat1 (float): 起點緯度 (十進制度數 Decimal Degrees)。
        lon1 (float): 起點經度 (十進制度數 Decimal Degrees)。
        lat2 (float): 終點緯度 (十進制度數 Decimal Degrees)。
        lon2 (float): 終點經度 (十進制度數 Decimal Degrees)。

    回傳值：
        float: 兩點間之地面直線球面距離 (單位：公里 km)，四捨五入至小數點後第 2 位。
    """
    earth_radius_km: float = 6371.0

    rad_lat1: float = math.radians(lat1)
    rad_lat2: float = math.radians(lat2)
    delta_lat: float = math.radians(lat2 - lat1)
    delta_lon: float = math.radians(lon2 - lon1)

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

    rainfall_rate_mm_per_hr: float = past_10min_rain_mm * 6.0

    if rainfall_rate_mm_per_hr < 0.05:
        return 15.0

    try:
        z_factor: float = 200.0 * (rainfall_rate_mm_per_hr ** 1.6)
        dbz: float = 10.0 * math.log10(z_factor)
        dbz_clamped: float = max(0.0, min(70.0, dbz))
        return round(dbz_clamped, 1)
    except (ValueError, OverflowError):
        return 0.0


# ==============================================================================
# 第二部分：氣象署 API 快取客戶端 (支援多地點共享 API 請求)
# ==============================================================================

class CwaApiClient:
    """
    氣象署開放資料 API 存取客戶端。
    具備微型記憶體快取 (TTL Cache)，當系統存在多個監控地點（如住家、工作地點）時，
    多個 Coordinator 在同一輪詢時間點調用只會觸發一次真實網路請求，避免重複連線與被氣象署限速。
    """

    def __init__(self, hass: HomeAssistant, api_token: str):
        """
        初始化 API 客戶端。

        參數說明：
            hass (HomeAssistant): Home Assistant 實體物件。
            api_token (str): 中央氣象署開放資料授權碼。
        """
        self.hass: HomeAssistant = hass
        self.api_token: str = api_token
        self._cached_data: List[Dict[str, Any]] = []
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds: int = 60  # 快取有效時間 60 秒

    async def async_fetch_stations(self) -> List[Dict[str, Any]]:
        """
        非同步取得氣象署所有自動雨量站觀測資料 (O-A0002-001)。

        回傳值：
            List[Dict[str, Any]]: 解析後之標準化測站字典清單。若請求失敗且無快取則回傳空清單。
        """
        now = datetime.now()
        # 若快取尚在有效期限內，直接重複使用
        if self._cached_data and self._cache_timestamp:
            elapsed = (now - self._cache_timestamp).total_seconds()
            if elapsed < self._cache_ttl_seconds:
                _LOGGER.debug("命中 CWA 雨量資料快取 (已快取 %.1f 秒)，略過重複網路請求", elapsed)
                return self._cached_data

        session = async_get_clientsession(self.hass)
        headers = {
            "Accept": "application/json",
            "User-Agent": "HomeAssistant-CWARainIntegration/1.0"
        }
        params = {
            "Authorization": self.api_token
        }

        try:
            _LOGGER.debug("正在發送非同步 GET 請求至氣象署雨量 API...")
            async with session.get(CWA_API_BASE_URL, headers=headers, params=params, timeout=20) as resp:
                if resp.status != 200:
                    _LOGGER.error("氣象署 API 回應 HTTP 異常狀態碼: %d", resp.status)
                    return self._cached_data or []

                data = await resp.json()
                if not data.get("success") or str(data.get("success")).lower() != "true":
                    _LOGGER.error("氣象署 API 回傳失敗狀態: %s", data.get("message", "無訊息"))
                    return self._cached_data or []

                records = data.get("records", {})
                raw_stations = records.get("Station") or records.get("location") or []

                # 標準化解析測站資料
                parsed = []
                for st in raw_stations:
                    item = self._extract_station_info(st)
                    if item:
                        parsed.append(item)

                self._cached_data = parsed
                self._cache_timestamp = now
                _LOGGER.info("成功自氣象署取得全台 %d 座雨量測站即時觀測數據", len(parsed))
                return parsed

        except Exception as exc:
            _LOGGER.error("連線氣象署 API 時發生非同步通訊錯誤: %s", exc)
            return self._cached_data or []

    @staticmethod
    def _extract_station_info(station_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        自單一測站原始字典中標準化提取必要欄位，並過濾負數異常值。

        參數說明：
            station_dict (Dict[str, Any]): API 回傳之單站原始字典。

        回傳值：
            Optional[Dict[str, Any]]: 標準化欄位字典，失敗則為 None。
        """
        try:
            station_id = station_dict.get("StationId") or station_dict.get("stationId", "")
            station_name = station_dict.get("StationName") or station_dict.get("locationName", "")

            lat = 0.0
            lon = 0.0
            geo_info = station_dict.get("GeoInfo", {})
            coordinates = geo_info.get("Coordinates", [])
            if coordinates and isinstance(coordinates, list):
                for coord in coordinates:
                    if coord.get("CoordinateName") == "WGS84" or "StationLatitude" in coord:
                        lat = float(coord.get("StationLatitude", 0.0))
                        lon = float(coord.get("StationLongitude", 0.0))
                        break
            if lat == 0.0 and lon == 0.0:
                lat = float(station_dict.get("lat") or station_dict.get("StationLatitude") or 0.0)
                lon = float(station_dict.get("lon") or station_dict.get("StationLongitude") or 0.0)

            past_10min = 0.0
            rainfall_elem = station_dict.get("RainfallElement", {})
            if "Past10Min" in rainfall_elem:
                past_10min = float(rainfall_elem["Past10Min"].get("Precipitation", 0.0))
            else:
                for elem in station_dict.get("weatherElement", []):
                    if elem.get("elementName") in ["PAST_10_MIN", "MIN_10", "Now"]:
                        past_10min = float(elem.get("elementValue", {}).get("value", 0.0))
                        break

            # 異常代碼清洗：-99 為故障，-998 為微量雨跡
            if past_10min < 0:
                past_10min = 0.0

            return {
                "station_id": str(station_id).strip(),
                "station_name": str(station_name).strip(),
                "latitude": lat,
                "longitude": lon,
                "past_10min_rain": round(past_10min, 2)
            }
        except Exception:
            return None


# ==============================================================================
# 第三部分：防抖動狀態機 (各監控地點獨立擁有)
# ==============================================================================

class RainDebounceStateMachine:
    """
    雨量判定與防抖動狀態機。
    每個配置項目 (Config Entry) 獨立實例化，維護自身的降雨與冷卻計數。
    """

    def __init__(
        self,
        rain_detected_mm: float = DEFAULT_RAIN_DETECTED_MM,
        stations_rain_count: int = DEFAULT_STATIONS_RAIN_COUNT,
        heavy_rain_single_station_mm: float = DEFAULT_HEAVY_RAIN_MM,
        debounce_on_count: int = DEFAULT_DEBOUNCE_ON_COUNT,
        debounce_off_count: int = DEFAULT_DEBOUNCE_OFF_COUNT
    ):
        """
        初始化狀態機。

        參數說明：
            rain_detected_mm (float): 單站認定有雨之最低雨量 (mm)。
            stations_rain_count (int): 一般降雨時需達到有雨的最少測站數。
            heavy_rain_single_station_mm (float): 單站驟雨判定門檻 (mm)。
            debounce_on_count (int): 開啟降雨所需滿足次數。
            debounce_off_count (int): 關閉停雨所需連續無雨次數。
        """
        self.rain_detected_mm = rain_detected_mm
        self.stations_rain_count = stations_rain_count
        self.heavy_rain_single_station_mm = heavy_rain_single_station_mm
        self.debounce_on_count = debounce_on_count
        self.debounce_off_count = debounce_off_count

        self.is_raining: bool = False
        self.rain_approaching: bool = False
        self.consecutive_rain_cycles: int = 0
        self.consecutive_dry_cycles: int = 0

    def evaluate(self, selected_stations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        輸入 4 座目標測站數據，執行降雨判定與防抖動狀態更新。

        參數說明：
            selected_stations (List[Dict[str, Any]]): 4 座目標測站詳細資訊字典清單。

        回傳值：
            Dict[str, Any]: 彙整後之狀態評估結果摘要。
        """
        active_count = 0
        max_rain = 0.0

        for st in selected_stations:
            rain = st.get("past_10min_rain", 0.0)
            if rain > max_rain:
                max_rain = rain
            is_st_raining = rain >= self.rain_detected_mm
            st["is_raining"] = is_st_raining
            if is_st_raining:
                active_count += 1

        two_stations_rain = (active_count >= self.stations_rain_count)
        single_heavy = (max_rain >= self.heavy_rain_single_station_mm)
        raw_rain_trigger = two_stations_rain or single_heavy

        if raw_rain_trigger:
            self.consecutive_rain_cycles += 1
            self.consecutive_dry_cycles = 0
            if self.consecutive_rain_cycles >= self.debounce_on_count:
                self.is_raining = True
        else:
            self.consecutive_dry_cycles += 1
            self.consecutive_rain_cycles = 0
            if self.consecutive_dry_cycles >= self.debounce_off_count:
                self.is_raining = False

        if active_count >= 1 or self.is_raining:
            self.rain_approaching = True
        else:
            if self.consecutive_dry_cycles >= self.debounce_off_count:
                self.rain_approaching = False

        estimated_dbz = calculate_estimated_dbz(max_rain)
        dry_remaining = max(0, self.debounce_off_count - self.consecutive_dry_cycles) if self.is_raining else 0

        return {
            "max_rain_10min": max_rain,
            "estimated_dbz": estimated_dbz,
            "active_stations_count": active_count,
            "raw_rain_trigger": raw_rain_trigger,
            "is_raining": self.is_raining,
            "rain_approaching": self.rain_approaching,
            "consecutive_rain_cycles": self.consecutive_rain_cycles,
            "consecutive_dry_cycles": self.consecutive_dry_cycles,
            "cooldown_remaining_cycles": dry_remaining,
            "stations_detail": selected_stations,
            "timestamp": datetime.now().isoformat()
        }


# ==============================================================================
# 第四部分：Home Assistant DataUpdateCoordinator 協調器
# ==============================================================================

class CwaRainDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """
    中央氣象署雨量監控資料協調器。
    代表單一監控地點（如住家或工作地點）之數據同步中樞。
    """

    def __init__(self, hass: HomeAssistant, client: CwaApiClient, entry_data: Dict[str, Any]):
        """
        初始化 Coordinator。

        參數說明：
            hass (HomeAssistant): Home Assistant 實體物件。
            client (CwaApiClient): 共享之氣象署 API 客戶端。
            entry_data (Dict[str, Any]): 本設定實例之配置字典。
        """
        self.client: CwaApiClient = client
        self.entry_data: Dict[str, Any] = entry_data

        interval_sec = entry_data.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"CWA Rain Monitor ({entry_data.get(CONF_LOCATION_NAME, '未命名')})",
            update_interval=timedelta(seconds=interval_sec),
        )

        # 狀態機初始化
        self.state_machine = RainDebounceStateMachine(
            rain_detected_mm=entry_data.get(CONF_RAIN_DETECTED_MM, DEFAULT_RAIN_DETECTED_MM),
            stations_rain_count=entry_data.get(CONF_STATIONS_RAIN_COUNT, DEFAULT_STATIONS_RAIN_COUNT),
            heavy_rain_single_station_mm=entry_data.get(CONF_HEAVY_RAIN_MM, DEFAULT_HEAVY_RAIN_MM),
            debounce_on_count=entry_data.get(CONF_DEBOUNCE_ON_COUNT, DEFAULT_DEBOUNCE_ON_COUNT),
            debounce_off_count=entry_data.get(CONF_DEBOUNCE_OFF_COUNT, DEFAULT_DEBOUNCE_OFF_COUNT),
        )

        # 經緯度座標狀態
        self.location_name: str = entry_data.get(CONF_LOCATION_NAME, DEFAULT_LOCATION_NAME)
        self.zone_entity: Optional[str] = entry_data.get(CONF_ZONE_ENTITY)
        self.use_zone: bool = entry_data.get(CONF_USE_ZONE, True)
        self.auto_sync_zone: bool = entry_data.get(CONF_AUTO_SYNC_ZONE, DEFAULT_AUTO_SYNC_ZONE)
        self.selection_mode: str = entry_data.get(CONF_SELECTION_MODE, DEFAULT_SELECTION_MODE)
        self.target_stations: List[Dict[str, str]] = entry_data.get(CONF_TARGET_STATIONS, [])

        self.current_lat: float = float(entry_data.get(CONF_LATITUDE, 23.0150))
        self.current_lon: float = float(entry_data.get(CONF_LONGITUDE, 120.2050))
        self.current_station_ids: List[str] = []

    def _sync_zone_coordinates(self) -> None:
        """
        若設定為使用 HA Zone 且啟用自動同步，自 HA 內部狀態取得指定 Zone 之最新經緯度。
        """
        if not self.use_zone or not self.zone_entity or not self.auto_sync_zone:
            return

        zone_state = self.hass.states.get(self.zone_entity)
        if zone_state and zone_state.attributes:
            z_lat = zone_state.attributes.get("latitude")
            z_lon = zone_state.attributes.get("longitude")
            if z_lat is not None and z_lon is not None:
                new_lat = float(z_lat)
                new_lon = float(z_lon)
                if round(self.current_lat, 4) != round(new_lat, 4) or round(self.current_lon, 4) != round(new_lon, 4):
                    _LOGGER.info(
                        "【%s Zone 座標變更】緯度: %.4f -> %.4f | 經度: %.4f -> %.4f",
                        self.location_name, self.current_lat, new_lat, self.current_lon, new_lon
                    )
                    self.current_lat = new_lat
                    self.current_lon = new_lon

    def _select_four_stations(self, all_stations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        依據目前座標與模式，由全台測站中挑選 4 座監控測站並計算距離。

        參數說明：
            all_stations (List[Dict[str, Any]]): 氣象署所有標準化測站清單。

        回傳值：
            List[Dict[str, Any]]: 排序後之目標 4 站清單。
        """
        stations_with_dist = []
        for st in all_stations:
            lat = st["latitude"]
            lon = st["longitude"]
            if lat > 0 and lon > 0:
                dist = haversine_distance(self.current_lat, self.current_lon, lat, lon)
            else:
                dist = 999.9

            st_copy = dict(st)
            st_copy["distance_km"] = dist
            stations_with_dist.append(st_copy)

        target_ids = {s.get("id") or s.get("station_id") for s in self.target_stations if isinstance(s, dict)}

        if self.selection_mode == MODE_FIXED and target_ids:
            selected = [s for s in stations_with_dist if s["station_id"] in target_ids]
            selected.sort(key=lambda x: x["distance_km"])
            result = selected[:4]
        else:
            valid = [s for s in stations_with_dist if s["distance_km"] < 900.0]
            valid.sort(key=lambda x: x["distance_km"])
            result = valid[:4]

        new_ids = [s["station_id"] for s in result]
        if self.current_station_ids and new_ids != self.current_station_ids:
            names = [f"{s['station_name']}({s['station_id']})" for s in result]
            _LOGGER.info("【%s 測站更新】已自動切換最近 4 站: %s", self.location_name, ", ".join(names))
        self.current_station_ids = new_ids

        return result

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        執行 Coordinator 週期更新之主流程。

        回傳值：
            Dict[str, Any]: 傳遞給所有 Sensor 實體之狀態字典。
        """
        try:
            # 1. 檢查並同步 Zone 座標
            self._sync_zone_coordinates()

            # 2. 取得全台雨量測站 (內建快取機制)
            all_stations = await self.client.async_fetch_stations()
            if not all_stations:
                raise UpdateFailed("未能自氣象署取得雨量測站數據")

            # 3. 挑選目標 4 站
            selected = self._select_four_stations(all_stations)
            if not selected:
                raise UpdateFailed(f"未能為地點 '{self.location_name}' 篩選出目標測站")

            # 4. 執行防抖動狀態評估
            evaluation = self.state_machine.evaluate(selected)

            # 5. 附加該地點之專屬維度資訊
            evaluation["location_name"] = self.location_name
            evaluation["latitude"] = self.current_lat
            evaluation["longitude"] = self.current_lon
            evaluation["selection_mode"] = self.selection_mode
            evaluation["zone_entity"] = self.zone_entity

            return evaluation

        except Exception as exc:
            _LOGGER.error("【%s】更新雨量數據時發生例外: %s", self.location_name, exc)
            raise UpdateFailed(f"更新雨量數據失敗: {exc}") from exc
