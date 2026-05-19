"""把 raw 價格 + 事件 合成每檔的調整後價格 JSON → data/tickers/{code}.json。

調整方法：後復權 (today's adj_close = today's close, earlier dates scaled down)。

演算法：
1. 取出該檔的所有事件 (按日期排序)
2. 從最新到最舊倒著走，初始 factor=1.0
3. 每遇到一個事件 e (除權息日)，從前一個交易日往前所有 close 都需要 *= factor_inv
   等價地：在事件當日，乘以 (ref_price / prev_close) 給之前所有日期
   也就是：早於事件日的 close 都乘以 (ref_price / prev_close)

實作：
   adj[i] = close[i] for newest
   走訪事件 e (newest first)：對所有 d < e.date 的 row：adj *= e.ref_price / e.prev_close

輸出 schema：
  {
    "code": "0050",
    "name": "...",
    "market": "TWSE",
    "rows": [{"d":"YYYY-MM-DD", "c": close_raw, "a": adj_close}, ...],
    "events": [{"date","prev_close","ref_price","ratio","label"}, ...],
    "last_updated": "..."
  }
"""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, save_json, RAW_DIR, TICKERS_DIR, UNIVERSE_PATH, fmt_iso

EVENTS_PATH = RAW_DIR / "events.json"
PRICES_DIR = RAW_DIR / "prices"


def load_universe_index() -> dict[str, dict]:
    u = load_json(UNIVERSE_PATH, default={"listed": [], "otc": []})
    idx = {}
    for r in u.get("listed", []) + u.get("otc", []):
        idx[r["code"]] = r
    return idx


def build_one(code: str, name: str = "", market: str = "TWSE") -> dict | None:
    """從 raw/prices/{code}.json + raw/events.json 產生調整後 JSON。"""
    pp = PRICES_DIR / f"{code}.json"
    if not pp.exists():
        print(f"  [{code}] no price file")
        return None
    price_obj = load_json(pp)
    rows = price_obj.get("rows", [])
    if not rows:
        return None
    market = price_obj.get("market", market)

    events_all = load_json(EVENTS_PATH, default={"by_code": {}})
    # 合併 manual_events
    manual_events = load_json(Path(__file__).parent.parent / "data" / "manual_events.json", default={})
    for manual_code, manual_events_list in manual_events.items():
        if manual_code != "_README":
            if manual_code not in events_all.get("by_code", {}):
                events_all["by_code"][manual_code] = []
            events_all["by_code"][manual_code].extend(manual_events_list)

    events = events_all.get("by_code", {}).get(code, [])
    # 過濾掉事件無效的 (ref_price=0 等已在 fetch 過濾)
    events_use = [e for e in events if e.get("prev_close", 0) > 0 and e.get("ref_price", 0) > 0]
    events_use.sort(key=lambda e: e["date"])

    # 計算兩組 factor:
    #   factor_total: 套用所有事件 (含息含分割) → 給 'a' (TR adj close)
    #   factor_split: 只套用 split 事件 → 給 'c' (split-adjusted raw price)
    # 兩者皆為 forward-to-today = 1.0
    n = len(rows)
    factors_total = [1.0] * n
    factors_split = [1.0] * n
    ev_idx = len(events_use) - 1
    cur_total = 1.0
    cur_split = 1.0
    for i in range(n - 1, -1, -1):
        d = rows[i]["d"]
        while ev_idx >= 0 and events_use[ev_idx]["date"] > d:
            ev = events_use[ev_idx]
            ratio = ev["ref_price"] / ev["prev_close"]
            cur_total *= ratio
            if ev.get("type_label") == "split":
                cur_split *= ratio
            ev_idx -= 1
        factors_total[i] = cur_total
        factors_split[i] = cur_split

    out_rows = []
    for i, r in enumerate(rows):
        c = r.get("c")
        if c is None:
            continue
        out_rows.append({
            "d": r["d"],
            "c": round(c * factors_split[i], 6),  # split-adjusted price (連續可比)
            "a": round(c * factors_total[i], 6),  # 含息且含分割的後復權
        })

    # 事件中加入 ratio 與 label，方便前端展示
    ev_out = []
    for e in events_use:
        ratio = e["prev_close"] / e["ref_price"]  # >1 if positive return event
        ev_out.append({
            "date": e["date"],
            "prev_close": e["prev_close"],
            "ref_price": e["ref_price"],
            "ratio": round(ratio, 6),
            "label": e.get("type_label", ""),
        })

    obj = {
        "code": code,
        "name": price_obj.get("name") or name or "",
        "market": market,
        "rows": out_rows,
        "events": ev_out,
        "last_updated": price_obj.get("last_updated"),
    }
    return obj


def build_all(only_codes: list[str] | None = None) -> None:
    universe = load_universe_index()
    codes = only_codes or sorted(universe.keys())
    # 也加入所有已有 raw price 的 code (使用者前端輸入後抓的)
    for f in PRICES_DIR.glob("*.json"):
        c = f.stem
        if c not in codes:
            codes.append(c)
    for code in codes:
        info = universe.get(code, {})
        obj = build_one(code, name=info.get("name", ""), market=info.get("market", "TWSE"))
        if obj:
            save_json(TICKERS_DIR / f"{code}.json", obj)
            print(f"  [{code}] {obj['name']} {len(obj['rows'])} rows, {len(obj['events'])} events")


def build_index() -> None:
    """產生 data/index.json：列出所有可用的 ticker (code, name, market, start, end)。
    給前端讀取作為可選清單。"""
    items = []
    for f in sorted(TICKERS_DIR.glob("*.json")):
        obj = load_json(f)
        rows = obj.get("rows", [])
        if not rows:
            continue
        items.append({
            "code": obj["code"],
            "name": obj.get("name", ""),
            "market": obj.get("market", ""),
            "start": rows[0]["d"],
            "end": rows[-1]["d"],
            "n": len(rows),
        })
    save_json(TICKERS_DIR.parent / "index.json", {"tickers": items, "generated": items[0]["end"] if items else None})
    print(f"[index] {len(items)} tickers")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", help="若不給，build 全部 universe + 已抓的 raw")
    args = ap.parse_args()
    build_all(args.codes if args.codes else None)
    build_index()
