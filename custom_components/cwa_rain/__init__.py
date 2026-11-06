"""
中央氣象署雨量監控整合 - 整合進入點模組
檔案名稱：__init__.py
功能簡述：
    處理 Home Assistant 的配置項目 (ConfigEntry) 生命週期，
    包含初始化、轉發實體平台註冊 (Platforms forwarding)、重新載入與卸載。
"""

import os
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS, CONF_API_TOKEN
from .coordinator import CwaApiClient, CwaRainDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """
    非同步設定 cwa_rain 全域元件環境。

    用途說明：
        註冊元件專屬的靜態 HTTP 資源路徑 (/cwa_rain_static/CWA.png 與 /cwa_rain_static/icon.png)，
        使 Home Assistant 前端介面、Lovelace 卡片、通知訊息均能直接載入氣象署專屬品牌圖示。

    參數說明：
        hass (HomeAssistant): Home Assistant 核心實體。
        config (dict): YAML 全域配置字典 (本整合主要透過 UI Config Flow 設定)。

    回傳值：
        bool: 固定回傳 True。
    """
    cwa_png_path = os.path.join(os.path.dirname(__file__), "CWA.png")
    icon_png_path = os.path.join(os.path.dirname(__file__), "icon.png")

    # 若 Home Assistant HTTP 伺服器已啟動，註冊靜態圖檔路徑
    if hasattr(hass, "http") and hasattr(hass.http, "register_static_path"):
        try:
            if os.path.exists(cwa_png_path):
                hass.http.register_static_path("/cwa_rain_static/CWA.png", cwa_png_path, cache_headers=True)
            if os.path.exists(icon_png_path):
                hass.http.register_static_path("/cwa_rain_static/icon.png", icon_png_path, cache_headers=True)
            _LOGGER.debug("成功註冊氣象署圖示靜態路徑 /cwa_rain_static/CWA.png")
        except Exception as exc:
            _LOGGER.debug("註冊氣象署靜態圖檔路徑時略過: %s", exc)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    非同步設定單一配置項目 (Config Entry)。

    參數說明：
        hass (HomeAssistant): Home Assistant 核心實體。
        entry (ConfigEntry): 本次載入之設定項目物件。

    回傳值：
        bool: 設定成功回傳 True，失敗回傳 False。
    """
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("clients", {})

    api_token = entry.data.get(CONF_API_TOKEN, "")

    # 共享 API Client 機制：相同 API Token 共享同一個快取客戶端
    if api_token not in hass.data[DOMAIN]["clients"]:
        hass.data[DOMAIN]["clients"][api_token] = CwaApiClient(hass, api_token)
    shared_client: CwaApiClient = hass.data[DOMAIN]["clients"][api_token]

    # 合併 entry.data 與 entry.options (允許使用者後續在 UI 透過 Options Flow 調整參數)
    combined_config = {**entry.data, **entry.options}

    # 建立該地點專屬的非同步協調器
    coordinator = CwaRainDataUpdateCoordinator(
        hass=hass,
        client=shared_client,
        entry_data=combined_config
    )

    # 執行第一次啟動資料抓取與評估
    await coordinator.async_config_entry_first_refresh()

    # 儲存協調器實例
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # 向下轉發實體平台 (sensor 與 binary_sensor)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 監聽設定變更事件 (使用者於 UI 調整選項時自動重新載入)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("成功載入中央氣象署雨量監控實例 [%s]", coordinator.location_name)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    非同步卸載配置項目。

    參數說明：
        hass (HomeAssistant): Home Assistant 核心實體。
        entry (ConfigEntry): 待卸載之設定項目。

    回傳值：
        bool: 卸載成功回傳 True。
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info("成功卸載中央氣象署雨量監控實例 [%s]", entry.title)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    當使用者在 UI 變更 Options 時觸發非同步重新載入。

    參數說明：
        hass (HomeAssistant): Home Assistant 核心實體。
        entry (ConfigEntry): 待重新載入之設定項目。
    """
    await hass.config_entries.async_reload(entry.entry_id)

