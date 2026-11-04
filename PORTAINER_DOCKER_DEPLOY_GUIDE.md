# Portainer Stacks (Docker Compose) 完整部署指南

本文件提供在 **Portainer Stacks** 中，以容器化架構部署「**中央氣象署雨量監控與 Home Assistant 同步服務**」的完整步驟、設定說明及同區網 (LAN) 連線優化指南。

---

## 目錄
- [一、前置準備工作](#一前置準備工作)
- [二、Portainer Stacks 一鍵部署 YAML](#二portainer-stacks-一鍵部署-yaml)
- [三、Portainer 圖形介面操作步驟](#三portainer-圖形介面操作步驟)
- [四、同區網 (LAN) 連線關鍵細節與防坑指南](#四同區網-lan-連線關鍵細節與防坑指南)
- [五、環境變數對照表](#五環境變數對照表)
- [六、日誌檢查與故障排除 (Troubleshooting)](#六日誌檢查與故障排除-troubleshooting)

---

## 一、前置準備工作

在進入 Portainer 建立 Stack 之前，請先備齊以下三項關鍵資訊：

### 1. 取得氣象署開放資料 API 授權碼 (Token)
1. 前往 [中央氣象署開放資料平台](https://opendata.cwa.gov.tw/)。
2. 註冊登入會員後，點選個人首頁之「API 授權碼」。
3. 複製屬於您的專屬 Token（格式通常為 `CWA-XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX`）。

### 2. 取得 Home Assistant 區網 IP 與長效存取權杖 (Token)
1. **確認 HA 區域網路 IP**：
   - 請至路由器後台或 HA「設定」->「系統」->「網路」中確認 HA 的區域網路實體 IP（例如：`http://192.168.1.100:8123`）。
   - **強烈建議**：在路由器中將 HA 綁定為固定 IP (Static DHCP Lease)。
2. **生成長效存取權杖**：
   - 登入 Home Assistant 網頁後台。
   - 點擊左下角您的**個人帳號名稱 (Profile)**。
   - 滑動至最下方找到**「長效存取權杖 (Long-Lived Access Tokens)」**。
   - 點擊「建立權杖」，輸入名稱（如 `Portainer Rain Monitor`），並將生成的長字串完整複製妥善保存。

### 3. 在 Home Assistant 中建立對應實體
前往 HA「設定」->「裝置與服務」->「輔助程式 (Helpers)」->「新增輔助程式」->「切換開關 (input_boolean)」，分別建立兩個開關：
* 實體 ID：`input_boolean.is_raining`（名稱：目前正在下雨）
* 實體 ID：`input_boolean.rain_approaching_warning`（名稱：雨雲接近預警）

*(亦可在 `configuration.yaml` 加入)*：
```yaml
input_boolean:
  is_raining:
    name: "目前正在下雨"
    icon: mdi:weather-pouring
  rain_approaching_warning:
    name: "雨雲接近預警"
    icon: mdi:weather-partly-rainy
```

---

## 二、Portainer Stacks 一鍵部署 YAML

在 Portainer 的 Web Editor 中，直接貼上以下 Compose 配置。

> **提示**：若您是在具備本專案原始碼的環境建立 Stack，可使用 `build: .`；若要在純獨立 Portainer 上部署，建議將建置好的映像標籤指定為 `image`。

```yaml
version: '3.8'

services:
  cwa-rain-monitor:
    container_name: cwa-rain-monitor
    # 若在包含 Dockerfile 的專案目錄下直接建置
    build:
      context: https://github.com/YOUR_GITHUB_USER/Rain.git#main
      dockerfile: Dockerfile
    # 或直接使用本地已 build 之映像名稱
    image: cwa-ha-rain-monitor:latest
    restart: unless-stopped
    
    # 【關鍵推薦】同區網環境使用 host 網路模式
    network_mode: host
    
    environment:
      # 強制容器時區為台灣時間 (UTC+8)
      - TZ=Asia/Taipei
      # 即時輸出 stdout/stderr，免去 Portainer 日誌緩衝
      - PYTHONUNBUFFERED=1
      
      # ------------------------------------------------------------------------
      # 【必填 1】中央氣象署 API 設定
      # ------------------------------------------------------------------------
      - CWA_API_TOKEN=CWA-YOUR-ACTUAL-API-TOKEN-HERE
      - CWA_DATASET_ID=O-A0002-001
      
      # ------------------------------------------------------------------------
      # 【必填 2】Home Assistant 連線設定 (同區網)
      # ------------------------------------------------------------------------
      - HA_BASE_URL=http://192.168.1.100:8123
      - HA_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.YOUR_ACTUAL_TOKEN_HERE
      
      # ------------------------------------------------------------------------
      # 【選填】住家地理經緯度 (預設為臺南市安南/北區交界)
      # ------------------------------------------------------------------------
      - HOME_LATITUDE=23.0150
      - HOME_LONGITUDE=120.2050
      
      # 測站模式：'fixed' (鎖定指定4站: 安南/北區/永康/安定) 或 'auto' (自動距離篩選)
      - STATION_SELECTION_MODE=fixed
      
      # ------------------------------------------------------------------------
      # 【選填】判定門檻與防抖動機制
      # ------------------------------------------------------------------------
      - RAIN_DETECTED_MM=0.1          # 單站微雨判定門檻 (mm)
      - HEAVY_RAIN_MM=1.5             # 單站驟雨判定門檻 (mm，任一站達標立即下雨)
      - POLLING_INTERVAL_SECONDS=300  # 輪詢頻率 (300秒 = 5分鐘)
      - DEBOUNCE_OFF_COUNT=3          # 停雨冷卻連續次數 (連續 3 次無雨 = 15分鐘才關閉)
      - DEBOUNCE_ON_COUNT=1           # 降雨觸發連續次數 (連續 1 次滿足立即開啟)
      
    deploy:
      resources:
        limits:
          cpus: '0.20'
          memory: 128M
```

---

## 三、Portainer 圖形介面操作步驟

1. **進入 Portainer 主控台**：
   - 開啟瀏覽器輸入 Portainer 網址（例如 `https://192.168.1.5:9443` 或 `http://192.168.1.5:9000`）。
2. **新增 Stack**：
   - 點擊左側選單的 **「Stacks」**。
   - 點擊右上角的 **「+ Add stack」**。
3. **填寫 Stack 資訊**：
   - **Name**：輸入 `cwa-rain-monitor`。
   - **Build method**：選擇 **Web editor**。
4. **貼上與修改設定**：
   - 將上方第二章節的 YAML 內容完整貼入編輯器框中。
   - 將 `CWA_API_TOKEN` 替換為您的氣象署授權碼。
   - 將 `HA_BASE_URL` 改為您 HA 的真實區網 IP（如 `http://192.168.1.100:8123`）。
   - 將 `HA_ACCESS_TOKEN` 替換為您的 HA 長效權杖。
5. **部署服務**：
   - 滑動至頁面最下方，點擊 **「Deploy the stack」**。
   - Portainer 將自動下載基底映像檔、安裝環境並啟動容器。

---

## 四、同區網 (LAN) 連線關鍵細節與防坑指南

### 1. 為何強烈推薦 `network_mode: host`？
* **問題根源**：Docker 預設的 `bridge` 網路模式是一個獨立的虛擬內部子網（通常為 `172.17.0.0/16`）。在此模式下，容器內部無法解析區域網路內的 mDNS 網域名稱（例如 `homeassistant.local`），時常導致 `Name or service not known` 錯誤。
* **Host 模式優勢**：使用 `network_mode: host` 時，容器直接使用宿主機的實體網卡與 IP，與 Home Assistant 處於同一廣播網段：
  1. 免去 Docker 虛擬 NAT 轉發損耗。
  2. 完美支援區網 IP 直連與區域網路廣播解析。

### 2. 若必須使用 `bridge` 網路模式的正確設定
若您的 Portainer 環境不允許使用 host 模式（例如某些雲端環境或特定 Synology NAS 限制）：
1. 移除 `network_mode: host`。
2. **切勿使用** `http://homeassistant.local:8123`。
3. **務必使用純數字實體區網 IP**，例如 `http://192.168.1.100:8123`。

---

## 五、環境變數對照表

本服務設計為「**設定檔與環境變數雙軌支援**」。若未掛載 `config.yaml`，系統會自動套用環境變數覆寫：

| 環境變數名稱 | 預設值 | 型態 | 說明 |
| :--- | :---: | :---: | :--- |
| `TZ` | `Asia/Taipei` | 字串 | 容器標準時區，確保 Log 時間與台灣氣象觀測一致。 |
| `PYTHONUNBUFFERED` | `1` | 數值 | 強制 Python 即時輸出日誌，避免緩衝。 |
| `CWA_API_TOKEN` | *(必填)* | 字串 | 中央氣象署開放資料平台授權碼。 |
| `CWA_DATASET_ID` | `O-A0002-001` | 字串 | 自動雨量站資料集編號。 |
| `HA_BASE_URL` | *(必填)* | 字串 | Home Assistant 服務網址 (含 Port 8123)。 |
| `HA_ACCESS_TOKEN` | *(必填)* | 字串 | Home Assistant 長效存取權杖 (Bearer Token)。 |
| `HOME_LATITUDE` | `23.0150` | 浮點數 | 住家緯度 (用於 Haversine 球面距離計算)。 |
| `HOME_LONGITUDE` | `120.2050` | 浮點數 | 住家經度。 |
| `STATION_SELECTION_MODE` | `fixed` | 字串 | `fixed` (鎖定指定4站) 或 `auto` (自動距離排序)。 |
| `RAIN_DETECTED_MM` | `0.1` | 浮點數 | 單站判定有雨之最低累積雨量 (mm)。 |
| `HEAVY_RAIN_MM` | `1.5` | 浮點數 | 單站驟雨判定門檻 (mm)。 |
| `POLLING_INTERVAL_SECONDS` | `300` | 整數 | 抓取頻率 (秒)，預設 300 秒 = 5 分鐘。 |
| `DEBOUNCE_OFF_COUNT` | `3` | 整數 | 停雨冷卻連續次數 (3次 = 15分鐘冷卻)。 |
| `DEBOUNCE_ON_COUNT` | `1` | 整數 | 降雨觸發連續次數 (1次 = 即時警戒)。 |

---

## 六、日誌檢查與故障排除 (Troubleshooting)

部署完成後，點擊 Portainer 中的容器名稱 `cwa-rain-monitor`，進入 **「Logs」** 頁籤：

### 1. 正常運行日誌範例：
```log
2026-11-02 15:45:00 [INFO] 正在啟動中央氣象署雨量監控服務...
2026-11-02 15:45:00 [INFO] 已透過環境變數 CWA_API_TOKEN 覆寫氣象署金鑰
2026-11-02 15:45:00 [INFO] 已透過環境變數 HA_BASE_URL 覆寫 HA 網址: http://192.168.1.100:8123
2026-11-02 15:45:00 [INFO] 進入常駐輪詢模式，每隔 300 秒 (5.0 分鐘) 更新一次...
2026-11-02 15:45:01 [INFO] 正在連線氣象署 API (資料集: O-A0002-001) 抓取雨量資料...
2026-11-02 15:45:02 [INFO] 成功抓取氣象署資料，共取得 1142 個測站記錄
2026-11-02 15:45:02 [INFO] 【固定測站模式】已鎖定指定之 4 個測站
2026-11-02 15:45:02 [INFO] === 監控測站降雨即時數據 ===
2026-11-02 15:45:02 [INFO]   [C2O950 安南] 距離家: 1.25 km | 過去10分雨量: 0.00 mm
2026-11-02 15:45:02 [INFO]   [C0X100 臺南市北區] 距離家: 2.14 km | 過去10分雨量: 0.00 mm
2026-11-02 15:45:02 [INFO]   [467420 永康] 距離家: 4.52 km | 過去10分雨量: 0.00 mm
2026-11-02 15:45:02 [INFO]   [C0X150 安定] 距離家: 5.81 km | 過去10分雨量: 0.00 mm
2026-11-02 15:45:02 [INFO] === 判定結論 ===
2026-11-02 15:45:02 [INFO]   最大10分雨量: 0.00 mm | 推估雷達迴波: 0.0 dBZ | 有雨測站數: 0
2026-11-02 15:45:02 [INFO]   【正在下雨 is_raining】: False (連續有雨:0, 連續無雨:1, 離解除還差:0)
2026-11-02 15:45:02 [INFO]   【雨雲接近預警 rain_approaching】: False
2026-11-02 15:45:02 [INFO] 成功同步 HA 實體 [input_boolean.is_raining] -> 狀態: off
2026-11-02 15:45:02 [INFO] 成功同步 HA 實體 [input_boolean.rain_approaching_warning] -> 狀態: off
2026-11-02 15:45:02 [INFO] 成功同步 HA 實體 [sensor.cwa_rain_monitor] -> 狀態: 0.0
2026-11-02 15:45:02 [INFO] 休眠 300 秒後進行下一次輪詢...
```

### 2. 常見錯誤與排除方式：
* **`HTTP 401 Unauthorized`**：
  * 原因：HA 的 Access Token 填錯，或氣象署 API Token 未授權。
  * 排除：重新至 HA 個人資料頁生成 Token 並更新 Stack 環境變數。
* **`ConnectionRefusedError` 或 `Failed to establish a new connection`**：
  * 原因：HA IP 填寫錯誤、防火牆阻擋，或使用 bridge 模式時填了 `homeassistant.local`。
  * 排除：將網路改為 `network_mode: host`，並確保 `HA_BASE_URL` 為實體 IP（如 `http://192.168.1.100:8123`）。
* **實體未更新**：
  * 原因：HA 中尚未手動建立 `input_boolean.is_raining` 與 `input_boolean.rain_approaching_warning`。
  * 排除：請至 HA「輔助程式」中建立這兩個布林開關。

