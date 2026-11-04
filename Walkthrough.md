# 中央氣象署雨量監控與預警整合系統實作歷程與驗證報告 (Walkthrough)

本文件詳實記錄從需求分析、模組架構設計、核心演算法實作、防抖動狀態機驗證到 Home Assistant 整合之完整過程。

---

## 一、專案完成項目總覽

| 序號 | 項目 | 檔案 / 模組 | 狀態 | 說明 |
| :---: | :--- | :--- | :---: | :--- |
| 1 | **架構設計規劃** | `rain_monitor_plan.md` | ✅ 完成 | 涵蓋 CWA API 規格、Haversine 距離公式、Marshall-Palmer dBZ 估計與優缺點分析。 |
| 2 | **核心監控與同步服務** | `cwa_ha_rain_monitor.py` | ✅ 完成 | 包含資料抓取、4 站距離評估、防抖動雙開關狀態機與 HA REST API 同步，附完整繁體中文註解。 |
| 3 | **設定檔範本** | `config.example.yaml` | ✅ 完成 | 支援住家經緯度、指定四站 (安南、北區、永康、安定)、門檻與 HA Token 設定。 |
| 4 | **單元與情境模擬測試** | `test_monitor.py` | ✅ 完成 | 5 項單元測試（物理公式、資料解析、全天候降雨防抖動模擬）全數通過。 |
| 5 | **專案說明與操作文件** | `README.md` | ✅ 完成 | 包含機制深度分析、優缺點比較、HA 實體配置、GitHub Pages 自動化設定指南。 |
| 6 | **靜態展示首頁** | `index.html` | ✅ 完成 | 現代化 Tailwind CSS 響應式介面，內嵌互動式即時雨量與雷達迴波模擬器。 |
| 7 | **自動化部署工作流程** | `.github/workflows/deploy.yml` | ✅ 完成 | 配置 GitHub Actions 自動將文件與互動模擬器發佈至 GitHub Pages。 |
| 8 | **容器化封裝定義** | `Dockerfile`, `requirements.txt` | ✅ 完成 | 基於 Python 3.11-slim 最佳化，內建台灣時區與即時日誌輸出。 |
| 9 | **Portainer Stack 配置** | `docker-compose.yml` | ✅ 完成 | 支援 host 網路直連同區網 HA，並提供完整環境變數覆寫機制。 |
| 10 | **Portainer 部署指南** | `PORTAINER_DOCKER_DEPLOY_GUIDE.md` | ✅ 完成 | 詳細記載同區網連線 HA 的設定、防坑細節與圖形介面操作步驟。 |
| 11 | **PVE (192.168.0.110) 專屬部署指南** | `PVE_PORTAINER_DEPLOY_GUIDE.md` | ✅ 完成 | 詳列上傳檔案清單、Windows SCP 單行指令、PVE docker build 與 Portainer 部署流程。 |
| 12 | **Lovelace 儀表板卡片指南** | `LOVELACE_CARD_GUIDE.md` | ✅ 完成 | 詳解自動復原機制、room-elves-card、Mushroom 及原生 Markdown 卡片 YAML 範例。 |

---

## 二、關鍵演算法實作與測試驗證

### 1. Haversine 球面距離計算驗證
- **測試點**：
  - 起點：臺南市安南區約略經緯度 (23.0150, 120.2050)
  - 終點：臺南市北區測站 (23.0039, 120.2183)
- **測試結果**：
  - 算得距離約 $2.08\text{ km}$，符合實地地理跨距。
  - 同點距離測試精準傳回 $0.00\text{ km}$。

### 2. 雷達迴波強度 (dBZ) 反推公式驗證
- **模型**：
  $$\text{dBZ} = 10 \times \log_{10}(200 \times (P_{10min} \times 6)^{1.6})$$
- **各雨量級距輸出結果**：
  - $0.0\text{ mm}$：傳回 $0.0\text{ dBZ}$（無降水）。
  - $0.5\text{ mm}$：換算小時降雨率 $3.0\text{ mm/hr}$，反推為 **$30.6\text{ dBZ}$**（符合氣象局弱降雨黃綠色迴波）。
  - $2.0\text{ mm}$：換算小時降雨率 $12.0\text{ mm/hr}$，反推為 **$40.3\text{ dBZ}$**（符合氣象局中度對流黃橙色迴波）。

### 3. 防抖動 (Debounce) 與磁滯冷卻情境測試
在 `test_monitor.py` 中執行全週期模擬驗證：

```
[階段 T0] 全區無雨 (0, 0, 0, 0)
  -> is_raining = False, rain_approaching = False (正常晴天狀態)

[階段 T1] 僅安南站 1 站微雨 0.2mm (其餘 0mm)
  -> is_raining = False (未達 2 站，不誤報下雨)
  -> rain_approaching = True (成功觸發雨雲接近預警！)

[階段 T2] 安南 0.5mm、北區 0.3mm (達 2 站有雨)
  -> is_raining = True (成功觸發正在下雨！)
  -> rain_approaching = True

[階段 T3] 遭遇短暫間歇停雨 1 週期 (0, 0, 0, 0)
  -> 防抖動生效！is_raining 依然保持 True (避免窗戶立刻重開)
  -> 連續乾燥計數累計 = 1，剩餘冷卻次數 = 2

[階段 T4] 第 2 週期依然無雨 (0, 0, 0, 0)
  -> 防抖動生效！is_raining 依然保持 True
  -> 連續乾燥計數累計 = 2，剩餘冷卻次數 = 1

[階段 T5] 第 3 週期依然無雨 (0, 0, 0, 0)
  -> 達到連續 3 週期 (15分鐘) 無雨門檻！
  -> is_raining 正式切換為 False (安全解除停雨)
  -> rain_approaching 解除切換為 False

[階段 T6] 突發單站局部暴雨 (0, 2.0mm, 0, 0)
  -> 命中單站 >= 1.5mm 驟雨條件！
  -> is_raining 立即跳轉為 True，推估雷達迴波達 40.3 dBZ！
```

**單元測試執行結果：**
```
Ran 5 tests in 0.001s
OK
```

---

## 三、Home Assistant 實體連動架構

系統透過 Home Assistant 的 REST API 直接推送狀態與屬性，無需額外中間件：

### 1. `input_boolean.is_raining` (目前正在下雨)
- **狀態**：`on` 或 `off`
- **主要用途**：連動自動化——關閉天窗、收回戶外遮陽簾、停止草坪自動灑水器。

### 2. `input_boolean.rain_approaching_warning` (雨雲接近預警)
- **狀態**：`on` 或 `off`
- **主要用途**：連動自動化——推播手機通知提醒「周邊測站已有雨滴，建議收衣服」、預防性收回遮陽棚。

### 3. `sensor.cwa_rain_monitor` (綜合氣象感測器)
- **狀態**：四站中之最大 10 分鐘雨量數值 (例如 `1.5`)
- **屬性結構**：
  ```json
  {
    "friendly_name": "氣象署雨量綜合監控",
    "unit_of_measurement": "mm",
    "device_class": "precipitation",
    "state_class": "measurement",
    "max_rain_10min": 1.5,
    "estimated_dbz": 37.8,
    "is_raining": true,
    "rain_approaching_warning": true,
    "active_stations_count": 2,
    "consecutive_rain_cycles": 1,
    "consecutive_dry_cycles": 0,
    "cooldown_remaining_cycles": 0,
    "monitored_stations": [
      {
        "id": "C2O950",
        "name": "安南",
        "distance_km": 1.25,
        "past_10min_mm": 1.5,
        "is_raining": true
      },
      {
        "id": "C0X100",
        "name": "臺南市北區",
        "distance_km": 2.14,
        "past_10min_mm": 0.4,
        "is_raining": true
      },
      {
        "id": "467420",
        "name": "永康",
        "distance_km": 4.52,
        "past_10min_mm": 0.0,
        "is_raining": false
      },
      {
        "id": "C0X150",
        "name": "安定",
        "distance_km": 5.81,
        "past_10min_mm": 0.0,
        "is_raining": false
      }
    ],
    "last_updated": "2026-11-02T15:10:00.000000"
  }
  ```

---

## 四、GitHub Pages 自動部屬確認

- **工作流程檔案**：`.github/workflows/deploy.yml`
- **部署來源**：專案根目錄之 `index.html`
- **展示功能**：
  - 專案介紹與測站狀態展示
  - 四站即時雨量滑桿與雷達迴波計算器
  - 雙狀態開關即時動態模擬
  - Home Assistant 自動化 YAML 範例
- **操作步驟已更新至 `README.md` 第七章節**，使用者只需至儲存庫 Settings -> Pages 將 Source 改為 GitHub Actions 即可完成全自動發佈。

---

## 五、問題、錯誤情境與處置作為全紀錄

詳細之根本原因分析與代碼比對請參閱獨立專屬紀錄檔：[`TROUBLESHOOTING_AND_INCIDENT_LOG.md`](file:///f:/Antigravity/Rain/TROUBLESHOOTING_AND_INCIDENT_LOG.md)。

| 序號 | 問題/錯誤現象 | 根本原因分析 (RCA) | 相關處理作為 (處置措施) | 涉及修改之模組/檔案 |
| :---: | :--- | :--- | :--- | :--- |
| **1** | Portainer 部署報錯：`open Dockerfile: no such file or directory` | 使用 Web editor 時，Portainer 於內部暫存目錄執行 Compose，該處無本地原始碼與 Dockerfile。 | 1. 調整 `docker-compose.yml` 移除強制 `build:`，改指定本機現成映像。<br>2. 建立 Repository 模式引導。<br>3. 提供免 build 之全自動執行 YAML。 | [`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml)<br>[`PORTAINER_DOCKER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PORTAINER_DOCKER_DEPLOY_GUIDE.md) |
| **2** | 容器內無法透過 mDNS (`.local`) 解析 HA 網址 | Docker 預設 Bridge 網路之虛擬 NAT 隔離了區網 mDNS 多播 (5353 port) 封包。 | 1. 在 Compose 啟用 `network_mode: host` 共享宿主機實體網卡。<br>2. 規範優先採用 HA 實體靜態 IP (如 `http://192.168.1.100:8123`)。 | [`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml) |
| **3** | 容器日誌時間產生 8 小時時差 (UTC) | 官方 Python 映像預設時區為 UTC，與氣象署台灣時間 (UTC+8) 不一致。 | 1. 在 Dockerfile 安裝 `tzdata` 並軟連結 `Asia/Taipei`。<br>2. Compose 注入 `TZ=Asia/Taipei`。 | [`Dockerfile`](file:///f:/Antigravity/Rain/Dockerfile)<br>[`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml) |
| **4** | Portainer Logs 日誌延遲不顯示 | Python 於非 TTY 環境預設啟用 I/O 區塊緩衝 (Block Buffering)。 | 注入環境變數 `PYTHONUNBUFFERED=1` 強制無緩衝即時輸出。 | [`Dockerfile`](file:///f:/Antigravity/Rain/Dockerfile)<br>[`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml) |
| **5** | 氣象署異常代碼 (`-99`, `-998`) 致數學對數運算崩潰 | 測站故障或微雨負數旗標代入 Marshall-Palmer 公式引發 `math domain error`。 | 1. `extract_station_info()` 增加資料清洗將負數歸零。<br>2. `calculate_estimated_dbz()` 增加邊界與例外防護。 | [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py)<br>[`test_monitor.py`](file:///f:/Antigravity/Rain/test_monitor.py) |
| **6** | 間歇雨滴致 HA 實體與家電頻繁彈跳 | 單次輪詢欠缺時間維度防抖動與磁滯冷卻。 | 實作非對稱雙計數器狀態機 `RainDebounceStateMachine`，降雨即時開啟 (1次)，停雨冷卻 15 分鐘 (3次)。 | [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) |
| **7** | 純環境變數啟動拋出 `FileNotFoundError` | `load_config` 原預設實體 `config.yaml` 必定存在，不支援純 Docker 微服務注入。 | 改寫 `load_config()`，若無檔案則載入內部預設字典結構，再由系統環境變數覆寫。 | [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) |
| **8** | `docker build` 報錯 `requires exactly 1 argument` | 指令結尾遺漏指向當前目錄上下文的空格與點號 `.`。 | 指令結尾補上 `.`，並於 PVE 部署手冊中特別加註防呆提示。 | [`PVE_PORTAINER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PVE_PORTAINER_DEPLOY_GUIDE.md) |
| **9** | `room-elves-card` 白屏崩潰無法顯示 | 該卡片子項不支持複雜 Jinja2 且未防範屬性空陣列。 | 調整標準相容配置，並引入推薦專業圖表卡片 `weather-chart-card`。 | [`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md) |
| **10** | Markdown 表格歪斜錯位 | Jinja2 換行符干擾 GFM 解析，且欠缺寬度比例約束。 | 調整 Jinja2 換行，但因 HA 核心 XSS 安全過濾器更新，進一步改用純 Markdown（見第 11 項）。 | [`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md) |
| **11** | Markdown 出現 HTML 源碼 | 新版 Home Assistant 安全過濾器 (Sanitizer) 轉義 HTML 標籤。 | 改回標準 GFM 表格語法搭配 `content: \|` 與 `{%- for -%}` 空白修剪，表格完美渲染。 | [`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md) |
| **12** | `weather-chart-card` 實體不符 | 該卡片架構僅接受 `weather.*` 預報實體，不接受 `sensor.*`。 | 分離職責：`weather-chart-card` 綁定天氣實體，雨量監控數據由 Markdown/Entities 卡片呈現。 | [`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md) |
| **13** | 住家座標變更自動切換測站 | 使用者住家經緯度變更時需自動切換為最近 4 座雨量測站。 | 實作 `auto` 距離模式，支援 Haversine 全台測站動態挑選與 HA `zone.home` 座標自動即時同步。 | [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py)<br>[`test_monitor.py`](file:///f:/Antigravity/Rain/test_monitor.py) |
| **14** | 升級 HACS 整合與多座標支援 | 需免手動 Token 並支援多座標（住家+公司）獨立監控。 | 全面構建 HACS 自訂整合，實作 UI Config Flow、多實例、原生 Binary Sensors 與 CWA API 快取機制。 | [`custom_components/cwa_rain/`](file:///f:/Antigravity/Rain/custom_components/cwa_rain/)<br>[`hacs.json`](file:///f:/Antigravity/Rain/hacs.json)<br>[`tests/test_custom_component.py`](file:///f:/Antigravity/Rain/tests/test_custom_component.py) |


