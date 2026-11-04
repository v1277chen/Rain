"""
中央氣象署雨量監控整合 - 常數與設定鍵定義模組
檔案名稱：const.py
功能簡述：
    定義本整合所需之網域識別碼 (DOMAIN)、受支援之平台清單、
    各項使用者設定鍵 (Configuration Keys) 與預設數值。
"""

from typing import Final

# 整合網域識別碼
DOMAIN: Final = "cwa_rain"

# 受支援之 Home Assistant 平台清單
PLATFORMS: Final = ["sensor", "binary_sensor"]

# 氣象署開放資料 API 端點常數
CWA_API_BASE_URL: Final = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001"

# 設定鍵 (Configuration Keys)
CONF_API_TOKEN: Final = "api_token"
CONF_LOCATION_NAME: Final = "location_name"
CONF_ZONE_ENTITY: Final = "zone_entity"
CONF_USE_ZONE: Final = "use_zone"
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_SELECTION_MODE: Final = "selection_mode"
CONF_AUTO_SYNC_ZONE: Final = "auto_sync_zone"
CONF_TARGET_STATIONS: Final = "target_stations"

# 判定門檻與防抖動設定鍵
CONF_POLLING_INTERVAL: Final = "polling_interval"
CONF_RAIN_DETECTED_MM: Final = "rain_detected_mm"
CONF_STATIONS_RAIN_COUNT: Final = "stations_rain_count"
CONF_HEAVY_RAIN_MM: Final = "heavy_rain_single_station_mm"
CONF_DEBOUNCE_ON_COUNT: Final = "debounce_on_count"
CONF_DEBOUNCE_OFF_COUNT: Final = "debounce_off_count"

# 預設參數數值 (Defaults)
DEFAULT_LOCATION_NAME: Final = "住家"
DEFAULT_ZONE_ENTITY: Final = "zone.home"
DEFAULT_POLLING_INTERVAL: Final = 300  # 5 分鐘輪詢一次
DEFAULT_RAIN_DETECTED_MM: Final = 0.1  # 單站微雨判定門檻 (mm)
DEFAULT_STATIONS_RAIN_COUNT: Final = 2  # 一般降雨多站投票門檻 (至少 2 站)
DEFAULT_HEAVY_RAIN_MM: Final = 1.5     # 單站驟雨瞬間判定門檻 (mm)
DEFAULT_DEBOUNCE_ON_COUNT: Final = 1   # 開啟降雨所需滿足次數 (1次快速反應)
DEFAULT_DEBOUNCE_OFF_COUNT: Final = 3  # 解除停雨所需冷卻次數 (3次 = 15分鐘)
DEFAULT_SELECTION_MODE: Final = "auto" # 預設自動挑選最近 4 站
DEFAULT_AUTO_SYNC_ZONE: Final = True   # 預設自 Zone 自動即時同步經緯度

# 模式選項字串
MODE_AUTO: Final = "auto"
MODE_FIXED: Final = "fixed"

