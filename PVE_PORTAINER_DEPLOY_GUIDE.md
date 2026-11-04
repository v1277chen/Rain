# PVE (192.168.0.110) 下 Portainer Stacks 完整部署指南

本文件專為在 **Proxmox VE (PVE，主機 IP: `192.168.0.110`)** 環境中，透過 **Portainer Stacks (Docker Compose)** 部署「中央氣象署雨量監控與 Home Assistant 同步服務」提供最詳盡的實戰操作手冊。

涵蓋**需上傳之檔案清單**、**Windows 至 PVE 的上傳指令**、**`docker build` 建置步驟**、**Portainer Stack 配置**與**同區網 (192.168.0.x) 連線防坑設定**。

---

## 目錄
- [一、需上傳至 PVE 的檔案清單](#一需上傳至-pve-的檔案清單)
- [二、檔案上傳至 PVE 步驟 (SCP / SFTP)](#二檔案上傳至-pve-步驟-scp--sftp)
- [三、在 PVE 終端機執行 docker build](#三在-pve-終端機執行-docker-build)
- [四、在 Portainer Stacks 中一鍵部署](#四在-portainer-stacks-中一鍵部署)
- [五、PVE 專屬架構關鍵防坑注意 (LXC / 虛擬網卡)](#五pve-專屬架構關鍵防坑注意-lxc--虛擬網卡)
- [六、部署後驗證與日誌檢查](#六部署後驗證與日誌檢查)

---

## 一、需上傳至 PVE 的檔案清單

您只需要將專案中的 **5 個核心檔案** 上傳至 PVE 主機（其餘 `.git`、`.github`、網頁、說明文件均不需上傳，確保映像檔最小化）：

| 檔案名稱 | 檔案作用 | 是否必傳 |
| :--- | :--- | :---: |
| **`Dockerfile`** | 容器建置規範檔（定義 Python 3.11 環境、台灣時區 `Asia/Taipei`） | **必傳** |
| **`requirements.txt`** | Python 相依套件清單 (`requests`, `pyyaml`) | **必傳** |
| **`cwa_ha_rain_monitor.py`** | 雨量監控主程式（含 Haversine、防抖動狀態機、dBZ 換算與 HA 同步） | **必傳** |
| **`config.example.yaml`** | 預設測站座標與結構範本（供容器內部 Fallback 備援） | **必傳** |
| **`docker-compose.yml`** | Portainer Stacks 部署設定範本 | **必傳** |

> **不必上傳的檔案**：`index.html`（GitHub Pages 用）、`README.md`、`Walkthrough.md`、`__pycache__` 等暫存檔。

---

## 二、檔案上傳至 PVE 步驟 (SCP / SFTP)

假設您的 PVE 伺服器 IP 為 `192.168.0.110`，預設管理員帳號為 `root`。

### 步驟 1：在 PVE 主機建立目標存放目錄
在 Windows 開啟 PowerShell，透過 SSH 連線進入 PVE：
```powershell
ssh root@192.168.0.110
```
*(輸入 root 密碼後登入)*，建立專案存放目錄：
```bash
# 在 PVE 上建立專用目錄
mkdir -p /opt/cwa-rain-monitor
exit
```

### 步驟 2：從 Windows 將檔案上傳至 PVE
在您的本機電腦（`F:\Antigravity\Rain` 目錄下）開啟 PowerShell，執行以下單行 `scp` 指令將 5 個檔案一次性上傳：

```powershell
cd F:\Antigravity\Rain
scp Dockerfile requirements.txt cwa_ha_rain_monitor.py config.example.yaml docker-compose.yml root@192.168.0.110:/opt/cwa-rain-monitor/
```

> **提示（WinSCP / FileZilla 圖形化操作）**：
> 若您習慣使用圖形介面，可開啟 WinSCP 或 FileZilla：
> * 主機：`192.168.0.110`，連接埠：`22`，使用者：`root`
> * 直接將上述 5 個檔案拖曳至 PVE 的 `/opt/cwa-rain-monitor/` 目錄中。

---

## 三、在 PVE 終端機執行 docker build

檔案上傳完成後，即可直接在 PVE 宿主機（或運行 Docker 的 LXC 容器內部）執行映像檔打包：

### 步驟 1：SSH 進入目錄
```bash
ssh root@192.168.0.110
cd /opt/cwa-rain-monitor
```

### 步驟 2：確認檔案完整性
執行 `ls -la`，確認目錄下包含上述檔案：
```bash
ls -la
# 應看到 Dockerfile, requirements.txt, cwa_ha_rain_monitor.py, config.example.yaml, docker-compose.yml
```

### 步驟 3：執行 Docker Build 打包映像檔
執行以下指令開始打包，映像檔名稱命名為 `cwa-ha-rain-monitor:latest`：

```bash
docker build -t cwa-ha-rain-monitor:latest .
```

> **⚠️ 極重要提醒（注意結尾的點號）**：
> 指令結尾的 **「空格與點號 `.`」絕對不能省略**！
> 點號 `.` 代表當前目錄上下文 (Context)。若漏掉點號，Docker 會報錯：`ERROR: "docker buildx build" requires exactly 1 argument`。

*建置過程會自動：*
1. 下載官方 `python:3.11-slim` 基底映像。
2. 自動安裝系統 `tzdata` 並軟連結設定時區為 `Asia/Taipei`（台灣標準時間 UTC+8）。
3. 自動安裝 `requirements.txt` 中之 `requests` 與 `pyyaml`。
4. 將 Python 程式碼複製至容器 `/app/` 目錄。

### 步驟 4：確認映像檔建置成功
```bash
docker images | grep cwa-ha-rain-monitor
```
*預期輸出：*
```text
REPOSITORY            TAG       IMAGE ID       CREATED          SIZE
cwa-ha-rain-monitor   latest    a1b2c3d4e5f6   10 seconds ago   約 160MB
```
當看到上述輸出，代表本機映像檔已經建置完畢！接下來在 Portainer 即可直接秒級調用，**徹底解決先前的 `open Dockerfile: no such file or directory` 錯誤**！

---

## 四、在 Portainer Stacks 中一鍵部署

### 步驟 1：開啟 Portainer 管理頁面
瀏覽器開啟 Portainer（通常位於 `https://192.168.0.110:9443` 或 `http://192.168.0.110:9000`）。

### 步驟 2：新增 Stack
1. 點擊左側選單 **「Stacks」**。
2. 點擊右上角 **「+ Add stack」**。
3. **Name** 輸入：`cwa-rain-monitor`。
4. **Build method** 保持預設 **Web editor**。

### 步驟 3：貼入 Compose YAML 配置
將以下內容貼入 Web editor（注意替換您的 Token 與 HA 區網 IP）：

```yaml
version: '3.8'

services:
  cwa-rain-monitor:
    container_name: cwa-rain-monitor
    # 【關鍵】直接使用剛才在 PVE build 好的映像檔，不再執行 build，完全不會報錯！
    image: cwa-ha-rain-monitor:latest
    restart: unless-stopped
    
    # 【同區網最佳設定】直接使用 Host 網路，直連 HA 實體 IP (免 NAT 轉發與 DNS 延遲)
    network_mode: host
    
    environment:
      # 系統環境
      - TZ=Asia/Taipei
      - PYTHONUNBUFFERED=1
      
      # 1.【必填】氣象署 API 授權碼 (至 https://opendata.cwa.gov.tw/ 個人頁面取得)
      - CWA_API_TOKEN=YOUR_CWA_API_KEY_HERE
      - CWA_DATASET_ID=O-A0002-001
      
      # 2.【必填】Home Assistant 區域網路位址 (同處 192.168.0.x 網段)
      # 範例：http://192.168.0.120:8123 (請改成您真實的 HA IP)
      - HA_BASE_URL=http://192.168.0.120:8123
      # HA 長效存取權杖 (HA 使用者個人檔案最下方產生)
      - HA_ACCESS_TOKEN=YOUR_HA_LONG_LIVED_ACCESS_TOKEN_HERE
      
      # 3.【選填】住家經緯度 (預設為臺南市安南/北區交界)
      - HOME_LATITUDE=23.0150
      - HOME_LONGITUDE=120.2050
      - STATION_SELECTION_MODE=fixed  # fixed: 鎖定安南、北區、永康、安定 4 站
      
      # 4.【選填】判定門檻與防抖動機制
      - RAIN_DETECTED_MM=0.1          # 單站微雨判定門檻 (mm)
      - HEAVY_RAIN_MM=1.5             # 單站驟雨判定門檻 (mm，任一站達標立即下雨)
      - POLLING_INTERVAL_SECONDS=300  # 輪詢週期 (300 秒 = 5 分鐘)
      - DEBOUNCE_OFF_COUNT=3          # 停雨冷卻連續次數 (連續 3 次無雨 = 15 分鐘冷卻才關閉)
      - DEBOUNCE_ON_COUNT=1           # 降雨觸發連續次數 (1 次滿足立即開啟)

    deploy:
      resources:
        limits:
          cpus: '0.20'
          memory: 128M
```

### 步驟 4：點擊部署
滑至頁面最下方，點擊 **「Deploy the stack」**，容器將於 1 秒內快速啟動完成！

---

## 五、PVE 專屬架構關鍵防坑注意 (LXC / 虛擬網卡)

在 Proxmox VE 架構下運行 Docker，需特別留意以下兩項常見設定：

### 1. 若 Docker 是運行在 PVE 的 LXC 容器中 (特權/巢狀虛擬化)
若您的 Portainer / Docker 是跑在 PVE 開立的 **LXC 容器 (CT)** 中：
* **必備權限設定**：在 PVE Web 介面選中該 LXC $\to$ **Options** $\to$ **Features**：
  * 必須勾選 **`Nesting`**（允許在容器內跑 Docker）。
  * 必須勾選 **`keyctl`**。
* 若是無特權 (Unprivileged) 容器，請確認 Docker 存儲驅動支援（推薦 Overlay2 或在 PVE Options 啟用相應權限）。

### 2. 同區網 IP 連線規範
* PVE IP 為 `192.168.0.110`，若您的 Home Assistant 也在 `192.168.0.x` 網段（例如 `192.168.0.120`）：
  * 由於 `docker-compose.yml` 配置了 `network_mode: host`，容器與 PVE（或 LXC）共享同一個 IP，**不存在跨網段 NAT 阻隔**。
  * `HA_BASE_URL` 請直接填寫實體 IP `http://192.168.0.XXX:8123`，**切勿使用** `http://homeassistant.local:8123`。

---

## 六、部署後驗證與日誌檢查

部署成功後，在 Portainer 進入 **Containers** $\to$ 點選 **`cwa-rain-monitor`** $\to$ **Logs**：

### 正常運作日誌範例：
```text
2026-11-02 17:00:00 [INFO] 正在啟動中央氣象署雨量監控服務...
2026-11-02 17:00:00 [INFO] 已透過環境變數 CWA_API_TOKEN 覆寫氣象署金鑰
2026-11-02 17:00:00 [INFO] 已透過環境變數 HA_BASE_URL 覆寫 HA 網址: http://192.168.0.120:8123
2026-11-02 17:00:00 [INFO] 進入常駐輪詢模式，每隔 300 秒 (5.0 分鐘) 更新一次...
2026-11-02 17:00:01 [INFO] 正在連線氣象署 API (資料集: O-A0002-001) 抓取雨量資料...
2026-11-02 17:00:02 [INFO] 成功抓取氣象署資料，共取得 1142 個測站記錄
2026-11-02 17:00:02 [INFO] 【固定測站模式】已鎖定指定之 4 個測站
2026-11-02 17:00:02 [INFO] === 監控測站降雨即時數據 ===
2026-11-02 17:00:02 [INFO]   [C2O950 安南] 距離家: 1.25 km | 過去10分雨量: 0.00 mm
2026-11-02 17:00:02 [INFO]   [C0X100 臺南市北區] 距離家: 2.14 km | 過去10分雨量: 0.00 mm
2026-11-02 17:00:02 [INFO]   [467420 永康] 距離家: 4.52 km | 過去10分雨量: 0.00 mm
2026-11-02 17:00:02 [INFO]   [C0X150 安定] 距離家: 5.81 km | 過去10分雨量: 0.00 mm
2026-11-02 17:00:02 [INFO] === 判定結論 ===
2026-11-02 17:00:02 [INFO]   最大10分雨量: 0.00 mm | 推估雷達迴波: 0.0 dBZ | 有雨測站數: 0
2026-11-02 17:00:02 [INFO]   【正在下雨 is_raining】: False (連續有雨:0, 連續無雨:1, 離解除還差:0)
2026-11-02 17:00:02 [INFO]   【雨雲接近預警 rain_approaching】: False
2026-11-02 17:00:02 [INFO] 成功同步 HA 實體 [input_boolean.is_raining] -> 狀態: off
2026-11-02 17:00:02 [INFO] 成功同步 HA 實體 [input_boolean.rain_approaching_warning] -> 狀態: off
2026-11-02 17:00:02 [INFO] 成功同步 HA 實體 [sensor.cwa_rain_monitor] -> 狀態: 0.0
2026-11-02 17:00:02 [INFO] 休眠 300 秒後進行下一次輪詢...
```

同時，您可以前往 Home Assistant 的「開發者工具」$\to$「狀態」，搜尋 `sensor.cwa_rain_monitor`，即可看見即時寫入的四站明細與推估雷達迴波數值！

