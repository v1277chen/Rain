"""
中央氣象署雨量監控整合 - 使用者介面設定流程模組 (Config Flow)
檔案名稱：config_flow.py
功能簡述：
    提供 Home Assistant 原生前端 UI 設定嚮導，支援：
    1. 輸入氣象署 API Token 並即時驗證。
    2. 多地點/多座標支援：可從 HA 現有 Zone (如 zone.home, zone.work) 下拉選取，或手動輸入經緯度。
    3. 自訂降雨判定門檻與防抖動參數。
    4. 支援 Options Flow 供使用者隨時在 UI 重新配置門檻參數。
"""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    CONF_RAIN_DETECTED_MM,
    CONF_STATIONS_RAIN_COUNT,
    CONF_HEAVY_RAIN_MM,
    CONF_DEBOUNCE_ON_COUNT,
    CONF_DEBOUNCE_OFF_COUNT,
    CONF_POLLING_INTERVAL,
    DEFAULT_LOCATION_NAME,
    DEFAULT_ZONE_ENTITY,
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


async def validate_cwa_api(hass, api_token: str) -> bool:
    """
    非同步測試氣象署 API 金鑰是否有效。

    參數說明：
        hass: Home Assistant 核心實體。
        api_token (str): 欲驗證的氣象署金鑰。

    回傳值：
        bool: 連線成功且授權有效回傳 True，否則回傳 False。
    """
    session = async_get_clientsession(hass)
    params = {"Authorization": api_token, "limit": 1}
    try:
        async with session.get(CWA_API_BASE_URL, params=params, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                return bool(data.get("success") and str(data.get("success")).lower() == "true")
            return False
    except Exception:
        return False


class CwaRainConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """處理中央氣象署雨量監控整合之設定流程。"""

    VERSION = 1

    def __init__(self):
        """初始化暫存資料字典。"""
        self._data: Dict[str, Any] = {}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """
        第一步：輸入 API Token、地點名稱與選擇座標模式。
        """
        errors = {}

        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            # 驗證 API Token 是否有效
            is_valid = await validate_cwa_api(self.hass, token)
            if not is_valid:
                errors["base"] = "invalid_auth"
            else:
                self._data.update(user_input)
                self._data[CONF_API_TOKEN] = token

                # 若使用者選擇使用現有 HA Zone，導引至 Zone 選擇頁面
                if user_input.get(CONF_USE_ZONE, True):
                    return await self.async_step_zone()
                # 否則導引至手動經緯度輸入頁面
                return await self.async_step_manual()

        schema = vol.Schema({
            vol.Required(CONF_API_TOKEN): str,
            vol.Required(CONF_LOCATION_NAME, default=DEFAULT_LOCATION_NAME): str,
            vol.Required(CONF_USE_ZONE, default=True): bool,
            vol.Required(CONF_SELECTION_MODE, default=DEFAULT_SELECTION_MODE): vol.In({
                MODE_AUTO: "自動挑選最近 4 座測站 (推薦)",
                MODE_FIXED: "固定指定測站 (進階手動)"
            })
        })

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_zone(self, user_input: Optional[Dict[str, Any]] = None):
        """
        第二步 (A 路線)：選擇現有 Home Assistant 區域 (Zone)。
        """
        errors = {}

        # 取得系統中現有之 zone 清單
        zone_entities = self.hass.states.async_entity_ids("zone")
        if not zone_entities:
            zone_entities = [DEFAULT_ZONE_ENTITY]

        if user_input is not None:
            zone_id = user_input[CONF_ZONE_ENTITY]
            self._data[CONF_ZONE_ENTITY] = zone_id
            self._data[CONF_AUTO_SYNC_ZONE] = user_input.get(CONF_AUTO_SYNC_ZONE, True)

            # 讀取目前該 Zone 之經緯度作為初始基準
            zone_state = self.hass.states.get(zone_id)
            if zone_state and zone_state.attributes:
                self._data[CONF_LATITUDE] = float(zone_state.attributes.get("latitude", 23.0150))
                self._data[CONF_LONGITUDE] = float(zone_state.attributes.get("longitude", 120.2050))
            else:
                self._data[CONF_LATITUDE] = 23.0150
                self._data[CONF_LONGITUDE] = 120.2050

            return await self.async_step_thresholds()

        schema = vol.Schema({
            vol.Required(CONF_ZONE_ENTITY, default=zone_entities[0]): vol.In(zone_entities),
            vol.Required(CONF_AUTO_SYNC_ZONE, default=DEFAULT_AUTO_SYNC_ZONE): bool,
        })

        return self.async_show_form(step_id="zone", data_schema=schema, errors=errors)

    async def async_step_manual(self, user_input: Optional[Dict[str, Any]] = None):
        """
        第二步 (B 路線)：手動輸入經緯度座標。
        """
        errors = {}

        if user_input is not None:
            self._data[CONF_LATITUDE] = float(user_input[CONF_LATITUDE])
            self._data[CONF_LONGITUDE] = float(user_input[CONF_LONGITUDE])
            self._data[CONF_AUTO_SYNC_ZONE] = False
            self._data[CONF_ZONE_ENTITY] = None
            return await self.async_step_thresholds()

        # 預設嘗試讀取系統住家座標
        default_lat = self.hass.config.latitude or 23.0150
        default_lon = self.hass.config.longitude or 120.2050

        schema = vol.Schema({
            vol.Required(CONF_LATITUDE, default=float(default_lat)): float,
            vol.Required(CONF_LONGITUDE, default=float(default_lon)): float,
        })

        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_thresholds(self, user_input: Optional[Dict[str, Any]] = None):
        """
        第三步：設定判定門檻、防抖動與輪詢週期。
        """
        if user_input is not None:
            self._data.update(user_input)
            loc_name = self._data.get(CONF_LOCATION_NAME, DEFAULT_LOCATION_NAME)
            return self.async_create_entry(
                title=f"雨量監控 ({loc_name})",
                data=self._data
            )

        schema = vol.Schema({
            vol.Required(CONF_POLLING_INTERVAL, default=DEFAULT_POLLING_INTERVAL): vol.All(int, vol.Range(min=60, max=3600)),
            vol.Required(CONF_RAIN_DETECTED_MM, default=DEFAULT_RAIN_DETECTED_MM): vol.All(float, vol.Range(min=0.0, max=50.0)),
            vol.Required(CONF_STATIONS_RAIN_COUNT, default=DEFAULT_STATIONS_RAIN_COUNT): vol.All(int, vol.Range(min=1, max=4)),
            vol.Required(CONF_HEAVY_RAIN_MM, default=DEFAULT_HEAVY_RAIN_MM): vol.All(float, vol.Range(min=0.1, max=100.0)),
            vol.Required(CONF_DEBOUNCE_ON_COUNT, default=DEFAULT_DEBOUNCE_ON_COUNT): vol.All(int, vol.Range(min=1, max=10)),
            vol.Required(CONF_DEBOUNCE_OFF_COUNT, default=DEFAULT_DEBOUNCE_OFF_COUNT): vol.All(int, vol.Range(min=1, max=20)),
        })

        return self.async_show_form(step_id="thresholds", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """建立 Options Flow 處理器。"""
        return CwaRainOptionsFlowHandler(config_entry)


class CwaRainOptionsFlowHandler(config_entries.OptionsFlow):
    """處理使用者後續於整合面板調整參數之 Options Flow。"""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        """選項設定表單。"""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema({
            vol.Required(
                CONF_POLLING_INTERVAL,
                default=current.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
            ): vol.All(int, vol.Range(min=60, max=3600)),
            vol.Required(
                CONF_RAIN_DETECTED_MM,
                default=current.get(CONF_RAIN_DETECTED_MM, DEFAULT_RAIN_DETECTED_MM)
            ): vol.All(float, vol.Range(min=0.0, max=50.0)),
            vol.Required(
                CONF_STATIONS_RAIN_COUNT,
                default=current.get(CONF_STATIONS_RAIN_COUNT, DEFAULT_STATIONS_RAIN_COUNT)
            ): vol.All(int, vol.Range(min=1, max=4)),
            vol.Required(
                CONF_HEAVY_RAIN_MM,
                default=current.get(CONF_HEAVY_RAIN_MM, DEFAULT_HEAVY_RAIN_MM)
            ): vol.All(float, vol.Range(min=0.1, max=100.0)),
            vol.Required(
                CONF_DEBOUNCE_ON_COUNT,
                default=current.get(CONF_DEBOUNCE_ON_COUNT, DEFAULT_DEBOUNCE_ON_COUNT)
            ): vol.All(int, vol.Range(min=1, max=10)),
            vol.Required(
                CONF_DEBOUNCE_OFF_COUNT,
                default=current.get(CONF_DEBOUNCE_OFF_COUNT, DEFAULT_DEBOUNCE_OFF_COUNT)
            ): vol.All(int, vol.Range(min=1, max=20)),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
