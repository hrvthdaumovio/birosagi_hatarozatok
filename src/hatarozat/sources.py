"""Forrásszeletek (TERV 3.1) leképezése keresési paraméterekre."""
from __future__ import annotations

from .api import SearchSpec
from .config import Slice


def slice_to_spec(sl: Slice, harvest_cfg: dict) -> SearchSpec:
    """Egy szelet -> SearchSpec. A rendezést és a lapozást a hívó állítja be."""
    scalars: dict[str, str] = {
        "NemHivatkozhato": harvest_cfg.get("nem_hivatkozhato", "igen"),
    }
    if sl.kollegium_szuro and harvest_cfg.get("kollegium"):
        scalars["Kollegium"] = harvest_cfg["kollegium"]

    spec = SearchSpec(scalars)
    if sl.tipus == "cimke":
        spec.scalars["HierarchikusPertargy"] = sl.ertek
    elif sl.tipus == "kulcsszo":
        if harvest_cfg.get("kulcsszo_mod", "operator") == "operator":
            spec.keresoszavak.append((sl.ertek, "Pontos"))
        else:
            spec.scalars["KeresoSzo"] = sl.ertek
    elif sl.tipus == "jogszabaly":
        spec.jogszabalyhelyek.append({
            "GyakoriJogszabalyId": sl.ertek,
            "JogszabalyHivatkozas": "",
            "JogszabalyIdejeTol": "",
            "JogszabalyIdejeIg": "",
        })
    elif sl.tipus == "szerv":
        spec.scalars["ErintettKozigazgatsaiSzerv"] = sl.ertek
    else:  # a config.py már ellenőrzi
        raise ValueError(f"ismeretlen szelettípus: {sl.tipus}")
    return spec


def year_spec(spec: SearchSpec, ev: int) -> SearchSpec:
    """Évre szűkített változat (10 000-es plafon és hiányos lapozás esetére, TERV F1/F2)."""
    return spec.with_scalars(MeghozatalIdejeTol=str(ev), MeghozatalIdejeIg=str(ev))
