"""Második kíméletes próba: rendezés, lapozás veszteségmentessége, letöltés formátuma.
~15 kérés, kérések között 2 mp szünet."""
import sys
import time
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_api import BASE, TAG, UA, URL  # noqa: E402

SUB_HARMADIK = TAG + "/Harmadik országbeli állampolgárok beutazása és tartózkodása"
SUB_MENEDEK = TAG + "/Menedékjog"


def post(s, **ov):
    r = s.post(URL, data={**BASE, **ov}, timeout=30)
    r.raise_for_status()
    time.sleep(2)
    return r.json()


def main():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get("https://eakta.birosag.hu/anonimizalt-hatarozatok", timeout=30)

    # 1) NemHivatkozhato mező elhagyása
    base_wo = {k: v for k, v in BASE.items() if k != "NemHivatkozhato"}
    r = s.post(URL, data={**base_wo, "HierarchikusPertargy": TAG}, timeout=30).json()
    time.sleep(2)
    print("fo cimke, NemHivatkozhato nelkul:", r.get("Count"))

    # 2) Rendezés publikálási dátum szerint
    for sort in ("IndexelesIdejeCsokkeno", "IndexelesIdejeNovekvo"):
        js = post(s, HierarchikusPertargy=SUB_HARMADIK, Rendezes=sort, ResultCount="5")
        print(sort, [x.get("IndexelesIdeje", "")[:10] for x in js.get("List", [])])

    # 3) Lapozás veszteségmentessége a fő címkén (889 körül -> 9 oldal)
    ids, total, start = [], None, 0
    while True:
        js = post(s, HierarchikusPertargy=TAG, ResultCount="100", ResultStartIndex=str(start))
        total = js.get("Count")
        lst = js.get("List", [])
        ids += [x["EgyediAzonosito"] for x in lst]
        if len(lst) < 100:
            break
        start += 100
    dup = [k for k, v in Counter(ids).items() if v > 1]
    print(f"lapozas: Count={total}, lekert={len(ids)}, egyedi={len(set(ids))}, duplikalt={len(dup)}")

    # 4) Egy határozat letöltése (mobil GET végpont) -> formátum
    js = post(s, HierarchikusPertargy=SUB_MENEDEK, ResultCount="1")
    it = js["List"][0]
    dl = ("https://eakta.birosag.hu/AnonimizaltHatarozat/DownloadHatarozatMobile"
          f"?Area=&birosagName={it['MeghozoBirosag']}&ugyszam={it['Azonosito']}&azonosito={it['IndexId']}")
    r = s.get(dl, timeout=60)
    print("letoltes:", r.status_code, r.headers.get("Content-Type"), len(r.content), "bajt",
          r.headers.get("Content-Disposition", "")[:120])
    print("minta:", it["Azonosito"], it["MeghozoBirosag"], it["HatarozatEve"], it["EgyediAzonosito"])


if __name__ == "__main__":
    main()
