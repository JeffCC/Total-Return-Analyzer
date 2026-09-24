"""快速更新指定標的 — 給日常查詢用的輕量版。

跟 update_all.py --only 的差異:
  - 跳過 universe (TAIFEX) 抓取
  - 跳過 benchmarks (IR0001 / 0050) 更新;可用 --with-benchmarks 加回
  - events 只做 TWSE 增量;若代碼含 OTC 或用 --with-otc-events 才抓 FinMind
  - 最後仍會重建這些代碼的 tickers/{code}.json 與 index.json

用法:
  python scripts/quick_update.py 2330 0056 00878
  python scripts/quick_update.py 2330,0056,00878          # 逗號也可 (跟 --only 語法一致)
  python scripts/quick_update.py 5274 --market TPEX       # 全部強制當上櫃
  python scripts/quick_update.py 2330 5274 --tpex 5274    # 混合: 逐檔標記上櫃
  python scripts/quick_update.py 2330 --with-benchmarks   # 順便更新 0050 / IR0001
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, UNIVERSE_PATH
import fetch_prices
import fetch_events
import fetch_benchmarks
import build_adjusted


def resolve_market(code: str, forced_market: str | None, tpex_codes: set[str], universe_idx: dict) -> str:
    if forced_market:
        return forced_market
    if code in tpex_codes:
        return "TPEX"
    if code in universe_idx:
        return universe_idx[code].get("market", "TWSE")
    return "TWSE"  # 預設當上市


def main():
    ap = argparse.ArgumentParser(description="Quick update for a small list of tickers")
    ap.add_argument("codes", nargs="+", help="ticker codes (空白或逗號分隔皆可)")
    ap.add_argument("--market", choices=["TWSE", "TPEX"], help="全部強制此市場")
    ap.add_argument("--tpex", nargs="+", default=[], help="標為 OTC 的代碼 (混合上市/上櫃時用)")
    ap.add_argument("--with-benchmarks", action="store_true", help="同時更新 IR0001 + 0050")
    ap.add_argument("--with-otc-events", action="store_true", help="強制跑 FinMind OTC 事件 (慢)")
    args = ap.parse_args()

    # 支援 "2330,0056" 這種寫法
    codes: list[str] = []
    for c in args.codes:
        codes.extend(x.strip() for x in c.split(",") if x.strip())
    codes = list(dict.fromkeys(codes))  # dedup, 保留順序
    tpex_forced = set(args.tpex)

    universe = load_json(UNIVERSE_PATH, default={"listed": [], "otc": []})
    universe_idx = {r["code"]: r for r in universe.get("listed", []) + universe.get("otc", [])}

    print(f"=== Step 1: prices for {len(codes)} ticker(s) ===")
    incomplete = []
    has_otc = False
    for i, code in enumerate(codes, 1):
        mkt = resolve_market(code, args.market, tpex_forced, universe_idx)
        if mkt == "TPEX":
            has_otc = True
        print(f" [{i}/{len(codes)}] {mkt} {code}")
        try:
            _, fm = fetch_prices.update_ticker(code, mkt)
            if fm:
                incomplete.append((code, mkt, fm))
        except Exception as e:
            print(f"  ! error: {e}")
            incomplete.append((code, mkt, "exception"))

    print("=== Step 2: events (TWSE incremental) ===")
    otc_codes = None
    if args.with_otc_events or has_otc:
        otc_codes = [c for c in codes if resolve_market(c, args.market, tpex_forced, universe_idx) == "TPEX"]
        if not otc_codes:
            otc_codes = None
    fetch_events.update_events(otc_codes=otc_codes)

    if args.with_benchmarks:
        print("=== Step 3: benchmarks (IR0001 + 0050) ===")
        fetch_benchmarks.fetch_ir0001()

    print("=== Step 4: build adjusted JSON ===")
    build_adjusted.build_all(codes)

    if args.with_benchmarks:
        fetch_benchmarks.copy_0050_benchmark()

    build_adjusted.build_index()
    print("=== Done ===")

    if incomplete:
        print()
        print(f"!!! {len(incomplete)} ticker(s) had API failures — re-run the same command to fill:")
        for code, mkt, fm in incomplete:
            print(f"    {mkt} {code}  stopped at {fm}")


if __name__ == "__main__":
    main()
