# 台股總報酬比較 (Total-Return-Analyzer)

含息、含配股、含現增、含分割的台股總報酬比較工具。可同時比較 2~6 檔上市/上櫃個股或 ETF，並可選用 0050 與 IR0001 (加權報酬指數) 作為基準。

## 含息計算原理

採用標準的「後復權因子法」：

```
factor *= 除權息前收盤 / 除權息參考價   # 對所有事件
adj_close[t] = close[t] × cumulative_factor (forward to today = 1.0)
```

由於台灣交易所公布的「除權息參考價」已假設**現金股利 + 股票股利 + 現金增資（必認）**全部反映，因此單一公式即可同時處理三類事件。股票分割另以人工事件補錄。

## 目錄結構

```
.
├── data/
│   ├── universe.json          # 上市權值前 300 + 上櫃前 150
│   ├── manual_events.json     # 人工補錄事件（如 0050 分割）
│   ├── index.json             # 前端讀取：所有可用 ticker 清單
│   ├── tickers/{code}.json    # 每檔調整後價格 + 事件
│   ├── benchmarks/            # 0050 / IR0001
│   └── raw/                   # 中間檔 (原始 prices, events)
├── scripts/
│   ├── fetch_universe.py      # 抓 TAIFEX 權值清單
│   ├── fetch_prices.py        # TWSE STOCK_DAY + TPEX tradingStock
│   ├── fetch_events.py        # TWSE TWT49U + FinMind (OTC)
│   ├── fetch_benchmarks.py    # IR0001 + 0050 (FinMind)
│   ├── build_adjusted.py      # 計算後復權，輸出 tickers/{code}.json
│   ├── update_all.py          # 一鍵增量更新
│   └── common.py              # 共用工具
├── index.html / css / js      # 前端 (純 HTML + ECharts)
├── requirements.txt
└── README.md
```

## 使用流程

### 0. 安裝依賴

```bash
python -m pip install -r requirements.txt
```

### 1. 首次完整下載 (耗時)

```bash
python scripts/update_all.py
```

第一次跑會抓：
- TAIFEX 權值清單 (上市前 300、上櫃前 150)
- 每檔自 2020-01-01 至今的日成交價
- 全市場除權息事件 (TWSE listed) + OTC 事件 (FinMind, per-stock)
- IR0001 加權報酬指數
- 重建所有 tickers JSON 與索引

預估時間：listed 300 檔 ≈ 30~60 分鐘 (每檔每月一次 API 呼叫)。

如要更快，可先跳過 OTC 事件：

```bash
python scripts/update_all.py --no-otc-events
```

### 2. 只更新少數標的

```bash
python scripts/update_all.py --only 2330,0056,00878
```

也可加新代碼（不在 universe 中）：會以 TWSE 抓取，若是 OTC 需改 universe.json 或手動跑 `python scripts/fetch_prices.py 5274 --market TPEX`。

### 3. 增量更新

之後每天跑同一個 `update_all.py` 會自動只抓上次到今天的差異。

### 4. 啟動前端

任何靜態 server 即可：

```bash
python -m http.server 8892
# 開 http://localhost:8892/
```

## 前端功能

- **標的選擇**：搜尋代碼/名稱，最多 6 檔
- **基準勾選**：0050（虛線）、IR0001（虛線，已含息）
- **區間**：1M / 3M / 6M / YTD / 1Y / MAX / 自訂
  - **MAX**：取所有勾選標的 (含基準) 中**最晚的上市日**為起點
- **圖表**：累積報酬曲線（起點歸零 0%），含 ECharts dataZoom
- **表格**：含息報酬、純價格報酬 (split-adjusted)、年化報酬

## 人工補錄事件

`data/manual_events.json` 用於補錄 API 取不到的事件，例如：

```json
{
  "0050": [
    {"date": "2025-06-19", "prev_close": 4, "ref_price": 1, "type_label": "split", "note": "1拆4"}
  ]
}
```

格式：`prev_close / ref_price` 即為 factor。如 1拆4 → factor=4，可用 `prev_close=4, ref_price=1` 表示。

`type_label="split"` 時，分割也會反映在 split-adjusted 的純價格序列上 (`c` 欄)，避免分割造成價格圖跳水。

## 已知限制

1. **OTC 歷史事件**：TPEX 改版後不再公開歷史除權息查詢，改採 FinMind per-stock API。免費版有 600 req/hr 限制，首次跑 150 檔約需數分鐘。
2. **現金增資**：理論上 TWSE 除權息參考價已含現增（假設必認），但若為單獨現增除權（無除息日），可能需人工補錄至 `manual_events.json`。
3. **資料起點**：預設 2020-01-01，如需更早可改 `scripts/common.py` 的 `START_DATE`。

## 資料來源

- 上市股價：[TWSE STOCK_DAY](https://www.twse.com.tw/zh/page/trading/exchange/STOCK_DAY.html)
- 上櫃股價：[TPEX tradingStock](https://www.tpex.org.tw/)
- 上市除權息：[TWSE TWT49U](https://www.twse.com.tw/zh/exchangeReport/TWT49U)
- 上櫃除權息：[FinMind TaiwanStockDividendResult](https://finmindtrade.com/)
- 加權報酬指數：FinMind TaiwanStockTotalReturnIndex (data_id=TAIEX)
- 權值清單：[TAIFEX 上市股票權值清單](https://www.taifex.com.tw/cht/9/futuresQADetail) / [上櫃](https://www.taifex.com.tw/cht/2/tPEXPropertion)
