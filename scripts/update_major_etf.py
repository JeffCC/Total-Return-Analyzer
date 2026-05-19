"""抓取規模較大的 ETF (已發行受益權單位數 >= 1,000,000,000)，
價格從 2025-01-01 到今天。

資料來源:
  ETF 清單 + 已發行單位數: https://mis.twse.com.tw/stock/data/all_etf.txt
  (TWSE 基本市況報導 indicator-disclosure-etf 頁面所讀的 JSON)

清單存到 data/major_etf.json，再呼叫 fetch_prices + fetch_events + build_adjusted。

用法：
  python scripts/update_major_etf.py
  python scripts/update_major_etf.py --threshold 500000000   # 自訂閾值
  python scripts/update_major_etf.py --start 2025-01-01      # 自訂起始日 (預設 2025-01-01)
  python scripts/update_major_etf.py --list-only             # 只列出符合條件的 ETF 不抓價
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import session, save_json, load_json, DATA, polite_sleep, fmt_iso
import fetch_prices
import fetch_events
import fetch_benchmarks
import build_adjusted

ALL_ETF_URL = "https://mis.twse.com.tw/stock/data/all_etf.txt"
MAJOR_ETF_PATH = DATA / "major_etf.json"
DEFAULT_THRESHOLD = 1_000_000_000          # 10 digits ≥ 10 億單位
DEFAULT_START = date(2025, 1, 1)


def fetch_all_etf_list() -> list[dict]:
    """回傳 [{code, name, issued_units, market}]。掃過所有 issuer 群組。"""
    s = session()
    r = s.get(ALL_ETF_URL, timeout=30)
    r.raise_for_status()
    obj = json.loads(r.text)
    out = []
    # JSON 結構：{"a1": [{msgArray: [...]}, ...], "a2": [...], ...}
    # 每個 group 內都有 msgArray
    for top_key, top_val in obj.items():
        if not isinstance(top_val, list):
            continue
        for grp in top_val:
            for row in grp.get("msgArray", []):
                code = str(row.get("a", "")).strip()
                if not code:
                    continue
                name = str(row.get("b", "")).strip()
                # c 可能是 float 或 string
                c_raw = row.get("c", 0)
                try:
                    issued = float(str(c_raw).replace(",", ""))
                except (ValueError, TypeError):
                    issued = 0
                out.append({
                    "code": code,
                    "name": name,
                    "issued_units": int(issued),
                    "group": top_key,
                })
    # 去重 (同 code 取第一個出現的)
    seen = set()
    dedup = []
    for r in out:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        dedup.append(r)
    return dedup


def filter_major(etfs: list[dict], threshold: int) -> list[dict]:
    return [e for e in etfs if e["issued_units"] >= threshold]


def determine_market(code: str) -> str:
    """簡易判定: 上櫃 ETF 代碼通常 6開頭(6字頭) 或特殊範圍；
    多數 ETF 是 0-開頭的上市。實務上需要查 universe。
    我們先全部當 TWSE，遇 fetch 失敗再 fallback TPEX。"""
    return "TWSE"


def fetch_prices_with_fallback(code: str, start: date, end: date) -> dict | None:
    """先嘗試 TWSE，失敗 (拿不到資料) 則嘗試 TPEX。"""
    obj = fetch_prices.update_ticker(code, "TWSE")
    if obj.get("rows"):
        return obj
    # 試 TPEX
    print(f"  [{code}] TWSE no data, try TPEX")
    obj = fetch_prices.update_ticker(code, "TPEX")
    return obj if obj.get("rows") else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                    help="已發行受益權單位數最小值 (預設 1,000,000,000)")
    ap.add_argument("--start", default=fmt_iso(DEFAULT_START),
                    help="價格起始日 (預設 2025-01-01)")
    ap.add_argument("--list-only", action="store_true", help="只列出符合條件的 ETF 不抓價")
    ap.add_argument("--skip-events", action="store_true", help="跳過除權息事件抓取")
    args = ap.parse_args()

    # 暫時改變全域 START_DATE
    import common as _c
    orig_start = _c.START_DATE
    _c.START_DATE = date.fromisoformat(args.start)
    fetch_prices.START_DATE = _c.START_DATE

    print(f"[major_etf] fetching ETF list from {ALL_ETF_URL}")
    etfs = fetch_all_etf_list()
    print(f"[major_etf] total ETFs: {len(etfs)}")
    major = filter_major(etfs, args.threshold)
    major.sort(key=lambda e: -e["issued_units"])
    print(f"[major_etf] >= {args.threshold:,} units : {len(major)} ETFs")
    save_json(MAJOR_ETF_PATH, {
        "threshold": args.threshold,
        "as_of": fmt_iso(date.today()),
        "etfs": major,
    })

    # 列印前 20
    print("  Top 20 by issued units:")
    for e in major[:20]:
        print(f"    {e['code']:>6}  {e['issued_units']:>15,}  {e['name']}")
    if len(major) > 20:
        print(f"    ... and {len(major) - 20} more")

    if args.list_only:
        return

    today = date.today()
    print(f"\n[major_etf] fetching prices {args.start} → {today}")
    successes, failures = [], []
    for i, e in enumerate(major, 1):
        code = e["code"]
        print(f" [{i}/{len(major)}] {code} {e['name']}")
        try:
            obj = fetch_prices_with_fallback(code, _c.START_DATE, today)
            if obj and obj.get("rows"):
                successes.append(code)
            else:
                failures.append(code)
        except Exception as ex:
            print(f"  ! error: {ex}")
            failures.append(code)

    if not args.skip_events:
        # ETF 的收益分配 TWSE TWT49U 不收，必須用 FinMind 對每檔 ETF 各抓一次
        print(f"\n[major_etf] events: TWSE TWT49U for listed stocks")
        fetch_events.update_events()
        print(f"\n[major_etf] events: FinMind per-ETF for {len(major)} ETFs")
        etf_codes = [e["code"] for e in major]
        fetch_events.update_otc_for_codes(etf_codes, end=today)

    print(f"\n[major_etf] benchmarks")
    fetch_benchmarks.fetch_ir0001()

    print(f"\n[major_etf] build adjusted JSON for {len(successes)} ETFs")
    build_adjusted.build_all(successes)
    fetch_benchmarks.copy_0050_benchmark()
    build_adjusted.build_index()

    print(f"\n=== Done ===")
    print(f"  successes: {len(successes)}")
    print(f"  failures : {len(failures)} {failures}")

    _c.START_DATE = orig_start


if __name__ == "__main__":
    main()
