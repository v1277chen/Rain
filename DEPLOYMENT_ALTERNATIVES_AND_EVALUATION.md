# 備選部署方案、架構評估與 CI/CD 工作流程手冊

本文件彙整專案開發過程中之**方案評估比較（HACS vs Add-on vs 獨立 Docker）**、**Portainer Stacks (Docker Compose) 獨立容器化部署指南**，以及 **GitHub Pages 與 GitHub Actions 自動化工作流程**，供偏好容器化隔離架構或進階開發者參考。

---

## 目錄

- [一、方案評估：HACS 整合 vs Add-on vs 獨立 Docker 容器](#一方案評估hacs-整合-vs-add-on-vs-獨立-docker-容器)
- [二、外部獨立 Docker 容器部署指南 (Portainer Stacks)](#二外部獨立-docker-容器部署指南-portainer-stacks)
- [三、GitHub Actions 自動化工作流程說明](#三github-actions-自動化工作流程說明)
  - [1. GitHub Pages 模擬展示網頁部署 (`deploy.yml`)](#1-github-pages-模擬展示網頁部署-deployyml)
  - [2. HACS 結構標準規範驗證與單元測試 (`validate.yml`)](#2-hacs-結構標準規範驗證與單元測試-validateyml)
- [四、外部獨立 Python 服務維護與規格說明](#四外部獨立-python-服務維護與規格說明)

---

## 一、方案評估：HACS 整合 vs Add-on vs 獨立 Docker 容器

本專案在規劃初期針對 Home Assistant 各種連動方式進行深度評估：

| 評估維度 | **HACS 自訂整合 (官方首選推薦 ⭐)** | **Home Assistant Add-on** | **Portainer 獨立 Docker 容器** |
| :--- | :--- | :--- | :--- |
| **本質與運作環境** | **HA 核心非同步事件迴圈** (`asyncio`) | **獨立 Linux Docker 容器** (Supervisor 管理) | **獨立 Linux Docker 容器** (外部主機/Portainer) |
| **鑑權機制** | **完全免 Token** (直接呼叫 HA 記憶體 API) | 免手動 Token (Supervisor 自動派發 Token) | 需手動建立 Long-Lived Access Token |
| **多座標支援度** | **最佳**：原生支援 UI 重複新增實例 (住家一個、公司一個)，內建全台 API 共享快取 | 普通：需手動編輯 Options YAML/JSON | 普通：需於 Compose 設定多環境變數或啟動多容器 |
| **通訊延遲與效能** | **最優 (零網路開銷)**：微秒級記憶體傳遞 | 次之：走容器內部虛擬網卡打 REST API | 普通：走區域網路或 Host 網路打 REST API |
| **資源消耗** | **極低** (約 3~8 MB，共用 HA Python 執行環境) | 較大 (約 40~80 MB 獨立 Linux 容器) | 較大 (約 40~80 MB 獨立 Linux 容器) |
| **系統相容度** | **100% 全相容** (HA OS, Container, Supervised, Core) | **受限** (⚠️ 僅限 HA OS / Supervised，純 Docker 無法安裝) | **100% 全相容** (任何具備 Docker 環境之主機均可) |
| **適用族群** | 所有 Home Assistant 使用者 | 偏好 Supervisor 介面管理的使用者 | 偏好服務與 HA 核心進程完全解耦的高級玩家 |

---

## 二、外部獨立 Docker 容器部署指南 (Portainer Stacks)

若您偏好外部進程解耦（例如希望 HA 核心升級或重啟時，雨量計時服務依然在外部持續計時），可採用此獨立容器方案。
* 通用 Portainer 部署指南請參見：[`PORTAINER_DOCKER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PORTAINER_DOCKER_DEPLOY_GUIDE.md)
* **PVE (192.168.0.110) 專屬實戰部署手冊**（含 SCP 傳檔與 `docker build` 步驟）：[`PVE_PORTAINER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PVE_PORTAINER_DEPLOY_GUIDE.md)

### 1. Portainer Stack 快速貼上範本 (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  cwa-rain-monitor:
    container_name: cwa-rain-monitor
    image: cwa-ha-rain-monitor:latest
    restart: unless-stopped
    # 推薦使用 host 網路，免去 Docker 虛擬網路隔離與 DNS 延遲
    network_mode: host
    environment:
      - TZ=Asia/Taipei
      - PYTHONUNBUFFERED=1
      # 【必填】氣象署授權碼
      - CWA_API_TOKEN=YOUR_CWA_API_KEY_HERE
      # 【必填】Home Assistant 實體區網網址 (不可用 homeassistant.local 若在 bridge 模式)
      - HA_BASE_URL=http://192.168.1.100:8123
      # 【必填】Home Assistant 長效存取權杖
      - HA_ACCESS_TOKEN=YOUR_HA_LONG_LIVED_ACCESS_TOKEN_HERE
      # 【選填】住家經緯度與測站模式
      - HOME_LATITUDE=23.0150
      - HOME_LONGITUDE=120.2050
      - STATION_SELECTION_MODE=auto
      - AUTO_SYNC_HA_ZONE=true
      # 【選填】判定門檻與防抖動 (預設 5 分鐘輪詢，15 分鐘連續無雨才關閉)
      - RAIN_DETECTED_MM=0.1
      - HEAVY_RAIN_MM=1.5
      - POLLING_INTERVAL_SECONDS=300
      - DEBOUNCE_OFF_COUNT=3
      - DEBOUNCE_ON_COUNT=1
    deploy:
      resources:
        limits:
          cpus: '0.20'
          memory: 128M
```

---

## 三、GitHub Actions 自動化工作流程說明

專案於 `.github/workflows/` 內建兩套全自動 CI/CD 流程：

### 1. GitHub Pages 模擬展示網頁部署 (`deploy.yml`)
- **觸發時機**：推送至 `main` 分支時自動執行。
- **作用**：自動將專案根目錄的 `index.html`（互動式雷達迴波模擬器與展示儀表板）發佈至 GitHub Pages。
- **啟用路徑**：GitHub 儲存庫 $\to$ Settings $\to$ Pages $\to$ Source 選擇 `GitHub Actions`。

### 2. HACS 結構標準規範驗證與單元測試 (`validate.yml`)
- **觸發時機**：推送或發起 Pull Request 時自動執行。
- **作用**：
  1. 建立 Python 3.11 環境並自動執行 `test_monitor.py` 與 `tests/test_custom_component.py`。
  2. 調用官方 `hacs/action@main` 自動檢查 `hacs.json`、`manifest.json` 與元件目錄結構規範，確保隨時符合 HACS 商店上架標準。

---

## 四、外部獨立 Python 服務維護與規格說明

針對外部獨立服務腳本 [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) 之函式清單：

| 模組 / 函式 | 參數型態 | 回傳值型態 | 功能說明 |
| :--- | :--- | :--- | :--- |
| `haversine_distance(lat1, lon1, lat2, lon2)` | `(float, float, float, float)` | `float` | 計算地球表面兩點之大圓球面距離 (公里 km)。 |
| `calculate_estimated_dbz(past_10min_rain_mm)` | `(float)` | `float` | 套用 Marshall-Palmer $Z=200\times R^{1.6}$ 氣象經驗模型，由 10 分鐘雨量換算雷達迴波強度 (dBZ)。 |
| `CwaRainDataFetcher.fetch_raw_stations()` | 無 | `List[Dict[str, Any]]` | 發送 HTTP GET 請求至氣象署 API (O-A0002-001)，解析 JSON 原始資料。 |
| `CwaRainDataFetcher.extract_station_info(station_dict)` | `(Dict[str, Any])` | `Optional[Dict[str, Any]]` | 標準化提取測站 ID、名稱、座標與 10 分鐘雨量，並將 -99 等異常值歸零。 |
| `StationEvaluator.update_home_location(new_lat, new_lon)` | `(float, float)` | `bool` | 外部獨立服務模式中動態更新住家經緯度座標。 |
| `StationEvaluator.select_four_stations(all_stations)` | `(List[Dict[str, Any]])` | `List[Dict[str, Any]]` | 依據模式 (fixed 或 auto) 挑選目標 4 站，計算各站離家距離並由近至遠排序。 |
| `RainDebounceStateMachine.evaluate(selected_stations)` | `(List[Dict[str, Any]])` | `Dict[str, Any]` | 獨立狀態機，執行多站雨量投票、驟雨判定，並維護連續冷卻計數器。 |
| `HomeAssistantSync.sync_all(evaluation_result, home_lat, home_lon, selection_mode)` | `(Dict[str, Any], float, float, str)` | `None` | 透過 HA REST API 更新兩個 input_boolean 及一個綜合 sensor。 |
