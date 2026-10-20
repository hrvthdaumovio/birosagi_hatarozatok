"""Egyszeri, kíméletes API-próba: a Search végpont működik-e a Tárgycímke-szűrővel,
és hány találat van szeletenként. Csak darabszámot kér (ResultCount=1), szünetekkel."""
import json
import sys
import time

import requests

URL = "https://eakta.birosag.hu/AnonimizaltHatarozat/Search"
UA = "Mozilla/5.0 (research; idegenrendeszeti-hatarozatok-gyujtes)"
TAG = "Idegenrendészet, menekültügy és állampolgársági ügyek"

BASE = {
    "ResultCount": "1",
    "ResultStartIndex": "0",
    "KeresoSzo": "",
    "Rezume": "",
    "JogTerulet": "",
    "MeghozoBirosag": "",
    "ErintettKozigazgatsaiSzerv": "",
    "Azonosito": "",
    "HatarozatFajta": "",
    "MeghozatalIdejeTol": "",
    "MeghozatalIdejeIg": "",
    "Ugycsoport": "",
    "Ugytargy": "",
    "BefejezesMod": "",
    "ItelkezesiGyakorlat": "",
    "EUJoganyag": "",
    "EJEBJoganyag": "",
    "Kollegium": "",
    "HatarozatTipus": "",
    "EgyediAzonosito": "",
    "Rendezes": "BirosagiSzint",
    "HierarchikusPertargy": "",
    "NemHivatkozhato": "nem",
}


def count(session, **overrides):
    data = {**BASE, **overrides}
    r = session.post(URL, data=data, timeout=30)
    r.raise_for_status()
    js = r.json()
    return js.get("Count"), js.get("List", [])


def main():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get("https://eakta.birosag.hu/anonimizalt-hatarozatok", timeout=30)

    probes = [
        ("osszes (szures nelkul)", {}),
        ("tag: fo cimke", {"HierarchikusPertargy": TAG}),
        ("tag: harmadik orszagbeli", {"HierarchikusPertargy": TAG + "/Harmadik országbeli állampolgárok beutazása és tartózkodása"}),
        ("tag: menedekjog", {"HierarchikusPertargy": TAG + "/Menedékjog"}),
        ("tag: fo cimke + minden hatarozat", {"HierarchikusPertargy": TAG, "NemHivatkozhato": "igen"}),
        ("kulcsszo: Idegenrendeszeti Foigazgatosag", {"KeresoSzo": "Országos Idegenrendészeti Főigazgatóság"}),
    ]
    out = {}
    sample = None
    for label, ov in probes:
        try:
            c, lst = count(s, **ov)
            out[label] = c
            if lst and sample is None and "HierarchikusPertargy" in ov:
                sample = lst[0]
        except Exception as e:  # noqa: BLE001
            out[label] = f"HIBA: {e}"
        print(f"{label}: {out[label]}", flush=True)
        time.sleep(2)

    if sample:
        print("\nMinta rekord kulcsai:", sorted(sample.keys()))
        print(json.dumps({k: (str(v)[:120] if v is not None else None) for k, v in sample.items()},
                         ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
