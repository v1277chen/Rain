# Home Assistant 氣象署雨量聯動自動化與 Node-RED 實戰指南

本指南專為 **中央氣象署雨量監控與預警 (CWA Rain Monitor)** 整合設計。
涵蓋 **Home Assistant 原生自動化 (YAML)** 與 **Node-RED 視覺化流程** 兩大主流自動化工具，提供可直接複製貼上使用的生產級設定與流程 JSON，協助您打造「無雨通風、有雨關窗、雨雲接近語音示警」的全自動化智慧居家。

---

## 目錄
- [一、核心實體與觸發訊號一覽](#一核心實體與觸發訊號一覽)
- [二、Home Assistant 原生自動化範例 (YAML)](#二home-assistant-原生自動化範例-yaml)
  - [範例 1：驟雨緊急防護（立即關閉電動氣窗與伸縮雨遮）](#範例-1驟雨緊急防護立即關閉電動氣窗與伸縮雨遮)
  - [範例 2：雨雲接近預警（智慧音箱 TTS 語音提醒收衣物）](#範例-2雨雲接近預警智慧音箱-tts-語音提醒收衣物)
  - [範例 3：停雨安全復原（滿 15 分鐘冷卻期自動重新開啟氣窗通風）](#範例-3停雨安全復原滿-15-分鐘冷卻期自動重新開啟氣窗通風)
  - [範例 4：多地點應用：下班時段公司降雨提醒帶傘](#範例-4多地點應用下班時段公司降雨提醒帶傘)
- [三、Node-RED 視覺化自動化流程 (Flow)](#三node-red-視覺化自動化流程-flow)
  - [架構流程圖 (Mermaid)](#架構流程圖-mermaid)
  - [完整可匯入之 Node-RED Flow JSON](#完整可匯入之-node-red-flow-json)
  - [節點功能解析與自訂參數替換指南](#節點功能解析與自訂參數替換指南)
- [四、在推播與卡片中調用氣象署 CWA.png 圖示](#四在推播與卡片中調用氣象署-cwapng-圖示)

---

## 一、核心實體與觸發訊號一覽

本整合已自動對齊 Docker 經典簡潔命名架構，提供以下實體以供自動化作為觸發條件 (Triggers) 或條件判斷 (Conditions)：

| 實體代碼 (Entity ID) | 類型 | 狀態值 | 自動化應用場景 |
| :--- | :--- | :--- | :--- |
| **`binary_sensor.is_raining`**<br>*(或相容 `input_boolean.is_raining`)* | 二元開關 | `on` / `off` | **即時降雨開關**（多站投票或單站驟雨成立）。內建 15 分鐘防抖動冷卻，作為**關窗、關閉雨遮**的核心觸發。 |
| **`binary_sensor.rain_approaching_warning`**<br>*(或相容 `input_boolean.rain_approaching_warning`)* | 二元開關 | `on` / `off` | **雨雲接近警戒開關**（周邊任一站測得微雨）。作為**語音廣播、提醒收衣物與攜帶傘具**的預警觸發。 |
| **`sensor.cwa_rain_monitor`** | 數值感測器 | 數值 (mm) | **雨量主實體**。數值為過去 10 分鐘最大累積雨量，其屬性中包含：<br>• `estimated_dbz`（推估雷達迴波強度 dBZ）<br>• `active_stations_count`（有雨測站數 0~4）<br>• `monitored_stations`（4 座測站即時明細） |
| **多地點實體**（如公司） | 二元 / 數值 | 對齊上述 | 包含 `binary_sensor.is_raining_gong_si` 與 `sensor.cwa_rain_monitor_gong_si`。 |

---

## 二、Home Assistant 原生自動化範例 (YAML)

以下範例可直接新增至 Home Assistant 的 `automations.yaml`，或於 HA 介面（**「設定」 $\to$ 「自動化與場景」 $\to$ 「建立自動化」 $\to$ 右上角三點選單「以 YAML 編輯」**）直接貼上。

### 範例 1：驟雨緊急防護（立即關閉電動氣窗與伸縮雨遮）

* **業務邏輯**：當偵測到正在下雨時（`binary_sensor.is_raining` 轉為 `on`），即刻關閉陽台窗戶與雨遮，並發送附帶雷達迴波強度與圖示的高優先級推播通知至手機。

```yaml
alias: "氣象署雨量聯動 - 正在下雨緊急關閉氣窗與雨遮"
description: "當中央氣象署判定周邊達到降雨門檻時，即刻關閉陽台窗戶並發送推播通知。"
trigger:
  # 觸發條件：下雨二元感測器由 off 轉為 on
  - platform: state
    entity_id: binary_sensor.is_raining
    from: "off"
    to: "on"
condition: []
action:
  # 動作 1：關閉陽台窗戶與遮陽棚 (請替換為您家中的實體代碼)
  - service: cover.close_cover
    target:
      entity_id:
        - cover.balcony_window
        - cover.patio_awning
  
  # 動作 2：發送行動裝置緊急推播通知
  - service: notify.notify
    data:
      title: "🌧️ 降雨警戒觸發 - 陽台窗戶已自動關閉"
      message: >-
        氣象署測得住家周邊測站雨量達到 {{ states('sensor.cwa_rain_monitor') }} mm，
        推估雷達迴波強度約 {{ state_attr('sensor.cwa_rain_monitor', 'estimated_dbz') }} dBZ。
        系統已為您自動關閉陽台窗戶與遮陽棚。
      data:
        # iOS / Android 推播附帶官方 CWA 圖示
        image: "/cwa_rain_static/CWA.png"
        push:
          sound: "critical"
          interruption-level: "time-sensitive"
mode: single
```

---

### 範例 2：雨雲接近預警（智慧音箱 TTS 語音提醒收衣物）

* **業務邏輯**：當雨雲接近預警觸發，但**目前住家尚未下雨**（`binary_sensor.is_raining == 'off'`），且時段在白天（07:30 ~ 21:30）時，透過客廳智慧音箱播放語音提醒家人收取衣物並備傘。

```yaml
alias: "氣象署雨量聯動 - 雨雲接近智慧音箱廣播提醒"
description: "當周邊測站偵測到微雨但住家未雨時，播放 TTS 語音提醒收衣物。"
trigger:
  # 觸發條件：雨雲接近二元感測器轉為 on
  - platform: state
    entity_id: binary_sensor.rain_approaching_warning
    from: "off"
    to: "on"
condition:
  # 條件 1：住家尚未真正下雨 (避免重複擾民)
  - condition: state
    entity_id: binary_sensor.is_raining
    state: "off"
  # 條件 2：限定日間時段，夜間不發出語音打擾睡眠
  - condition: time
    after: "07:30:00"
    before: "21:30:00"
action:
  # 動作 1：透過 Google Cast / HomePod / 小愛音箱播放語音 (TTS)
  - service: tts.speak
    target:
      entity_id: media_player.living_room_speaker
    data:
      media_player_entity_id: media_player.living_room_speaker
      message: >-
        氣象署通知：雷達偵測到降水雲系接近中，周邊測站已有降雨，請留意陽台衣物並攜帶雨具出門。
      cache: true
  
  # 動作 2：手機一般文字推播
  - service: notify.notify
    data:
      title: "⛅ 雨雲接近預警"
      message: "周邊測站已有微雨，降水雲系正在逼近住家，請記得收取陽台晾曬衣物。"
mode: single
```

---

### 範例 3：停雨安全復原（滿 15 分鐘冷卻期自動重新開啟氣窗通風）

* **業務邏輯**：利用整合內建的磁滯冷卻機制（連續 3 次輪詢無雨，滿 15 分鐘），當 `binary_sensor.is_raining` 轉回 `off` 時，代表雨勢已徹底停歇，安全重新開啟氣窗恢復通風。

```yaml
alias: "氣象署雨量聯動 - 停雨後自動重新開啟氣窗恢復通風"
description: "歷經連續 15 分鐘無雨確認停雨後，自動開啟氣窗通風。"
trigger:
  # 觸發條件：下雨狀態由 on 轉為 off (整合內部已完成 15 分鐘防抖動判定)
  - platform: state
    entity_id: binary_sensor.is_raining
    from: "on"
    to: "off"
condition:
  # 條件：確認空氣品質良好 (選用，例如 AQI < 50 或 PM2.5 良好)
  - condition: numeric_state
    entity_id: sensor.air_purifier_pm25
    below: 35
action:
  # 動作 1：重新開啟陽台通風氣窗
  - service: cover.open_cover
    target:
      entity_id: cover.balcony_window
  
  # 動作 2：推播復原通知
  - service: notify.notify
    data:
      title: "☀️ 雨勢已停歇 - 恢復通風"
      message: "周邊測站已連續 15 分鐘無降雨，系統已為您重新開啟陽台氣窗保持空氣流通。"
mode: single
```

---

### 範例 4：多地點應用：下班時段公司降雨提醒帶傘

* **業務邏輯**：工作日下午接近下班時間（17:00 ~ 18:30），若使用者人位於「公司」區域，且公司實體 `binary_sensor.is_raining_gong_si` 正在下雨或雨雲接近，發送下班提醒帶傘通知。

```yaml
alias: "氣象署雨量聯動 - 公司下雨下班提醒帶傘"
description: "接近下班時間若公司周邊有降雨，主動提醒準備雨具。"
trigger:
  # 觸發條件 1：接近下班時段固定每 15 分鐘檢查
  - platform: time_pattern
    minutes: "/15"
  # 觸發條件 2：公司降雨感測器變為 on
  - platform: state
    entity_id: binary_sensor.is_raining_gong_si
    to: "on"
condition:
  # 條件 1：平日星期一至五的下班時段
  - condition: time
    after: "17:00:00"
    before: "19:00:00"
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
  # 條件 2：手機位置目前處於公司區域 (Zone)
  - condition: zone
    entity_id: person.user
    zone: zone.work
  # 條件 3：公司目前正在下雨或雨雲接近
  - condition: or
    conditions:
      - condition: state
        entity_id: binary_sensor.is_raining_gong_si
        state: "on"
      - condition: state
        entity_id: binary_sensor.rain_approaching_warning_gong_si
        state: "on"
action:
  - service: notify.mobile_app_user_phone
    data:
      title: "☔ 下班降雨提醒 (公司)"
      message: >-
        目前公司周邊測站正處於降雨狀態 (雨量: {{ states('sensor.cwa_rain_monitor_gong_si') }} mm)，
        預計下班路途有雨，請記得攜帶雨具出發！
      data:
        image: "/cwa_rain_static/CWA.png"
mode: single
```

---

## 三、Node-RED 視覺化自動化流程 (Flow)

對於偏好視覺化工作流與需要進行複雜訊息排隊、防抖、分級警示的使用者，推薦使用 Node-RED 進行管理。

### 架構流程圖 (Mermaid)

```mermaid
flowchart TD
    subgraph S1["事件監聽層 (Home Assistant Event)"]
        T1["監聽 binary_sensor.is_raining 狀態變更"]
        T2["監聽 binary_sensor.rain_approaching_warning 狀態變更"]
    end

    subgraph S2["判斷與數據提取 (Logic & Extraction)"]
        SW1{"判斷是 開(on) 還是 關(off)？"}
        C1["讀取 sensor.cwa_rain_monitor 最新屬性\n(取得 estimated_dbz 與 4 站明細)"]
        FN1["Function 節點：\n依據 dBZ 分級並格式化通知文字"]
    end

    subgraph S3["設備聯動與通知執行 (Actions)"]
        A1["呼叫 cover.close_cover (關閉氣窗/雨遮)"]
        A2["呼叫 tts.speak (客廳音箱語音廣播)"]
        A3["呼叫 notify (發送附帶 CWA 圖示之手機推播)"]
        A4["呼叫 cover.open_cover (停雨滿15分重新開窗)"]
    end

    T1 --> SW1
    T2 -->|雨雲接近 (on)| C1

    SW1 -->|狀態 = on (正在下雨)| A1
    SW1 -->|狀態 = on (正在下雨)| C1
    SW1 -->|狀態 = off (確認停雨)| A4

    C1 --> FN1
    FN1 --> A2
    FN1 --> A3
```

---

### 完整可匯入之 Node-RED Flow JSON

在 Node-RED 介面中，點擊右上角漢堡選單 $\to$ **Import** $\to$ 將下方完整 JSON 貼入，點擊 **Import** 即可一鍵生成：

```json
[
  {
    "id": "cwa_tab_rain_monitor",
    "type": "tab",
    "label": "氣象署雨量聯動監控",
    "disabled": false,
    "info": "中央氣象署雨量監控與預警 (CWA Rain Monitor) 專用自動化流程"
  },
  {
    "id": "node_is_raining_event",
    "type": "server-state-changed",
    "z": "cwa_tab_rain_monitor",
    "name": "正在下雨狀態變更 (is_raining)",
    "server": "",
    "version": 5,
    "outputs": 2,
    "exposeAsEntityConfig": "",
    "entityId": "binary_sensor.is_raining",
    "entityIdType": "exact",
    "outputInitially": false,
    "stateType": "str",
    "ifState": "on",
    "ifStateType": "str",
    "ifStateOperator": "is",
    "outputOnlyOnStateChange": true,
    "for": "0",
    "forType": "num",
    "forUnits": "minutes",
    "ignorePrevStateNull": false,
    "ignorePrevStateUnknown": false,
    "ignorePrevStateUnavailable": false,
    "ignoreCurrentStateUnknown": false,
    "ignoreCurrentStateUnavailable": false,
    "outputProperties": [
      {
        "property": "payload",
        "propertyType": "msg",
        "value": "",
        "valueType": "entityState"
      },
      {
        "property": "data",
        "propertyType": "msg",
        "value": "",
        "valueType": "eventData"
      }
    ],
    "x": 190,
    "y": 140,
    "wires": [
      ["node_close_cover", "node_get_rain_sensor_data"],
      ["node_open_cover"]
    ]
  },
  {
    "id": "node_rain_approaching_event",
    "type": "server-state-changed",
    "z": "cwa_tab_rain_monitor",
    "name": "雨雲接近警報 (rain_approaching)",
    "server": "",
    "version": 5,
    "outputs": 1,
    "exposeAsEntityConfig": "",
    "entityId": "binary_sensor.rain_approaching_warning",
    "entityIdType": "exact",
    "outputInitially": false,
    "stateType": "str",
    "ifState": "on",
    "ifStateType": "str",
    "ifStateOperator": "is",
    "outputOnlyOnStateChange": true,
    "for": "0",
    "forType": "num",
    "forUnits": "minutes",
    "ignorePrevStateNull": false,
    "ignorePrevStateUnknown": false,
    "ignorePrevStateUnavailable": false,
    "ignoreCurrentStateUnknown": false,
    "ignoreCurrentStateUnavailable": false,
    "outputProperties": [
      {
        "property": "payload",
        "propertyType": "msg",
        "value": "",
        "valueType": "entityState"
      }
    ],
    "x": 200,
    "y": 240,
    "wires": [["node_check_if_already_raining"]]
  },
  {
    "id": "node_close_cover",
    "type": "api-call-service",
    "z": "cwa_tab_rain_monitor",
    "name": "執行關閉陽台窗戶與雨遮",
    "server": "",
    "version": 5,
    "debugenabled": false,
    "domain": "cover",
    "service": "close_cover",
    "areaId": [],
    "deviceId": [],
    "entityId": ["cover.balcony_window"],
    "data": "",
    "dataType": "jsonata",
    "mergeContext": "",
    "mustacheTags": false,
    "outputProperties": [],
    "queue": "none",
    "x": 550,
    "y": 100,
    "wires": [[]]
  },
  {
    "id": "node_open_cover",
    "type": "api-call-service",
    "z": "cwa_tab_rain_monitor",
    "name": "停雨滿15分重新開窗通風",
    "server": "",
    "version": 5,
    "debugenabled": false,
    "domain": "cover",
    "service": "open_cover",
    "areaId": [],
    "deviceId": [],
    "entityId": ["cover.balcony_window"],
    "data": "",
    "dataType": "jsonata",
    "mergeContext": "",
    "mustacheTags": false,
    "outputProperties": [],
    "queue": "none",
    "x": 550,
    "y": 180,
    "wires": [["node_notify_rain_stopped"]]
  },
  {
    "id": "node_check_if_already_raining",
    "type": "api-current-state",
    "z": "cwa_tab_rain_monitor",
    "name": "確認當前是否尚未下雨？",
    "server": "",
    "version": 3,
    "outputs": 2,
    "halt_if": "off",
    "halt_if_type": "str",
    "halt_if_compare": "is",
    "entity_id": "binary_sensor.is_raining",
    "state_type": "str",
    "blockInputOverrides": false,
    "outputProperties": [
      {
        "property": "is_raining_state",
        "propertyType": "msg",
        "value": "",
        "valueType": "entityState"
      }
    ],
    "for": "0",
    "forType": "num",
    "forUnits": "minutes",
    "override_topic": false,
    "state_location": "payload",
    "override_payload": "msg",
    "entity_location": "data",
    "override_data": "msg",
    "x": 510,
    "y": 240,
    "wires": [["node_tts_voice_warning"], []]
  },
  {
    "id": "node_tts_voice_warning",
    "type": "api-call-service",
    "z": "cwa_tab_rain_monitor",
    "name": "客廳智慧音箱語音廣播",
    "server": "",
    "version": 5,
    "debugenabled": false,
    "domain": "tts",
    "service": "speak",
    "areaId": [],
    "deviceId": [],
    "entityId": ["media_player.living_room_speaker"],
    "data": "{\"media_player_entity_id\":\"media_player.living_room_speaker\",\"message\":\"氣象署提醒：降雨雲系接近中，周邊測站已有雨滴，請記得收取陽台衣物。\"}",
    "dataType": "json",
    "mergeContext": "",
    "mustacheTags": false,
    "outputProperties": [],
    "queue": "none",
    "x": 810,
    "y": 240,
    "wires": [[]]
  },
  {
    "id": "node_get_rain_sensor_data",
    "type": "api-current-state",
    "z": "cwa_tab_rain_monitor",
    "name": "取得 sensor.cwa_rain_monitor 詳細屬性",
    "server": "",
    "version": 3,
    "outputs": 1,
    "halt_if": "",
    "halt_if_type": "str",
    "halt_if_compare": "is",
    "entity_id": "sensor.cwa_rain_monitor",
    "state_type": "str",
    "blockInputOverrides": false,
    "outputProperties": [
      {
        "property": "rain_data",
        "propertyType": "msg",
        "value": "",
        "valueType": "entity"
      }
    ],
    "for": "0",
    "forType": "num",
    "forUnits": "minutes",
    "override_topic": false,
    "state_location": "payload",
    "override_payload": "msg",
    "entity_location": "data",
    "override_data": "msg",
    "x": 590,
    "y": 60,
    "wires": [["node_format_notification_message"]]
  },
  {
    "id": "node_format_notification_message",
    "type": "function",
    "z": "cwa_tab_rain_monitor",
    "name": "格式化雷達迴波與雨量通知",
    "func": "const rainSensor = msg.rain_data || {};\nconst attrs = rainSensor.attributes || {};\nconst maxRain = rainSensor.state || '0.0';\nconst dbz = attrs.estimated_dbz || 0;\nconst activeCount = attrs.active_stations_count || 0;\n\n// 根據雷達迴波強度給予生動描述\nlet severityText = '常態雨勢';\nif (dbz >= 40) {\n    severityText = '⚠️ 強烈對流驟雨';\n} else if (dbz >= 30) {\n    severityText = '🌧️ 明顯降雨';\n} else if (dbz >= 20) {\n    severityText = '🌦️ 局部微雨';\n}\n\nmsg.payload = {\n    data: {\n        title: `🌧️ 【${severityText}】陽台氣窗已自動關閉`,\n        message: `過去10分鐘最大雨量：${maxRain} mm\\n推估雷達迴波：${dbz} dBZ\\n周邊有雨測站：${activeCount} / 4 站`,\n        data: {\n            image: '/cwa_rain_static/CWA.png',\n            push: {\n                sound: 'critical'\n            }\n        }\n    }\n};\n\nreturn msg;",
    "outputs": 1,
    "timeout": 0,
    "noerr": 0,
    "initialize": "",
    "finalize": "",
    "libs": [],
    "x": 880,
    "y": 60,
    "wires": [["node_send_mobile_push"]]
  },
  {
    "id": "node_send_mobile_push",
    "type": "api-call-service",
    "z": "cwa_tab_rain_monitor",
    "name": "發送手機 App 緊急推播通知",
    "server": "",
    "version": 5,
    "debugenabled": false,
    "domain": "notify",
    "service": "notify",
    "areaId": [],
    "deviceId": [],
    "entityId": [],
    "data": "payload.data",
    "dataType": "jsonata",
    "mergeContext": "",
    "mustacheTags": false,
    "outputProperties": [],
    "queue": "none",
    "x": 1160,
    "y": 60,
    "wires": [[]]
  },
  {
    "id": "node_notify_rain_stopped",
    "type": "api-call-service",
    "z": "cwa_tab_rain_monitor",
    "name": "推播通知已停雨恢復通風",
    "server": "",
    "version": 5,
    "debugenabled": false,
    "domain": "notify",
    "service": "notify",
    "areaId": [],
    "deviceId": [],
    "entityId": [],
    "data": "{\"title\":\"☀️ 雨勢已停歇\",\"message\":\"周邊已連續 15 分鐘無降雨，系統已為您重新開啟陽台氣窗保持通風。\",\"data\":{\"image\":\"/cwa_rain_static/CWA.png\"}}",
    "dataType": "json",
    "mergeContext": "",
    "mustacheTags": false,
    "outputProperties": [],
    "queue": "none",
    "x": 860,
    "y": 180,
    "wires": [[]]
  }
]
```

---

### 節點功能解析與自訂參數替換指南

當您將上方 Flow 匯入 Node-RED 後，請根據自家 Home Assistant 實體進行極簡調整：

1. **實體更換 (Entity Mapping)**：
   * 雙擊 `執行關閉陽台窗戶與雨遮` 節點：將 `cover.balcony_window` 替換為您的窗簾、百葉窗或雨遮實體代碼。
   * 雙擊 `客廳智慧音箱語音廣播` 節點：將 `media_player.living_room_speaker` 替換為您的智慧音箱。
   * 雙擊 `發送手機 App 緊急推播通知` 節點：若您有多支手機，可指定特定的服務如 `notify.mobile_app_your_iphone`。
2. **多地點支援 (Multi-Location)**：
   * 若要監控「公司」，只需將 `node_is_raining_event` 節點中的實體由 `binary_sensor.is_raining` 改為 `binary_sensor.is_raining_gong_si` 即可。
3. **雷達迴波門檻調整**：
   * 在 `格式化雷達迴波與雨量通知` 函式節點內，可依需求自訂 dBZ 級距判斷邏輯（如調整 `dbz >= 40` 為其他數值）。

---

## 四、在推播與卡片中調用氣象署 CWA.png 圖示

本整合自 `v1.0.3` 起，已內建註冊靜態路徑 `/cwa_rain_static/CWA.png`，無需手動建立 `www/` 資料夾即可在全系統呼叫：

### 1. 手機通知訊息附帶氣象署圖示
在自動化的 `notify` 服務中，傳入 `image` 參數：
```yaml
service: notify.notify
data:
  title: "🌧️ 降雨預警"
  message: "氣象署測得周邊已有降雨。"
  data:
    image: "/cwa_rain_static/CWA.png"
```

### 2. 在 Lovelace 卡片上顯示 CWA.png

* **Mushroom 範本卡片 (顯示官方標誌)**：
```yaml
type: custom:mushroom-template-card
primary: 氣象署雨量綜合監控
secondary: >-
  {{ states('sensor.cwa_rain_monitor') }} mm ({{ state_attr('sensor.cwa_rain_monitor', 'estimated_dbz') }} dBZ)
picture: /cwa_rain_static/CWA.png
entity: sensor.cwa_rain_monitor
```

* **原生實體清單卡片 (Entities Card)**：
```yaml
type: entities
title: 降雨監控
entities:
  - entity: sensor.cwa_rain_monitor
    name: 氣象署綜合雨量
    image: /cwa_rain_static/CWA.png
  - entity: binary_sensor.is_raining
  - entity: binary_sensor.rain_approaching_warning
```
