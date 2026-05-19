"""抓 IR0001 加權報酬指數 (含息) 與 0050 (作為 benchmark)。

IR0001 透過 FinMind dataset=TaiwanStockTotalReturnIndex, data_id='TAIEX'
(FinMind 命名上叫 TAIEX，但其實是含息報酬指數 IR0001 的數值 ~51000+)。

輸出 schema 與一般 ticker 相同 (rows: [{d,c,a}]，但 a==c 因本身已含息):
  data/benchmarks/IR0001.json
  data/benchmarks/0050.json (符號連結至一般 ticker JSON 的副本)
"""
from __future__ import annotations
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import session, polite_sleep, save_json, load_json, BENCH_DIR, TICKERS_DIR, START_DATE, fmt_iso

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def fetch_ir0001(end: date | None = None) -> dict:
    end = end or date.today()
    path = BENCH_DIR / "IR0001.json"
    existing = load_json(path, default={"code": "IR0001", "name": "加權報酬指數", "rows": []})
    rows = existing.get("rows", [])
    if rows:
        last_d = date.fromisoformat(rows[-1]["d"])
        start = last_d + timedelta(days=1)
    else:
        start = START_DATE
    if start > end:
        print(f"[IR0001] up-to-date ({rows[-1]['d'] if rows else 'n/a'})")
        return existing
    s = session()
    print(f"[IR0001] fetching {start} → {end}")
    # FinMind 一次最多 ~5 年，分段抓
    cur = start
    new_rows = []
    while cur <= end:
        chunk_end = min(cur.replace(year=cur.year + 4) if cur.year + 4 <= end.year else end, end)
        r = s.get(FINMIND_URL, params={
            "dataset": "TaiwanStockTotalReturnIndex",
            "data_id": "TAIEX",
            "start_date": fmt_iso(cur),
            "end_date": fmt_iso(chunk_end),
        }, timeout=60)
        js = r.json()
        if js.get("status") != 200:
            print(f"  ! error: {js.get('msg')}")
            break
        for row in js.get("data", []):
            d = row["date"]
            c = float(row["price"])
            new_rows.append({"d": d, "c": round(c, 2), "a": round(c, 2)})
        cur = chunk_end + timedelta(days=1)
        polite_sleep()
    seen = {r["d"] for r in rows}
    rows.extend(r for r in new_rows if r["d"] not in seen)
    rows.sort(key=lambda r: r["d"])
    existing["rows"] = rows
    existing["last_updated"] = fmt_iso(date.today())
    save_json(path, existing)
    print(f"[IR0001] +{len(new_rows)} rows, total {len(rows)}")
    return existing


def copy_0050_benchmark() -> None:
    """把 tickers/0050.json 複製一份到 benchmarks/0050.json。"""
    src = TICKERS_DIR / "0050.json"
    if not src.exists():
        print("[bench 0050] tickers/0050.json not found, skip")
        return
    obj = load_json(src)
    obj["name"] = obj.get("name") or "元大台灣50"
    save_json(BENCH_DIR / "0050.json", obj)
    print(f"[bench 0050] copied ({len(obj['rows'])} rows)")


if __name__ == "__main__":
    fetch_ir0001()
    copy_0050_benchmark()
