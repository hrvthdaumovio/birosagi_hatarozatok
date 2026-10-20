"""Kisegítő függvények: idő, szövegnormalizálás, naplózás."""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def slugify(s: str | None, maxlen: int = 80) -> str:
    """Ékezet nélküli, kötőjeles név fájlútvonalhoz (TERV F6)."""
    s = strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:maxlen].rstrip("-") or "ismeretlen"


def birosag_szint(nev: str | None) -> str | None:
    """A bíróság nevéből a bírósági szint (TERV 7. fejezet, 1. pont)."""
    if not nev:
        return None
    n = strip_accents(nev).lower()
    if "kuria" in n:
        return "Kúria"
    if "itelotabla" in n:
        return "ítélőtábla"
    if "torvenyszek" in n:
        return "törvényszék"
    if "kozigazgatasi es munkaugyi" in n:
        return "közigazgatási és munkaügyi bíróság"
    if "jarasbirosag" in n or "keruleti birosag" in n:
        return "járásbíróság"
    return "egyéb"


def setup_logging(log_dir: Path, name: str, verbose: bool = False) -> logging.Logger:
    """Konzol + UTF-8 naplófájl (logs/<name>_<dátum>.log)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("hatarozat")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_dir / f"{name}_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(ch)
    return logger
