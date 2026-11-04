# ==============================================================================
# 中央氣象署雨量監控服務 Dockerfile
# 基底映像：Python 3.11 Slim (輕量且穩定)
# 檔案名稱：Dockerfile
# ==============================================================================

FROM python:3.11-slim

# 設定維護者與描述標籤
LABEL maintainer="Antigravity"
LABEL description="CWA Rain Monitor Service for Home Assistant via Portainer"

# 1. 設定工作目錄
WORKDIR /app

# 2. 設定環境變數
# PYTHONUNBUFFERED=1：使 Python 即時輸出 stdout/stderr，避免在 Portainer Log 中延遲緩衝
# PYTHONDONTWRITEBYTECODE=1：避免產生 .pyc 垃圾檔
# TZ=Asia/Taipei：強制容器設定為台灣標準時間 (UTC+8)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Taipei

# 3. 安裝系統基本時區工具 (tzdata) 並設定時區
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 4. 複製相依性清單並安裝 Python 函式庫
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 5. 複製主程式與預設範本
COPY cwa_ha_rain_monitor.py /app/
COPY config.example.yaml /app/

# 6. 宣告資料掛載點（可選：用於掛載自訂 config.yaml）
VOLUME ["/app/config"]

# 7. 容器啟動指令
CMD ["python", "cwa_ha_rain_monitor.py"]

