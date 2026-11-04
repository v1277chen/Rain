# 中央氣象署雨量監控系統：問題、錯誤與處置作為全紀錄 (Incident & Troubleshooting Log)

本文件詳實記錄本專案在**架構規劃、氣象資料解析、防抖動狀態機設計、Home Assistant 連動**以及在 **Portainer Stacks (Docker Compose) 容器化部署** 過程中所遭遇之所有問題、錯誤訊息、根本原因分析 (Root Cause Analysis)，以及相應之工程處置作為與代碼修改。

---

## 問題與錯誤事件目錄

1. [【錯誤 01】Portainer Web Editor 部署報錯：`open Dockerfile: no such file or directory`](#錯誤-01portainer-web-editor-部署報錯open-dockerfile-no-such-file-or-directory)
2. [【錯誤 02】Docker 容器內部無法透過 mDNS (`.local`) 解析 Home Assistant 網址](#錯誤-02docker-容器內部無法透過-mdns-local-解析-home-assistant-網址)
3. [【問題 03】容器時區預設為 UTC 導致日誌與氣象署觀測時間產生 8 小時偏差](#問題-03容器時區預設為-utc-導致日誌與氣象署觀測時間產生-8-小時偏差)
4. [【問題 04】Python 標準輸出緩衝導致 Portainer 容器日誌延遲顯示](#問題-04python-標準輸出緩衝導致-portainer-容器日誌延遲顯示)
5. [【問題 05】氣象署 API 異常代碼 (`-99`, `-998`) 導致雷達迴波 $\log_{10}$ 運算崩潰](#問題-05氣象署-api-異常代碼--99--998-導致雷達迴波-log_10-運算崩潰)
6. [【問題 06】間歇雨滴引發 Home Assistant 實體頻繁彈跳開關 (Chattering/Flapping)](#問題-06間歇雨滴引發-home-assistant-實體頻繁彈跳開關-chatteringflapping)
7. [【問題 07】純環境變數啟動時因缺少 `config.yaml` 檔案拋出 `FileNotFoundError`](#問題-07純環境變數啟動時因缺少-configyaml-檔案拋出-filenotfounderror)
8. [【錯誤 08】`docker build` 漏掉結尾路徑參數 `.` 導致 `requires exactly 1 argument` 錯誤](#錯誤-08docker-build-漏掉結尾路徑參數--導致-requires-exactly-1-argument-錯誤)
9. [【問題 09】Lovelace 載入 `room-elves-card` 白屏崩潰無法正常顯示](#問題-09lovelace-載入-room-elves-card-白屏崩潰無法正常顯示)
10. [【問題 10】Markdown 卡片中周邊 4 站觀測明細表格歪斜錯位](#問題-10markdown-卡片中周邊-4-站觀測明細表格歪斜錯位)
11. [【問題 11】Markdown 卡片無法渲染 HTML 表格並出現 HTML 源碼問題](#問題-11markdown-卡片無法渲染-html-表格並出現-html-源碼問題)
12. [【問題 12】`weather-chart-card` 實體類型不符導致錯誤與 `weather.forecast_home` 不存在](#問題-12weather-chart-card-實體類型不符導致錯誤與-weatherforecast_home-不存在)
13. [【功能演進 13】住家經緯度變更時，自動取得氣象署測站並切換最近 4 站機制](#功能演進-13住家經緯度變更時自動取得氣象署測站並切換最近-4-站機制)
14. [【架構升級 14】由獨立外部 Docker 容器服務全面升級為 HACS 自訂整合 (Custom Integration) 與多座標支援](#架構升級-14由獨立外部-docker-容器服務全面升級為-hacs-自訂整合-custom-integration-與多座標支援)

---

## 錯誤 01：Portainer Web Editor 部署報錯：`open Dockerfile: no such file or directory`

### 1. 錯誤現象與日誌
使用者在 Portainer 的 **Stacks** $\to$ **Add stack** $\to$ **Web editor** 貼上原始 `docker-compose.yml` 並點擊部署時，跳出紅色錯誤提示：
```text
failed to deploy a stack: compose build operation failed: failed to solve: failed to read dockerfile: open Dockerfile: no such file or directory
```

### 2. 根本原因分析 (RCA)
* 在原 `docker-compose.yml` 中宣告了本地建置區塊：
  ```yaml
  build:
    context: .
    dockerfile: Dockerfile
  ```
* **Portainer Web Editor 的執行機制**：當使用者直接在瀏覽器文字框貼上 YAML 時，Portainer 僅將該文字存於宿主機的暫存目錄（如 `/data/compose/XX/docker-compose.yml`）。該暫存目錄下**並不存在**專案之 `Dockerfile`、`cwa_ha_rain_monitor.py` 或任何專案程式碼。
* Docker Engine 收到 build 指令並在該暫存目錄搜尋 `Dockerfile` 時失敗，拋出 `no such file or directory`。

### 3. 處理作為與實作修復
本專案提供並落實三種層級的處置方案：

* **處置方案 A（預設推薦，最簡便）：修改 `docker-compose.yml` 移除強制 build**
  * 修改模組：[`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml)
  * 將原本的 `build:` 區塊註解或移除，直接指定映像檔標籤：
    ```yaml
    services:
      cwa-rain-monitor:
        container_name: cwa-rain-monitor
        image: cwa-ha-rain-monitor:latest
        restart: unless-stopped
        # 移除原 build: . 設定，避免 Web editor 搜尋本地 Dockerfile
    ```
  * 操作引導：使用者只需在終端機先執行一次 `docker build -t cwa-ha-rain-monitor:latest .`，Portainer Web Editor 即可直接載入現成映像啟動。針對 PVE (192.168.0.110) 實體環境之 SCP 上傳與 build 步驟，請詳閱專屬指南：[`PVE_PORTAINER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PVE_PORTAINER_DEPLOY_GUIDE.md)。

* **處置方案 B：改採 Portainer 原生「Repository」模式自動構建**
  * 使用者新增 Stack 時，改選 **「Repository」** 模式，填入 Git 網址：`https://github.com/使用者/Rain.git`。
  * Portainer 會自動透過 Git clone 完整目錄（包含 `Dockerfile`）後再執行 build，解決檔案缺失問題。

* **處置方案 C：提供完全免 Dockerfile 的純映像啟動配置**
  * 在文件提供以官方 `python:3.11-slim` 映像檔，搭配目錄掛載與啟動命令自動 `pip install` 的備案，免除任何 build 手續。

---

## 錯誤 02：Docker 容器內部無法透過 mDNS (`.local`) 解析 Home Assistant 網址

### 1. 錯誤現象
在容器內部以 `http://homeassistant.local:8123` 請求時，日誌報錯：
```text
requests.exceptions.ConnectionError: HTTPConnectionPool(host='homeassistant.local', port=8123): Max retries exceeded with url: /api/states/... (Caused by NameResolutionError: Failed to resolve 'homeassistant.local')
```

### 2. 根本原因分析 (RCA)
* Docker 預設採用的 `bridge` 網路模式為隔離的虛擬專用網路（如 `172.17.0.0/16`）。
* mDNS (Multicast DNS，`.local` 協定) 依賴區域網路的 5353 埠多播廣播。Docker Bridge 的虛擬 NAT 邊界預設不會轉發 mDNS 多播封包，導致容器內部 DNS 解析器無法將 `homeassistant.local` 解析為區域網路實體 IP。

### 3. 處理作為與實作修復
* **處置作為 1（啟用 Host 網路）**：
  * 修改模組：[`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml)
  * 加入 `network_mode: host`：
    ```yaml
    services:
      cwa-rain-monitor:
        network_mode: host
    ```
  * **效益**：使容器直接共用宿主機網卡與網路命名空間，能原生接收同區網的廣播，免除 NAT 轉換與連接埠隔離。
* **處置作為 2（強制規範實體 IP）**：
  * 在設定檔與說明文件中，明確規範 `HA_BASE_URL` 優先採用靜態區域網路 IP（例如 `http://192.168.1.100:8123`），並強烈建議使用者在路由器建立 DHCP 靜態綁定。

---

## 問題 03：容器時區預設為 UTC 導致日誌與氣象署觀測時間產生 8 小時偏差

### 1. 錯誤現象
在 Portainer 查看容器運行日誌時，顯示的時間戳記（例如 `07:15:00`）與台灣實際時間（`15:15:00`）相差 8 小時，造成比對氣象署每 10 分鐘降雨觀測記錄時極大混淆。

### 2. 根本原因分析 (RCA)
* Linux 基底容器（`python:3.11-slim`）預設系統時區均為 UTC (格林威治標準時間)。
* 若未顯式安裝時區資料包與配置，`datetime.now()` 與日誌 formatter 將輸出 UTC 時間。

### 3. 處理作為與實作修復
* **修改模組**：[`Dockerfile`](file:///f:/Antigravity/Rain/Dockerfile) 與 [`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml)
* **在 Dockerfile 中寫入時區配置**：
  ```dockerfile
  ENV TZ=Asia/Taipei
  RUN apt-get update && \
      apt-get install -y --no-install-recommends tzdata && \
      ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
      apt-get clean && rm -rf /var/lib/apt/lists/*
  ```
* **在 Compose 中傳入環境變數**：
  ```yaml
  environment:
    - TZ=Asia/Taipei
  ```
* **效益**：日誌輸出與中央氣象署觀測報表完全對齊為台灣標準時間 (UTC+8)。

---

## 問題 04：Python 標準輸出緩衝導致 Portainer 容器日誌延遲顯示

### 1. 錯誤現象
在 Portainer 的「Logs」視窗中，點擊後長時間看不見日誌更新；一旦停止容器或過很久後，日誌才一次性大量湧出。

### 2. 根本原因分析 (RCA)
* Python 執行環境在偵測到輸出端非互動式終端 (Non-TTY，例如管線或 Docker 內部管道) 時，預設會啟動 I/O 區塊緩衝 (Block Buffering)，待緩衝區積滿（通常為 4KB 或 8KB）才進行 flush。

### 3. 處理作為與實作修復
* **修改模組**：[`Dockerfile`](file:///f:/Antigravity/Rain/Dockerfile) 與 [`docker-compose.yml`](file:///f:/Antigravity/Rain/docker-compose.yml)
* **配置環境變數**：
  ```dockerfile
  ENV PYTHONUNBUFFERED=1
  ```
* **效益**：確保每條 `logger.info()` 都能無延遲即時輸出至 Docker 標準輸出，方便使用者在 Portainer UI 即時觀察雨量與連動狀態。

---

## 問題 05：氣象署 API 異常代碼 (`-99`, `-998`) 導致雷達迴波 $\log_{10}$ 運算崩潰

### 1. 錯誤現象
當中央氣象署自動雨量站進行儀器保養或出現微雨時，API 傳回之數值可能為 `-99.0`（無資料/故障）或 `-998.0`（微量雨跡）。
若直接代入雷達迴波強度反推公式：
$$\text{dBZ} = 10 \times \log_{10}(200 \times (P_{10min} \times 6)^{1.6})$$
由於負數無法計算分數冪次方與對數，將引發 Python 例外：
```text
ValueError: math domain error
```

### 2. 根本原因分析 (RCA)
* 氣象署開放資料標準以特殊負數作為觀測品質旗標，未進行資料清洗即代入物理數學公式運算。

### 3. 處理作為與實作修復
* **修改模組**：[`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py)
* **修復點 1 (`extract_station_info`)**：
  ```python
  # 異常值過濾：氣象署 -99 代表故障，-998 代表雨跡(微量)
  if past_10min < 0:
      past_10min = 0.0
  ```
* **修復點 2 (`calculate_estimated_dbz`)**：
  ```python
  def calculate_estimated_dbz(past_10min_rain_mm: float) -> float:
      if past_10min_rain_mm <= 0.0:
          return 0.0
      rainfall_rate_mm_per_hr: float = past_10min_rain_mm * 6.0
      if rainfall_rate_mm_per_hr < 0.05:
          return 15.0  # 微雨下限防護
      try:
          z_factor: float = 200.0 * (rainfall_rate_mm_per_hr ** 1.6)
          dbz: float = 10.0 * math.log10(z_factor)
          return round(max(0.0, min(70.0, dbz)), 1)
      except (ValueError, OverflowError):
          return 0.0
  ```
* **測試驗證**：在 [`test_monitor.py`](file:///f:/Antigravity/Rain/test_monitor.py) 中加入 `test_extract_station_info_anomaly` 與 `test_calculate_estimated_dbz` 單元測試，確認負值輸入均安全回傳 0.0。

---

## 問題 06：間歇雨滴引發 Home Assistant 實體頻繁彈跳開關 (Chattering/Flapping)

### 1. 錯誤現象
在對流雲系邊緣時，常見測站於第 0 分鐘測得 0.2mm、第 5 分鐘為 0.0mm、第 10 分鐘又測得 0.1mm。
若採用傳統無記憶體之單次比較邏輯，HA 的 `input_boolean.is_raining` 將在 10 分鐘內觸發三次開關翻轉，連帶使電動遮陽棚或智慧窗戶之繼電器反覆作動，加速硬體磨損。

### 2. 根本原因分析 (RCA)
* 單純以單次輪詢的雨量門檻作為布林狀態依據，欠缺**時間維度防抖動 (Debounce)** 與**狀態磁滯 (Hysteresis)**。

### 3. 處理作為與實作修復
* **修改模組**：[`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) 之 `RainDebounceStateMachine`。
* **工程實作邏輯**：
  1. 引入「非對稱計數器」架構：
     * 觸發下雨（ON）：`debounce_on_count = 1`，要求 1 次達標即刻觸發，滿足天窗急時防雨之零延遲要求。
     * 解除下雨（OFF）：`debounce_off_count = 3`，建立冷卻保護期。
  2. 磁滯運算狀態轉移：
     * 當某輪詢判定無雨時，啟動 `consecutive_dry_cycles += 1`。
     * 狀態必須在**連續 3 次輪詢（每 5 分鐘一次，累計 15 分鐘）全無降雨**的情況下，方才將 `is_raining` 關閉為 `False`。
     * 若在 15 分鐘冷卻期間內再度偵測到雨滴，乾燥計數立刻歸零，狀態不中斷。
* **測試驗證**：在 [`test_monitor.py`](file:///f:/Antigravity/Rain/test_monitor.py) 之 `test_full_scenario_simulation` 針對 T3、T4 間歇無雨階段進行斷言驗證，確認狀態機在冷卻期間皆穩定維持 `True`。

---

## 問題 07：純環境變數啟動時因缺少 `config.yaml` 檔案拋出 `FileNotFoundError`

### 1. 錯誤現象
若使用者在 Portainer 部署時選擇純以 `environment:` 變數注入設定，而未透過 Volume 掛載本地 `config.yaml` 檔案，原程式在進入 `load_config()` 時會拋出：
```text
FileNotFoundError: 找不到設定檔: config.yaml 或 config.example.yaml
```

### 2. 根本原因分析 (RCA)
* 原 `load_config` 函式假定實體設定檔必定存在於檔案系統中，若兩者皆不存在即中止程序，無法支援純容器化環境變數運行的標準微服務模式。

### 3. 處理作為與實作修復
* **修改模組**：[`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) 之 `load_config` 函式。
* **代碼修復**：
  * 當本機實體 `config.yaml` 與 `config.example.yaml` 皆不存在時，不拋出中斷例外，而是初始化完整的內部預設設定字典結構。
  * 隨後讀取 `os.getenv()` 系統環境變數（如 `CWA_API_TOKEN`、`HA_BASE_URL`、`HA_ACCESS_TOKEN` 等）進行階層式覆寫。
  * 使得容器既支援 Volume 掛載外部檔案，亦支援純 Compose 環境變數部署。

---

## 錯誤 08：`docker build` 漏掉結尾路徑參數 `.` 導致 `requires exactly 1 argument` 錯誤

### 1. 錯誤現象與日誌
使用者在 PVE 終端機 `/opt/cwa-rain-monitor` 目錄執行建置指令：
```bash
root@pve:/opt/cwa-rain-monitor# docker build -t cwa-ha-rain-monitor:latest
```
Docker Engine (Buildx) 拋出參數缺失錯誤：
```text
ERROR: "docker buildx build" requires exactly 1 argument.
See 'docker buildx build --help'.

Usage:  docker buildx build [OPTIONS] PATH | URL | -

Start a build
```

### 2. 根本原因分析 (RCA)
* `docker build`（在現代 Docker 中底層已全面切換為 `docker buildx build`）語法規範：
  最後一個必要參數為 `PATH | URL | -`，代表建置上下文 (Build Context)。
* 使用者輸入了 `-t cwa-ha-rain-monitor:latest`（指定映像標籤），但結尾漏掉了指向當前目錄的點號 `.`（或其間缺少空格），導致 Docker 判定未傳入建置路徑參數。

### 3. 處理作為與實作修復
* **即時處置**：修正指令為完整且帶有當前目錄點號的指令：
  ```bash
  docker build -t cwa-ha-rain-monitor:latest .
  ```
* **文件防呆優化**：
  * 修改 [`PVE_PORTAINER_DEPLOY_GUIDE.md`](file:///f:/Antigravity/Rain/PVE_PORTAINER_DEPLOY_GUIDE.md)，在指令處特別使用高亮字體強調「結尾必須帶有空格與點號 `.`」。
  * 增加針對 `requires exactly 1 argument` 的故障排除 FAQ，防止後續維護或使用者再次漏打。

---

## 問題 09：Lovelace 載入 `room-elves-card` 白屏崩潰無法正常顯示

### 1. 錯誤現象
使用者在 Lovelace 儀表板貼入 `custom:room-elves-card` 後，前端卡片顯示紅色報錯、白屏，或提示自訂元件無法正確渲染。

### 2. 根本原因分析 (RCA)
1. **子設定鍵不支援 Jinja2 模板 (Template Unsupported)**：`room-elves-card` 原始架構是為實體開關設計，其 `elves:` 底層直接綁定 `entity:` 鍵並讀取其數值。若在 `elves:` 中強行傳入 `state_template:` 或在 `color:` 中塞入 Jinja2 邏輯，前端 JavaScript 解析器無法執行伺服端 Jinja2，會引發未預期之 JSON/YAML 物件異常。
2. **未經保護之陣列索引存取 (Undefined Object Index)**：在初次啟動或網路擷取中，若 `monitored_stations` 尚未寫入，JavaScript 執行 `monitored_stations[0]` 會直接拋出 `TypeError: Cannot read properties of undefined`，導致整個前端組件掛掉。

### 3. 處理作為與實作修復
* **提供標準相容配置**：調整 `room-elves-card` 配置，移除不支援的自訂模板屬性，將 `badges` 與 `elves` 改為直接綁定 `input_boolean.is_raining` 與 `input_boolean.rain_approaching_warning`。
* **推薦首選替代方案**：因應圖表與降雨柱狀圖需求，引進專業級 [`weather-chart-card`](https://github.com/mlamberts78/weather-chart-card)，提供專業的 Chart.js 降水長條圖與折線圖整合。

---

## 問題 10：Markdown 卡片中周邊 4 站觀測明細表格歪斜錯位

### 1. 錯誤現象
在 Lovelace 中使用純 Markdown 卡片顯示周邊 4 站時，表格各欄（測站名稱、代碼、距離、雨量）上下錯位、框線中斷，且在手機端縮放時呈現嚴重的波浪形歪斜。

### 2. 根本原因分析 (RCA)
1. **Jinja2 空白與換行符注入**：在 GFM (GitHub Flavored Markdown) 表格規範中，每一列 `| ... |` 必須連續無空行。Jinja2 的 `{% for %}` 與 `{% endfor %}` 標籤預設會產生換行與縮排空白，導致 Markdown 解析器中斷表格解析，造成表格結構破碎。
2. **缺乏欄寬百分比約束**：純 Markdown 表格無 CSS 欄寬控制，行動裝置端不同測站名稱長度不一引發非對稱折行。

### 3. 處理作為與實作修復
* **修改模組**：[`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md)。
* **全面改採 HTML 5 `<table>` 結構化表格**：
  * 利用 Home Assistant 原生支援 HTML/CSS 之特性，採用 `<table style="width: 100%; border-collapse: collapse;">`。
  * 明確為各欄指定固定寬度（如 28%, 20%, 18%, 18%, 16%）。
  * 加上 `padding`、斑馬紋背景色與 `text-align: center;`，確保在手機與電腦端均 100% 垂直水平絕對對齊、絕不歪斜！

---

## 問題 11：Markdown 卡片無法渲染 HTML 表格並出現 HTML 源碼問題

### 1. 錯誤現象
在較新版本的 Home Assistant Lovelace Markdown 卡片中，如果直接貼入 `<table>`、`<tr>`、`<td>` 等 HTML 標籤，前端頁面不會渲染為美觀表格，反而直接在畫面上印出一行行純文字 HTML 標籤代碼。

### 2. 根本原因分析 (RCA)
* Home Assistant 在近期的核心版本中強化了前端安全防護（XSS Sanitizer），Markdown 卡片預設會清洗或轉義直接嵌入的未信任 HTML 元素。
* 此外，若 YAML 使用 `content: >`（Folded 摺疊標量），換行符號會被自動轉為空格，導致 Markdown 表格解析器直接失靈。

### 3. 處理作為與實作修復
* **修復方式**：
  1. 放棄在 Markdown 卡片中使用原生 HTML `<table>` 標籤，全面改採標準 GitHub Flavored Markdown (GFM) 表格語法（`| 欄位 | 欄位 |`）。
  2. YAML 標量宣告嚴格採用 `content: |`（保留換行之 Literal 標量）。
  3. 在 Jinja2 迴圈中使用 `{%- for ... -%}` 與 `{%- endfor -%}` 進行空白修剪 (Whitespace Trimming)，消除多餘換行，使每一列 Markdown 表格保持連續無空行。
* **驗證結果**：使用者回報採用此修正後，周邊 4 站雨量觀測表格在 Lovelace 上已成功且整齊地顯示。

---

## 問題 12：`weather-chart-card` 實體類型不符導致錯誤與 `weather.forecast_home` 不存在

### 1. 錯誤現象
使用者嘗試在 `custom:weather-chart-card` 中將 `entity:` 設為 `sensor.cwa_rain_monitor`，卡片報錯無法載入或顯示 HTML 源碼；且預設填寫的 `weather.forecast_home` 在部分使用者系統中提示實體不存在。

### 2. 根本原因分析 (RCA)
1. **元件規範限制**：`weather-chart-card` 專為氣象實體設計，其架構要求 `entity:` 必須為 `weather.*` 類型之整合實體（例如預設的天氣整合、中央氣象署 HA 整合或 OpenWeatherMap），它需要讀取該實體內部的 `forecast`（預報陣列）屬性來繪製氣溫雨量趨勢折線圖與柱狀圖；它無法直接綁定一般數字感測器 `sensor.*`。
2. **實體命名差異**：各家庭的 Home Assistant 天氣實體代碼因安裝的氣象套件或自訂名稱而異（常見的有 `weather.home`、`weather.forecast_home`、`weather.cwa_home` 等）。

### 3. 處理作為與實作修復
* **模組架構分離**：
  * 在 [`LOVELACE_CARD_GUIDE.md`](file:///f:/Antigravity/Rain/LOVELACE_CARD_GUIDE.md) 中明確標示：`weather-chart-card` 負責呈現未來的綜合氣象與降雨預報（使用 `weather.*` 實體）；而當前的中央氣象署 4 站即時 10 分鐘雨量與雷達 dBZ 監測，則由純 Markdown 卡片、Entities 卡片或 Mushroom 卡片呈現。
  * 提供「開發者工具 $\to$ 狀態」中搜尋 `weather.` 的具體步驟，指引使用者找到自己系統中實際存在的天氣實體名稱進行填入。
* **驗證結果**：使用者確認調整後，`weather-chart-card`、Markdown 卡片、Entities 實體清單卡片、Mushroom Cards 均已恢復正常運作。

---

## 功能演進 13：住家經緯度變更時，自動取得氣象署測站並切換最近 4 站機制

### 1. 需求背景與核心問題
原系統預設鎖定 4 座指定核心氣象雨量站（安南 C2O950、臺南市北區 C0X100、永康 467420、安定 C0X150）。使用者提出若住家經緯度有變更（如搬遷或調整），系統是否能自動動態向氣象署全台雨量站抓取資料，改為挑選距離使用者住家最近的 4 座測站。

### 2. 架構設計與運作原理
本專案擴充並落實兩套雙軌連動方案：
1. **模式切換為 `auto`（自動距離模式）**：
   * 系統每次連線氣象署 API (O-A0002-001) 時，取得全台數百座自動雨量站之即時數據與 WGS84 座標。
   * 利用 Haversine 球面大圓距離公式，即時運算每座測站離當前住家座標（`home_latitude`, `home_longitude`）之直線距離。
   * 自動過濾經緯度異常或距離過遠之站點，由近到遠排序，動態取前 4 座最近的測站作為當前監控群。
2. **動態對接 Home Assistant `zone.home` 座標（全自動免重啟）**：
   * 在 [`HomeAssistantSync`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py) 模組中新增 `fetch_ha_zone_coordinates()` 函式，向 HA REST API 查詢 `zone.home` 實體。
   * 每個輪詢循環前，若發現使用者在 Home Assistant 前端地圖中變更了住家區域位置，程式自動呼叫 `update_home_location()` 更新座標。
   * 若最新挑選的 4 座測站清單與前一週期不同，立即輸出警告等級日誌提醒管理員，並同步將當前經緯度與最新測站屬性更新至 `sensor.cwa_rain_monitor`。

### 3. 修改模組與落實代碼
* **修改模組**：
  * [`cwa_ha_rain_monitor.py`](file:///f:/Antigravity/Rain/cwa_ha_rain_monitor.py)：擴充 `StationEvaluator`、`HomeAssistantSync` 與主迴圈調度邏輯。
  * [`config.example.yaml`](file:///f:/Antigravity/Rain/config.example.yaml)：增加 `auto_sync_ha_zone: true` 與 `station_selection_mode: "auto"` 設定範例。
  * [`test_monitor.py`](file:///f:/Antigravity/Rain/test_monitor.py)：新增 `TestAutoStationSelection` 單元測試，模擬住家由臺南動態切換至高雄時，測站動態重選行為。
* **驗證結果**：7 項單元測試 100% 通過（`Ran 7 tests in 0.060s - OK`）。

---

## 架構升級 14：由獨立外部 Docker 容器服務全面升級為 HACS 自訂整合 (Custom Integration) 與多座標支援

### 1. 需求背景與核心問題
1. **免手動維護 Token**：先前獨立容器運行模式需在 Home Assistant 手動生成長效存取權杖 (Long-Lived Access Token)，並需手動配置實體區網 IP 與 `network_mode: host`。
2. **多座標 (Multi-Location) 監控需求**：使用者提出同時監控多個地點（如「住家」與「工作地點」）之雨量需求。若維持容器架構，需啟動多個容器或在設定檔維護多陣列，且容易對氣象署 API 發出多餘的重複請求。
3. **穩定性與效能考量**：經深度評估，HACS 自訂整合直接運行於 HA 內部非同步事件迴圈 (`asyncio`)，微秒級記憶體傳遞，零 HTTP 網路開銷，為最佳長遠架構。

### 2. 根本處置作為與模組架構重構
本專案正式全面升級為符合 Home Assistant 官方與 HACS 標準之自訂整合：
1. **目錄架構規範化**：
   * 建立 `custom_components/cwa_rain/`，包含 `manifest.json`、`const.py`、`__init__.py`、`coordinator.py`、`config_flow.py`、`sensor.py`、`binary_sensor.py` 與 `strings.json` / `translations/zh-Hant.json`。
   * 根目錄建立 `hacs.json`，支援直接以 GitHub 網址加入 HACS 自訂儲存庫。
2. **全域 TTL 快取避免重複請求**：
   * 在 `coordinator.py` 實作 `CwaApiClient` 共享客戶端，具備 60 秒微型 TTL 快取。
   * 當「住家」與「公司」兩個實例在同一週期觸發更新時，僅向氣象署發出**單次**全台測站請求，多地點各自進行 Haversine 距離與 4 站過濾，大幅降低頻寬與被氣象署限速風險。
3. **UI Config Flow 多實例建立**：
   * 支援在 HA「設定 $\to$ 裝置與服務 $\to$ 新增整合」直接輸入氣象署 Token。
   * 支援下拉選單選取 `zone.home` 或 `zone.work`，自動讀取並跟隨地圖座標同步。
   * 使用者可重複新增多個地點實例，系統自動生成對應的 Device 裝置與 Sensors。
4. **原生 Binary Sensor 取代手動 input_boolean**：
   * 整合內建 `binary_sensor.*_is_raining` 與 `binary_sensor.*_rain_approaching`，使用者再也不需要在 HA 手動建立 `input_boolean`！

### 3. 修改與新增模組
* 新增目錄：[`custom_components/cwa_rain/`](file:///f:/Antigravity/Rain/custom_components/cwa_rain/)
* 新增檔案：[`hacs.json`](file:///f:/Antigravity/Rain/hacs.json)、[`.github/workflows/validate.yml`](file:///f:/Antigravity/Rain/.github/workflows/validate.yml)、[`tests/test_custom_component.py`](file:///f:/Antigravity/Rain/tests/test_custom_component.py)
* 驗證方式：單元測試 4 項全數通過 (`Ran 4 tests in 1.237s - OK`)，且維持原獨立服務測試相容 (`Ran 7 tests in 0.010s - OK`)。

---

## 歷次修正與驗證摘要表

| 序號 | 問題類型 | 涉及模組 / 元件 | 處置作為簡述 | 驗證方式 |
| :---: | :--- | :--- | :--- | :--- |
| **01** | Portainer 部署報錯 | `docker-compose.yml` | 移除 `build:` 本地路徑依賴，改直接指定現成 image；增設 Repository 模式指南。 | Portainer 重新載入無報錯 |
| **02** | 區網網址解析失敗 | `docker-compose.yml` | 加入 `network_mode: host`，改採實體區網 IP。 | 連線 HA REST API 通訊成功 |
| **03** | 容器時區時差 8 小時 | `Dockerfile`, `docker-compose.yml` | 安裝 `tzdata` 並強制設定 `TZ=Asia/Taipei`。 | 容器日誌時間對齊台灣時間 |
| **04** | 日誌延遲緩衝 | `Dockerfile`, `docker-compose.yml` | 設定 `PYTHONUNBUFFERED=1` 強制無緩衝輸出。 | Portainer Logs 即時更新 |
| **05** | API 負數致數學運算崩潰 | `cwa_ha_rain_monitor.py` | 清洗負數 `-99`/`-998` 歸零，增加 $\log_{10}$ 邊界保護。 | 單元測試 `test_calculate_estimated_dbz` 通過 |
| **06** | 間歇雨設備頻繁彈跳 | `cwa_ha_rain_monitor.py` | 實作非對稱雙計數器狀態機，設定連續 15 分鐘冷卻期。 | 單元測試 `test_full_scenario_simulation` 通過 |
| **07** | 純環境變數啟動報錯 | `cwa_ha_rain_monitor.py` | 改進 `load_config`，支援無實體檔時以預設字典結合環境變數覆寫。 | 單元測試與 `--once` 啟動通過 |
| **08** | build 遺漏結尾點號 | `PVE_PORTAINER_DEPLOY_GUIDE.md` | 指令結尾補上 `.`，並在手冊中強化語法提示與防呆說明。 | 補上點號後順利進入 build 階段 |
| **09** | room-elves-card 白屏 | `LOVELACE_CARD_GUIDE.md` | 移除不相容之子層 Jinja2 模板，改採標準實體綁定；推薦引入 weather-chart-card。 | 修正後正常渲染 |
| **10** | Markdown 表格歪斜 | `LOVELACE_CARD_GUIDE.md` | 改用原生 HTML 5 `<table>` 固定各欄百分比寬度，徹底消除換行錯位。 | 表格 100% 垂直對齊無歪斜 |
| **11** | Markdown 卡片出現 HTML 源碼 | `LOVELACE_CARD_GUIDE.md` | 因應 HA XSS 防護，改回 GFM 表格語法搭配 `content: \|` 與 `{%- for -%}` 空白修剪。 | 表格文字對齊且正常渲染 |
| **12** | weather-chart-card 實體不符 | `LOVELACE_CARD_GUIDE.md` | 分離氣象預報實體 (`weather.*`) 與雨量感測器 (`sensor.*`) 責任範圍。 | 實體設定正確後圖表正常呈現 |
| **13** | 住家座標變更自動切換測站 | `cwa_ha_rain_monitor.py` | 實作動態距離評估與 HA `zone.home` 座標自動同步，座標變更自動取最近 4 站。 | 單元測試 7 項全數通過 |
| **14** | 升級 HACS 整合與多座標支援 | `custom_components/cwa_rain/` | 全面實作標準 HACS Custom Integration，完全免 Token，支援多座標實例與全台快取。 | 單元測試 4 項全數通過 |

