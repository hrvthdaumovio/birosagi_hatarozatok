"""Harmadik próba: stabil-e a lapozás publikálási dátum szerinti rendezéssel?
Fő címke (~889 találat) -> 9 oldal, 2 mp szünettel."""
import sys
import time
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_api import BASE, TAG, UA, URL  # noqa: E402


def page_all(s, sort):
    ids, start, total = [], 0, None
    while True:
        r = s.post(URL, data={**BASE, "HierarchikusPertargy": TAG, "Rendezes": sort,
                              "ResultCount": "100", "ResultStartIndex": str(start)}, timeout=30)
        r.raise_for_status()
        js = r.json()
        total = js.get("Count")
        lst = js.get("List", [])
        ids += [x["EgyediAzonosito"] for x in lst]
        time.sleep(2)
        if len(lst) < 100:
            return total, ids
        start += 100


def main():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get("https://eakta.birosag.hu/anonimizalt-hatarozatok", timeout=30)
    for sort in ("IndexelesIdejeNovekvo",):
        total, ids = page_all(s, sort)
        dup = sum(1 for v in Counter(ids).values() if v > 1)
        print(f"{sort}: Count={total}, lekert={len(ids)}, egyedi={len(set(ids))}, duplikalt={dup}")


if __name__ == "__main__":
    main()
