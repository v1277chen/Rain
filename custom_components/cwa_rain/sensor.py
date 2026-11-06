"""
中央氣象署雨量監控整合 - 感測器實體平台模組 (Sensor Platform)
檔案名稱：sensor.py
功能簡述：
    提供氣象署雨量綜合監控核心感測器 (CwaRainMonitorSensor)，對齊 Docker 經典架構：
    實體名稱為 sensor.cwa_rain_monitor (多地點則加上簡短後綴如 sensor.cwa_rain_monitor_gong_si)，
    數值直接呈現過去 10 分鐘最大雨量 (mm)，並將推估雷達迴波 (dBZ)、有雨測站數與 4 站詳細觀測資料
    完整收納於屬性 (Attributes) 中，完美適配 LOVELACE_CARD_GUIDE.md 各項儀表板卡片。
"""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, get_location_slug
from .coordinator import CwaRainDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """
    非同步設定雨量綜合感測器實體。

    參數說明：
        hass (HomeAssistant): HA 核心物件。
        entry (ConfigEntry): 設定項目實例。
        async_add_entities (AddEntitiesCallback): 新增實體之回呼函式。
    """
    coordinator: CwaRainDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # 註冊單一綜合感測器，回歸經典 Docker 實體架構
    entities = [
        CwaRainMonitorSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class CwaRainMonitorSensor(CoordinatorEntity[CwaRainDataUpdateCoordinator], SensorEntity):
    """
    氣象署雨量綜合監控感測器實體 (對應 sensor.cwa_rain_monitor)。
    """

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        """
        初始化雨量綜合感測器。

        參數說明：
            coordinator (CwaRainDataUpdateCoordinator): 資料更新協調器。
            entry (ConfigEntry): 設定項目實例。
        """
        super().__init__(coordinator)
        self.entry = entry

        # 取得簡潔 slug (住家回傳空字串，公司回傳 gong_si)
        loc_slug = get_location_slug(coordinator.location_name)
        object_id = f"cwa_rain_monitor_{loc_slug}" if loc_slug else "cwa_rain_monitor"

        # 明確指定 entity_id 與 suggested_object_id，停用 has_entity_name 避免 HA 產生冗長中文拼音
        self._attr_has_entity_name = False
        self.entity_id = f"sensor.{object_id}"
        self._attr_suggested_object_id = object_id

        # 實體顯示名稱 (Friendly Name)
        if loc_slug:
            self._attr_name = f"氣象署雨量綜合監控 ({coordinator.location_name})"
        else:
            self._attr_name = "氣象署雨量綜合監控"

        self._attr_unique_id = f"{entry.entry_id}_cwa_rain_monitor"
        self._attr_native_unit_of_measurement = "mm"
        self._attr_device_class = SensorDeviceClass.PRECIPITATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # 設置氣象署專屬品牌圖示 (在支援的 HA 介面直接渲染圓形 CWA.png 圖片)
        self._attr_entity_picture = "/cwa_rain_static/CWA.png"

    @property
    def device_info(self) -> DeviceInfo:
        """回傳實體所屬之 Device 裝置結構。"""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"中央氣象署雨量監控 ({self.coordinator.location_name})",
            manufacturer="交通部中央氣象署 (CWA)",
            model="自動雨量觀測整合系統 (O-A0002-001)",
            sw_version="1.0.3",
        )

    @property
    def native_value(self) -> Optional[float]:
        """回傳當前 4 站中最大之過去 10 分鐘雨量值 (mm)。"""
        if self.coordinator.data:
            return float(self.coordinator.data.get("max_rain_10min", 0.0))
        return None

    @property
    def icon(self) -> str:
        """依據降雨狀態動態更換天氣圖示。"""
        if self.coordinator.data and self.coordinator.data.get("is_raining", False):
            return "mdi:weather-rainy"
        return "mdi:weather-cloudy"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """
        回傳綜合屬性字典，完整涵蓋 Docker 模式之各項屬性：
        包含雷達迴波、有雨測站數、4 站觀測明細、冷卻週期倒數等。
        """
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        is_raining = data.get("is_raining", False)
        rain_approaching = data.get("rain_approaching", False)
        max_rain = data.get("max_rain_10min", 0.0)
        dbz = data.get("estimated_dbz", 0.0)
        lat = data.get("latitude", 0.0)
        lon = data.get("longitude", 0.0)

        return {
            "friendly_name": self._attr_name,
            "entity_picture": "/cwa_rain_static/CWA.png",
            "max_rain_10min": max_rain,
            "estimated_dbz": dbz,
            "is_raining": is_raining,
            "rain_approaching_warning": rain_approaching,
            "station_selection_mode": data.get("selection_mode", "auto"),
            "home_latitude": round(lat, 4),
            "home_longitude": round(lon, 4),
            "location_name": data.get("location_name", self.coordinator.location_name),
            "zone_entity": data.get("zone_entity"),
            "active_stations_count": data.get("active_stations_count", 0),
            "consecutive_rain_cycles": data.get("consecutive_rain_cycles", 0),
            "consecutive_dry_cycles": data.get("consecutive_dry_cycles", 0),
            "cooldown_remaining_cycles": data.get("cooldown_remaining_cycles", 0),
            "monitored_stations": [
                {
                    "id": s["station_id"],
                    "name": s["station_name"],
                    "distance_km": s["distance_km"],
                    "past_10min_mm": s["past_10min_rain"],
                    "is_raining": s.get("is_raining", False)
                }
                for s in data.get("stations_detail", [])
            ],
            "last_updated": data.get("timestamp")
        }
