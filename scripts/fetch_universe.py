"""抓上市權值前 300 與上櫃權值前 150，輸出 data/universe.json。

來源：
- 上市：https://www.taifex.com.tw/cht/9/futuresQADetail
- 上櫃：https://www.taifex.com.tw/cht/2/tPEXPropertion
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bs4 import BeautifulSoup
from common import session, save_json, UNIVERSE_PATH, polite_sleep

TWSE_URL = "https://www.taifex.com.tw/cht/9/futuresQADetail"
OTC_URL = "https://www.taifex.com.tw/cht/2/tPEXPropertion"

LISTED_TOP = 300
OTC_TOP = 150


def parse_table(html: str):
    """Return list of (rank, code, name, weight) dicts from a TAIFEX page table."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    # 找含「排行/排名」與「比重」的表格
    for table in soup.find_all("table"):
        head_text = " ".join(th.get_text(strip=True) for th in table.find_all("th"))
        if ("排行" in head_text or "排名" in head_text) and "比重" in head_text:
            for tr in table.find_all("tr"):
                tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(tds) < 3:
                    continue
                # 欄位可能是 排行 / 證券名稱 / 比重，或 排行 / 代碼 / 名稱 / 比重
                rank = tds[0]
                if not rank.isdigit():
                    continue
                if len(tds) == 3:
                    name_field = tds[1]
                    m = re.match(r"^\s*(\d{4,5}[A-Z]?)\s+(.+)$", name_field)
                    if m:
                        code, name = m.group(1), m.group(2)
                    else:
                        # 也可能是「代碼\t名稱」全在一起
                        parts = name_field.split()
                        if len(parts) >= 2 and re.match(r"^\d{4,5}[A-Z]?$", parts[0]):
                            code, name = parts[0], " ".join(parts[1:])
                        else:
                            continue
                    weight = tds[2]
                else:
                    code, name, weight = tds[1], tds[2], tds[3]
                weight = weight.replace("%", "").strip()
                try:
                    weight_f = float(weight)
                except ValueError:
                    continue
                rows.append({
                    "rank": int(rank),
                    "code": code.strip(),
                    "name": name.strip(),
                    "weight": weight_f,
                })
            if rows:
                return rows
    return rows


def fetch(url: str):
    s = session()
    r = s.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def main():
    print(f"[universe] fetch listed: {TWSE_URL}")
    listed = parse_table(fetch(TWSE_URL))
    polite_sleep()
    print(f"[universe] fetch OTC: {OTC_URL}")
    otc = parse_table(fetch(OTC_URL))

    listed_top = sorted(listed, key=lambda r: r["rank"])[:LISTED_TOP]
    otc_top = sorted(otc, key=lambda r: r["rank"])[:OTC_TOP]

    universe = {
        "listed": [{**r, "market": "TWSE"} for r in listed_top],
        "otc": [{**r, "market": "TPEX"} for r in otc_top],
    }
    print(f"[universe] listed={len(universe['listed'])}, otc={len(universe['otc'])}")
    save_json(UNIVERSE_PATH, universe)
    print(f"[universe] saved → {UNIVERSE_PATH}")


if __name__ == "__main__":
    main()
