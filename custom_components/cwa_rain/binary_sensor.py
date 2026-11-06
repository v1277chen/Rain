"""
中央氣象署雨量監控整合 - 二元感測器實體平台模組 (Binary Sensor Platform)
檔案名稱：binary_sensor.py
功能簡述：
    提供兩個防抖動二元狀態開關實體，精簡命名對齊 Docker 模式：
    1. 「目前正在下雨」：
       實體代碼為 binary_sensor.is_raining (或多地點加後綴如 binary_sensor.is_raining_gong_si)，
       具備防抖動與 15 分鐘冷卻機制，作為雨遮、百葉窗自動關閉核心條件。
    2. 「雨雲接近預警」：
       實體代碼為 binary_sensor.rain_approaching_warning (或 binary_sensor.rain_approaching_warning_gong_si)，
       只要任一測站偵測到雨滴即時示警，提醒收衣物或準備傘具。
"""

import logging
from typing import Any, Dict, Optional

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
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
    非同步設定雨量二元感測器實體。

    參數說明：
        hass (HomeAssistant): HA 核心物件。
        entry (ConfigEntry): 設定項目實例。
        async_add_entities (AddEntitiesCallback): 新增實體之回呼函式。
    """
    coordinator: CwaRainDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        CwaRainIsRainingBinarySensor(coordinator, entry),
        CwaRainApproachingBinarySensor(coordinator, entry),
    ]

    async_add_entities(entities)


class CwaRainBaseBinarySensor(CoordinatorEntity[CwaRainDataUpdateCoordinator], BinarySensorEntity):
    """雨量二元感測器基底類別。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self.entry = entry
        # 停用 has_entity_name 避免 HA 預設加上長長的中文字拼音
        self._attr_has_entity_name = False

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


class CwaRainIsRainingBinarySensor(CwaRainBaseBinarySensor):
    """正在下雨判定二元感測器 (內建防抖動狀態機)。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        loc_slug = get_location_slug(coordinator.location_name)
        object_id = f"is_raining_{loc_slug}" if loc_slug else "is_raining"

        self.entity_id = f"binary_sensor.{object_id}"
        self._attr_suggested_object_id = object_id

        if loc_slug:
            self._attr_name = f"目前正在下雨 ({coordinator.location_name})"
        else:
            self._attr_name = "目前正在下雨"

        self._attr_unique_id = f"{entry.entry_id}_is_raining"
        self._attr_device_class = BinarySensorDeviceClass.MOISTURE

    @property
    def is_on(self) -> Optional[bool]:
        """
        回傳是否判定正在下雨。
        滿足條件即刻開啟；若停雨則需歷經連續冷卻週期滿後方會轉為 False。
        """
        if self.coordinator.data:
            return bool(self.coordinator.data.get("is_raining", False))
        return False

    @property
    def icon(self) -> str:
        """動態顯示天氣圖示。"""
        return "mdi:weather-pouring" if self.is_on else "mdi:weather-sunny"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """回傳附加屬性。"""
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "friendly_name": self._attr_name,
            "max_rain_10min": data.get("max_rain_10min", 0.0),
            "estimated_dbz": data.get("estimated_dbz", 0.0),
            "last_updated": data.get("timestamp")
        }


class CwaRainApproachingBinarySensor(CwaRainBaseBinarySensor):
    """雨雲接近預警二元感測器。"""

    def __init__(self, coordinator: CwaRainDataUpdateCoordinator, entry: ConfigEntry):
        super().__init__(coordinator, entry)
        loc_slug = get_location_slug(coordinator.location_name)
        object_id = f"rain_approaching_warning_{loc_slug}" if loc_slug else "rain_approaching_warning"

        self.entity_id = f"binary_sensor.{object_id}"
        self._attr_suggested_object_id = object_id

        if loc_slug:
            self._attr_name = f"雨雲接近預警 ({coordinator.location_name})"
        else:
            self._attr_name = "雨雲接近預警"

        self._attr_unique_id = f"{entry.entry_id}_rain_approaching"

    @property
    def is_on(self) -> Optional[bool]:
        """
        回傳是否有雨雲接近。
        當周邊任一測站偵測到有雨，或系統仍處於下雨狀態時為 True。
        """
        if self.coordinator.data:
            return bool(self.coordinator.data.get("rain_approaching", False))
        return False

    @property
    def icon(self) -> str:
        """動態顯示天氣預警圖示。"""
        return "mdi:weather-partly-rainy" if self.is_on else "mdi:weather-cloudy"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """回傳附加屬性。"""
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "friendly_name": self._attr_name,
            "active_stations": data.get("active_stations_count", 0),
            "last_updated": data.get("timestamp")
        }
