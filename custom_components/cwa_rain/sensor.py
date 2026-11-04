"""
中央氣象署雨量監控整合 - 感測器實體平台模組 (Sensor Platform)
檔案名稱：sensor.py
功能簡述：
    提供三個核心數值感測器實體：
    1. 過去 10 分鐘最大累積降水量感測器 (附帶 4 站完整即時數據屬性)
    2. Marshall-Palmer 反推雷達迴波強度感測器 (dBZ)
    3. 當前周邊有雨測站數量感測器
    各實體均綁定專屬 Device (裝置)，便於在 Home Assistant 儀表板分區呈現。
"""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CwaRainDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """
    非同步設定雨量感測器實體。

    參數說明：
        hass (HomeAssistant): HA 核心物件。
        entry (ConfigEntry): 設定項目實例。
        async_add_entities (AddEntitiesCallback): 新增實體之回呼函式。
    """
    coordinator: CwaRainDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CwaRainPrecipitationSensor(coordinator, entry),
        CwaRainDbzSensor(coordinator, entry),
        CwaRainActiveStationsSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class CwaRainBaseSensor(CoordinatorEntity[CwaRainDataUpdateCoordinator], SensorEntity):
    """雨量感測器基底類別，定義共用之裝置資訊 (Device Info)。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """回傳實體所屬之 Device 裝置結構。"""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=f"中央氣象署雨量監控 ({self.coordinator.location_name})",
            manufacturer="交通部中央氣象署 (CWA)",
            model="自動雨量觀測整合系統 (O-A0002-001)",
            sw_version="1.0.0",
        )


class CwaRainPrecipitationSensor(CwaRainBaseSensor):
    """過去 10 分鐘最大累積降水量感測器。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_precipitation"
        self._attr_name = "過去 10 分鐘降水量"
        self._attr_native_unit_of_measurement = "mm"
        self._attr_device_class = SensorDeviceClass.PRECIPITATION
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:weather-rainy"

    @property
    def native_value(self) -> Optional[float]:
        """回傳當前 4 站中最大之過去 10 分鐘雨量值 (mm)。"""
        if self.coordinator.data:
            return self.coordinator.data.get("max_rain_10min", 0.0)
        return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """回傳詳細屬性字典 (包含各站名稱、代碼、距離、雨量明細)。"""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        return {
            "location_name": data.get("location_name"),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "selection_mode": data.get("selection_mode"),
            "zone_entity": data.get("zone_entity"),
            "active_stations_count": data.get("active_stations_count"),
            "is_raining": data.get("is_raining"),
            "rain_approaching_warning": data.get("rain_approaching"),
            "consecutive_rain_cycles": data.get("consecutive_rain_cycles"),
            "consecutive_dry_cycles": data.get("consecutive_dry_cycles"),
            "cooldown_remaining_cycles": data.get("cooldown_remaining_cycles"),
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


class CwaRainDbzSensor(CwaRainBaseSensor):
    """估計雷達迴波強度感測器 (dBZ)。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_radar_dbz"
        self._attr_name = "推估雷達迴波"
        self._attr_native_unit_of_measurement = "dBZ"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:radar"

    @property
    def native_value(self) -> Optional[float]:
        """回傳依據 Marshall-Palmer 公式換算之雷達反射率強度 (dBZ)。"""
        if self.coordinator.data:
            return self.coordinator.data.get("estimated_dbz", 0.0)
        return None


class CwaRainActiveStationsSensor(CwaRainBaseSensor):
    """目前有雨測站數量感測器。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_stations"
        self._attr_name = "有雨測站數"
        self._attr_native_unit_of_measurement = "站"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:weather-partly-rainy"

    @property
    def native_value(self) -> Optional[int]:
        """回傳目前 4 站中達到降雨門檻之測站數量。"""
        if self.coordinator.data:
            return self.coordinator.data.get("active_stations_count", 0)
        return None

