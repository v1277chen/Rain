# Home Assistant Lovelace 降雨監控儀表板卡片設定手冊 (修正版)

本文件專為 `sensor.cwa_rain_monitor`、`input_boolean.is_raining` 與 `input_boolean.rain_approaching_warning` 設計。
所有配置均使用 **HA 原生 Markdown 語法 + Jinja2 模板**（不使用 HTML 標籤），確保在各版本 Home Assistant 上均能正確渲染。

---

## 目錄
- [一、狀態復原機制說明 (自動 vs 手動)](#一狀態復原機制說明-自動-vs-手動)
- [二、weather-chart-card 正確用法與整合配置](#二weather-chart-card-正確用法與整合配置)
- [三、HA 原生 Markdown 卡片 (表格完美對齊版)](#三ha-原生-markdown-卡片-表格完美對齊版)
- [四、Entities 實體清單卡片 (零依賴最穩定)](#四entities-實體清單卡片-零依賴最穩定)
- [五、Mushroom 卡片配置範例 (需 HACS)](#五mushroom-卡片配置範例-需-hacs)
- [六、常見錯誤與踩坑紀錄](#六常見錯誤與踩坑紀錄)

---

## 一、狀態復原機制說明 (自動 vs 手動)

### 答案：完全自動復原，不需要手動介入！

本專案的核心狀態機（`RainDebounceStateMachine`）已內建**磁滯冷卻計時機制 (Hysteresis Debounce)**：

1. **`input_boolean.is_raining` (正在下雨)**：
   * **自動轉 ON**：當四站中 ≥ 2 站有雨，或單站 ≥ 1.5 mm 時，輪詢當次立即自動設為 `on`。
   * **自動轉 OFF（自動復原）**：當雨勢停歇時，程式會啟動連續無雨計數。**只要連續 3 次輪詢（每 5 分鐘一次，累計 15 分鐘）全部無雨**，程式就會主動呼叫 HA REST API，將該實體**自動切換回 `off`**。
2. **`input_boolean.rain_approaching_warning` (雨雲接近預警)**：
   * **自動轉 ON**：任 1 站有雨或正在下雨時自動為 `on`。
   * **自動轉 OFF（自動復原）**：在下雨狀態解除後，所有測站維持連續 3 次無雨（滿 15 分鐘冷卻期）即**自動切換回 `off`**。
3. **冷卻倒數屬性**：
   在 `sensor.cwa_rain_monitor` 的屬性中帶有 `cooldown_remaining_cycles`，雨停時會倒數 3 → 2 → 1 → 0，歸零時即刻自動復原。

---

## 二、weather-chart-card 正確用法與整合配置

### 重要觀念釐清

[`weather-chart-card`](https://github.com/mlamberts78/weather-chart-card) **只能綁定 `weather.*` 類型的實體**（例如 `weather.openweathermap`、`weather.met_no_home` 等由天氣整合提供的實體）。

我們的 `sensor.cwa_rain_monitor` 是 **sensor 感測器類型**，不是 weather 天氣實體，因此**無法直接放入 `weather-chart-card` 的 `entity:` 欄位**。

### 正確整合方式：上下分層各司其職

上方放 `weather-chart-card` 顯示天氣整合的預報圖表，下方放 Markdown 卡片顯示我們的即時測站雨量數據：

#### 步驟 1：先確認您 HA 中有哪個天氣實體

前往 HA「開發者工具」→「狀態」，篩選 `weather.`，找到您的天氣實體名稱。
常見的天氣實體名稱範例：
* `weather.forecast_home` (HA 預設氣象整合)
* `weather.openweathermap` (OpenWeatherMap 整合)
* `weather.met_no_home` (Met.no 整合)
* `weather.home` (AccuWeather 或其他)

若您尚未安裝任何天氣整合，請至 HA「設定」→「裝置與服務」→「新增整合」→ 搜尋並安裝 **Met.no** 或 **OpenWeatherMap** (免費)。

#### 步驟 2：上下分層整合配置

```yaml
type: vertical-stack
cards:
  # === 上方：weather-chart-card 天氣預報圖表 ===
  # 請將下方的 weather.forecast_home 替換成您在步驟 1 找到的真實天氣實體名稱
  - type: custom:weather-chart-card
    entity: weather.forecast_home
    show_main: true
    show_attributes: true
    show_time: true
    show_temperature: true
    show_precipitation_amounts: true
    show_precipitation_probability: true
    icons_size: 28

  # === 下方：氣象署即時雨量監控 (純 Jinja2，不使用 HTML) ===
  - type: markdown
    content: |
      {% if is_state('input_boolean.is_raining', 'on') %}
      🔴 **目前正在下雨中** (最大雨量: **{{ states('sensor.cwa_rain_monitor') }} mm**)
      {% elif is_state('input_boolean.rain_approaching_warning', 'on') %}
      🟡 **雨雲接近預警** (周邊測站有雨)
      {% else %}
      🟢 **周邊天氣良好 (無降雨)**
      {% endif %}
      推估雷達迴波: **{{ state_attr('sensor.cwa_rain_monitor', 'estimated_dbz') }} dBZ** ┃ 有雨站數: **{{ state_attr('sensor.cwa_rain_monitor', 'active_stations_count') }}/4 站**
      {% set stations = state_attr('sensor.cwa_rain_monitor', 'monitored_stations') %}
      {% if stations %}

      | 測站 | 距離 | 10分雨量 | 狀態 |
      |:---|:---:|:---:|:---:|
      {%- for st in stations %}
      | **{{ st.name }}** ({{ st.id }}) | {{ st.distance_km }} km | {{ st.past_10min_mm }} mm | {{ '🌧️' if st.is_raining else '☀️' }} |
      {%- endfor %}

      {% endif %}
```

---

## 三、HA 原生 Markdown 卡片 (表格完美對齊版)

### 表格歪斜問題的根治修復

Markdown 表格歪斜的根本原因有兩個：
1. **YAML 使用 `>` (folded scalar)**：會把換行折疊成空格，破壞表格結構。改用 `|` (literal scalar) 即可保持換行。
2. **Jinja2 迴圈注入空白行**：在 `{% for %}` 和 `{% endfor %}` 前後使用 `{%- -%}` (加減號) 可以剝除多餘空白。

### 完整配置 (獨立使用，不依賴任何第三方卡片)：

```yaml
type: markdown
title: 🌧️ 中央氣象署雨量綜合觀測
content: |
  {% if is_state('input_boolean.is_raining', 'on') %}
  🔴 **目前正在下雨中** (過去10分最大雨量: **{{ states('sensor.cwa_rain_monitor') }} mm**)
  {% elif is_state('input_boolean.rain_approaching_warning', 'on') %}
  🟡 **雨雲接近預警中** (周邊已有測站偵測到微雨)
  {% else %}
  🟢 **周邊天氣良好 (無降雨)**
  {% endif %}

  **推估雷達迴波**: {{ state_attr('sensor.cwa_rain_monitor', 'estimated_dbz') }} dBZ ┃ **有雨測站**: {{ state_attr('sensor.cwa_rain_monitor', 'active_stations_count') }} / 4 站
  {% if is_state('input_boolean.is_raining', 'on') and state_attr('sensor.cwa_rain_monitor', 'cooldown_remaining_cycles') | int > 0 %}
  ⏳ **停雨冷卻倒數**: 還需連續無雨 {{ state_attr('sensor.cwa_rain_monitor', 'cooldown_remaining_cycles') }} 次輪詢才解除
  {% endif %}

  ---

  {% set stations = state_attr('sensor.cwa_rain_monitor', 'monitored_stations') %}
  {% if stations %}
  | 測站名稱 | 代碼 | 離家距離 | 10分雨量 | 判定 |
  |:---|:---:|:---:|:---:|:---:|
  {%- for st in stations %}
  | **{{ st.name }}** | `{{ st.id }}` | {{ st.distance_km }} km | {{ st.past_10min_mm }} mm | {{ '🌧️ 有雨' if st.is_raining else '☀️ 無雨' }} |
  {%- endfor %}
  {% endif %}

  ---
  *觀測更新: {{ state_attr('sensor.cwa_rain_monitor', 'last_updated') }}*
```

### 關鍵語法差異說明

```yaml
# ❌ 錯誤：使用 > (folded scalar) 會把換行變成空格，表格直接爆掉
content: >
  | 欄位A | 欄位B |

# ✅ 正確：使用 | (literal scalar) 保持原始換行
content: |
  | 欄位A | 欄位B |

# ❌ 錯誤：Jinja2 for 迴圈會在每行前後插入空白行，打斷表格
{% for st in stations %}
| {{ st.name }} | {{ st.value }} |
{% endfor %}

# ✅ 正確：加上減號 - 剝除迴圈產生的多餘空白
{%- for st in stations %}
| {{ st.name }} | {{ st.value }} |
{%- endfor %}
```

---

## 四、Entities 實體清單卡片 (零依賴最穩定)

如果您只是要快速查看狀態，不需要任何第三方卡片，HA 原生 `entities` 卡片是最穩定的選擇：

```yaml
type: entities
title: 氣象署雨量監控
show_header_toggle: false
entities:
  - entity: sensor.cwa_rain_monitor
    name: 最大10分鐘雨量
    icon: mdi:weather-rainy
  - entity: input_boolean.is_raining
    name: 正在下雨
  - entity: input_boolean.rain_approaching_warning
    name: 雨雲接近預警
  - type: attribute
    entity: sensor.cwa_rain_monitor
    attribute: estimated_dbz
    name: 推估雷達迴波
    icon: mdi:radar
    suffix: " dBZ"
  - type: attribute
    entity: sensor.cwa_rain_monitor
    attribute: active_stations_count
    name: 有雨測站數
    icon: mdi:cloud-percent
    suffix: " / 4 站"
  - type: attribute
    entity: sensor.cwa_rain_monitor
    attribute: consecutive_dry_cycles
    name: 連續無雨週期
    icon: mdi:timer-sand
    suffix: " 次"
```

---

## 五、Mushroom 卡片配置範例 (需 HACS)

若您已安裝 **Mushroom Cards** (HACS 前端)：

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-template-card
    primary: >
      {% if is_state('input_boolean.is_raining', 'on') %}
        🌧️ 正在下雨 ({{ states('sensor.cwa_rain_monitor') }} mm)
      {% elif is_state('input_boolean.rain_approaching_warning', 'on') %}
        ⛅ 雨雲接近預警
      {% else %}
        ☀️ 無降雨
      {% endif %}
    secondary: >
      雷達: {{ state_attr('sensor.cwa_rain_monitor', 'estimated_dbz') }} dBZ
      ┃ 有雨站: {{ state_attr('sensor.cwa_rain_monitor', 'active_stations_count') }}/4
    icon: >
      {% if is_state('input_boolean.is_raining', 'on') %}
        mdi:weather-pouring
      {% elif is_state('input_boolean.rain_approaching_warning', 'on') %}
        mdi:weather-partly-rainy
      {% else %}
        mdi:weather-sunny
      {% endif %}
    icon_color: >
      {% if is_state('input_boolean.is_raining', 'on') %}
        blue
      {% elif is_state('input_boolean.rain_approaching_warning', 'on') %}
        amber
      {% else %}
        green
      {% endif %}
    entity: sensor.cwa_rain_monitor
    tap_action:
      action: more-info

  - type: custom:mushroom-chips-card
    chips:
      - type: entity
        entity: input_boolean.is_raining
        name: 下雨
      - type: entity
        entity: input_boolean.rain_approaching_warning
        name: 預警
```

---

## 六、常見錯誤與踩坑紀錄

| 問題現象 | 根本原因 | 修正方式 |
|:---|:---|:---|
| **Markdown 卡片顯示 HTML 源碼** | 新版 HA 安全過濾器會剝除 HTML 標籤 | 不使用 HTML，純用 Markdown + Jinja2 語法 |
| **Markdown 表格歪斜/斷裂** | YAML 使用 `>` 折疊換行 + Jinja2 注入空白行 | 改用 `\|` (literal scalar) + `{%- -%}` 剝除空白 |
| **weather-chart-card 報錯** | 該卡片只接受 `weather.*` 實體，不接受 `sensor.*` | 綁定您 HA 的天氣整合實體 (如 `weather.forecast_home`)，測站數據用 Markdown 獨立顯示 |
| **room-elves-card 白屏** | 子項不支援 Jinja2 模板 + 陣列索引越界 | 放棄使用，改用 Entities 或 Mushroom 卡片 |
| **`weather.forecast_home` 不存在** | HA 尚未安裝天氣整合，或實體名稱不同 | 至「開發者工具」→「狀態」篩選 `weather.` 查看您的真實實體名稱 |
