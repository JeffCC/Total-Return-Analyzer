"""一鍵增量更新：universe → prices (top 300+150) → events → IR0001 → 重建 tickers JSON。

第一次跑會花較久 (歷史回填到 2020-01-01)；之後增量只抓上次到今天。

用法：
  python scripts/update_all.py                # 完整更新 (含 OTC 事件、慢)
  python scripts/update_all.py --no-otc-events # 只更新 TWSE 事件 (快)
  python scripts/update_all.py --skip-universe # 不重抓 universe (跳過 taifex)
  python scripts/update_all.py --only 2330,0056 # 只更新特定代碼 (含 events 與 prices)
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_json, UNIVERSE_PATH
import fetch_universe
import fetch_prices
import fetch_events
import fetch_benchmarks
import build_adjusted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-universe", action="store_true")
    ap.add_argument("--no-otc-events", action="store_true", help="略過 OTC events (FinMind 慢)")
    ap.add_argument("--only", help="逗號分隔的代碼清單 (限定更新範圍)")
    args = ap.parse_args()

    if not args.skip_universe and not args.only:
        print("=== Step 1: universe ===")
        fetch_universe.main()

    universe = load_json(UNIVERSE_PATH, default={"listed": [], "otc": []})
    listed = universe.get("listed", [])
    otc = universe.get("otc", [])

    if args.only:
        wanted = set(args.only.split(","))
        listed = [r for r in listed if r["code"] in wanted]
        otc = [r for r in otc if r["code"] in wanted]
        # 也支援 universe 裡沒有的 (使用者輸入新的代碼)
        for c in wanted:
            if not any(r["code"] == c for r in listed + otc):
                # 預設當作 TWSE，使用者可手動改 universe
                listed.append({"code": c, "name": "", "market": "TWSE"})

    print(f"=== Step 2: prices (listed={len(listed)}, otc={len(otc)}) ===")
    for i, r in enumerate(listed, 1):
        print(f" [{i}/{len(listed)}] TWSE {r['code']} {r.get('name','')}")
        try:
            fetch_prices.update_ticker(r["code"], "TWSE")
        except Exception as e:
            print(f"  ! error: {e}")
    for i, r in enumerate(otc, 1):
        print(f" [{i}/{len(otc)}] TPEX {r['code']} {r.get('name','')}")
        try:
            fetch_prices.update_ticker(r["code"], "TPEX")
        except Exception as e:
            print(f"  ! error: {e}")

    print("=== Step 3: events ===")
    otc_codes = None if args.no_otc_events else [r["code"] for r in otc]
    fetch_events.update_events(otc_codes=otc_codes)

    print("=== Step 4: IR0001 + 0050 benchmarks ===")
    fetch_benchmarks.fetch_ir0001()

    print("=== Step 5: build adjusted JSON ===")
    only_codes = None
    if args.only:
        only_codes = list(set(args.only.split(",")))
    build_adjusted.build_all(only_codes)

    # 0050 benchmark 必須在 build_adjusted 之後
    fetch_benchmarks.copy_0050_benchmark()
    build_adjusted.build_index()
    print("=== Done ===")


if __name__ == "__main__":
    main()
