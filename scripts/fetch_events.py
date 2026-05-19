"""抓取除權除息事件 (含現金股利/股票股利/現金增資合併計算的除權息參考價)。

關鍵觀察：TWSE/TPEX 提供的 (除權息前收盤價, 除權息參考價) 已內含所有除權息因素
(現金股利/股票股利/現金增資)，且現增已假設投資人必認 (理論除權息參考價就是這樣推出的)。

因此後復權因子：
    factor *= prev_close / ref_price
即可正確反映「持股期間所有股利再投入、所有現增認股」的累積總報酬。

人工補錄事件 (data/manual_events.json)：
- 股票分割 (例如 0050 於 2025-06-19 1拆4)：以 prev_close=4, ref_price=1 表示 factor=4
- API 缺漏的歷史事件

API:
- TWSE: https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json
- TPEX: https://www.tpex.org.tw/www/zh-tw/afterTrading/exRightExDividend?date=YYYY/MM/DD&response=json (按月)

欄位 (TWT49U / TPEX 一致)：
  0:資料日期 1:代號 2:名稱 3:除權息前收盤價 4:除權息參考價 5:權值+息值 6:權/息 ...
"""
from __future__ import annotations
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import session, polite_sleep, load_json, save_json, RAW_DIR, MANUAL_EVENTS_PATH, START_DATE, fmt_iso

EVENTS_PATH = RAW_DIR / "events.json"
TWSE_URL = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
# TPEX 改版後不再提供歷史除權息查詢，改用 FinMind 的 TaiwanStockDividendResult dataset (per-stock)
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def _f(s) -> float:
    if s is None:
        return 0.0
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_roc_date(d_roc: str) -> str | None:
    """民國日期 (e.g. '113年07月01日' or '113/07/01') → ISO 'YYYY-MM-DD'."""
    s = d_roc.replace("年", "/").replace("月", "/").replace("日", "").replace("-", "/").strip()
    parts = [p for p in s.split("/") if p]
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{y+1911:04d}-{m:02d}-{d:02d}"
    except ValueError:
        return None


def parse_row(row: list) -> dict | None:
    if not row or len(row) < 7:
        return None
    d_iso = _parse_roc_date(str(row[0]))
    if not d_iso:
        return None
    code = str(row[1]).strip()
    prev_close = _f(row[3])
    ref_price = _f(row[4])
    if prev_close <= 0 or ref_price <= 0:
        return None
    return {
        "date": d_iso,
        "code": code,
        "prev_close": prev_close,
        "ref_price": ref_price,
        "type_label": str(row[6]).strip() if len(row) > 6 else "",
    }


def fetch_twse_range(s, start: date, end: date) -> list[dict]:
    out = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=29), end)
        params = {"startDate": cur.strftime("%Y%m%d"), "endDate": chunk_end.strftime("%Y%m%d"), "response": "json"}
        print(f"  TWSE events {cur} → {chunk_end}")
        try:
            r = s.get(TWSE_URL, params=params, timeout=30)
            r.raise_for_status()
            r.encoding = "utf-8"
            js = r.json()
        except Exception as e:
            print(f"    ! error: {e}")
            cur = chunk_end + timedelta(days=1)
            polite_sleep(2.5)
            continue
        if js.get("stat") == "OK":
            for row in js.get("data", []):
                ev = parse_row(row)
                if ev:
                    out.append(ev)
        cur = chunk_end + timedelta(days=1)
        polite_sleep()
    return out


def fetch_finmind_one(s, code: str, start: date, end: date) -> list[dict]:
    """Per-stock FinMind 除權息結果。免費，需限速。"""
    try:
        r = s.get(FINMIND_URL, params={
            "dataset": "TaiwanStockDividendResult",
            "data_id": code,
            "start_date": fmt_iso(start),
            "end_date": fmt_iso(end),
        }, timeout=30)
        r.raise_for_status()
        js = r.json()
    except Exception as e:
        print(f"    ! FinMind {code} error: {e}")
        return []
    if js.get("status") != 200:
        return []
    out = []
    for row in js.get("data", []):
        prev_close = float(row.get("before_price", 0) or 0)
        ref_price = float(row.get("reference_price", 0) or 0)
        if prev_close <= 0 or ref_price <= 0:
            continue
        out.append({
            "date": row["date"],
            "code": code,
            "prev_close": prev_close,
            "ref_price": ref_price,
            "type_label": row.get("stock_or_cache_dividend", ""),
        })
    return out


def fetch_otc_events(codes: list[str], start: date, end: date) -> list[dict]:
    """OTC events via FinMind (per-stock)."""
    s = session()
    out = []
    for i, code in enumerate(codes, 1):
        print(f"  FinMind OTC {code} [{i}/{len(codes)}]")
        out.extend(fetch_finmind_one(s, code, start, end))
        polite_sleep(0.6)  # FinMind 免費 600/hr
    return out


def merge_events(by_code: dict, new_events: list[dict]) -> None:
    for ev in new_events:
        code = ev["code"]
        lst = by_code.setdefault(code, [])
        existing_dates = {e["date"] for e in lst}
        if ev["date"] in existing_dates:
            continue
        lst.append({k: v for k, v in ev.items() if k != "code"})
    for code in by_code:
        by_code[code].sort(key=lambda e: e["date"])


def apply_manual_events(by_code: dict) -> None:
    """Manual events override / supplement (e.g. 0050 split)."""
    manual = load_json(MANUAL_EVENTS_PATH, default={})
    for code, evs in manual.items():
        if code.startswith("_") or not isinstance(evs, list):
            continue
        lst = by_code.setdefault(code, [])
        existing = {e["date"]: e for e in lst}
        for ev in evs:
            ev_clean = {k: v for k, v in ev.items() if k != "code"}
            existing[ev["date"]] = ev_clean
        by_code[code] = sorted(existing.values(), key=lambda e: e["date"])


def update_events(end: date | None = None, otc_codes: list[str] | None = None) -> dict:
    end = end or date.today()
    data = load_json(EVENTS_PATH, default={"by_code": {}, "last_updated": None})
    last = data.get("last_updated")
    start = date.fromisoformat(last) + timedelta(days=1) if last else START_DATE
    if start > end:
        print(f"[events] up-to-date ({last})")
    else:
        print(f"[events] fetching {start} → {end}")
        s = session()
        twse_evs = fetch_twse_range(s, start, end)
        merge_events(data["by_code"], twse_evs)
        otc_evs = []
        if otc_codes:
            otc_evs = fetch_otc_events(otc_codes, start, end)
            merge_events(data["by_code"], otc_evs)
        data["last_updated"] = fmt_iso(end)
        print(f"[events] +{len(twse_evs)} TWSE, +{len(otc_evs)} OTC (FinMind)")
    apply_manual_events(data["by_code"])
    save_json(EVENTS_PATH, data)
    return data


def update_otc_for_codes(codes: list[str], end: date | None = None) -> None:
    """為特定 OTC 代碼補抓事件 (對非 universe 內、使用者輸入的代碼)。"""
    end = end or date.today()
    data = load_json(EVENTS_PATH, default={"by_code": {}, "last_updated": None})
    evs = fetch_otc_events(codes, START_DATE, end)
    merge_events(data["by_code"], evs)
    apply_manual_events(data["by_code"])
    save_json(EVENTS_PATH, data)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-otc", action="store_true", help="只抓 TWSE listed events")
    args = ap.parse_args()
    from common import UNIVERSE_PATH as _UP
    otc = None
    if not args.no_otc:
        u = load_json(_UP, default={"otc": []})
        otc = [r["code"] for r in u.get("otc", [])]
    update_events(otc_codes=otc)
