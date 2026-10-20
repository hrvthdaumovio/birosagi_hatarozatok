"""SQLite-séma és adatbázis-műveletek (TERV 5. fejezet).

Alapelv: semmit nem törlünk. Ha egy határozat eltűnik a forrásból, csak az
`utoljara_lattuk` mező nem frissül tovább.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .api import parse_api_date
from .util import birosag_szint, now_iso

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    kulcs TEXT PRIMARY KEY,
    ertek TEXT
);

CREATE TABLE IF NOT EXISTS hatarozat (
    egyedi_azonosito     TEXT PRIMARY KEY,
    azonosito            TEXT,
    index_id             TEXT,
    birosag              TEXT,
    birosag_szint        TEXT,
    kollegium            TEXT,
    jogterulet           TEXT,
    ev                   INTEGER,
    indexeles_ideje      TEXT,
    rezume               TEXT,
    jogszabalyhelyek_raw TEXT,
    kapcsolodo_raw       TEXT,
    nem_hivatkozhato     TEXT,
    raw_json             TEXT,
    elso_lattuk          TEXT NOT NULL,
    utoljara_lattuk      TEXT NOT NULL,
    rtf_path             TEXT,
    rtf_sha256           TEXT,
    letoltve_at          TEXT,
    szoveg               TEXT,
    hatokor              TEXT,
    hatokor_ok           TEXT,
    hatokor_modszer      TEXT
);
CREATE INDEX IF NOT EXISTS ix_hatarozat_indexeles ON hatarozat(indexeles_ideje);
CREATE INDEX IF NOT EXISTS ix_hatarozat_hatokor ON hatarozat(hatokor);

CREATE TABLE IF NOT EXISTS lekerdezes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nev               TEXT UNIQUE NOT NULL,
    tipus             TEXT NOT NULL,
    ertek             TEXT NOT NULL,
    utolso_count      INTEGER,
    utolso_egyedi     INTEGER,
    utolso_futas      TEXT,
    utolso_teljes     TEXT,
    utolso_megjegyzes TEXT
);

CREATE TABLE IF NOT EXISTS forras (
    egyedi_azonosito TEXT NOT NULL REFERENCES hatarozat(egyedi_azonosito),
    lekerdezes_id    INTEGER NOT NULL REFERENCES lekerdezes(id),
    elso_talalat     TEXT NOT NULL,
    utolso_talalat   TEXT NOT NULL,
    PRIMARY KEY (egyedi_azonosito, lekerdezes_id)
);

CREATE TABLE IF NOT EXISTS kapcsolat (
    egyedi_azonosito   TEXT NOT NULL REFERENCES hatarozat(egyedi_azonosito),
    kapcsolodo_ugyszam TEXT NOT NULL,
    kapcsolodo_birosag TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (egyedi_azonosito, kapcsolodo_ugyszam, kapcsolodo_birosag)
);

CREATE TABLE IF NOT EXISTS jogszabalyhely (
    egyedi_azonosito TEXT NOT NULL REFERENCES hatarozat(egyedi_azonosito),
    jogszabaly       TEXT NOT NULL,
    szakasz          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (egyedi_azonosito, jogszabaly, szakasz)
);

CREATE TABLE IF NOT EXISTS besorolas (
    egyedi_azonosito TEXT NOT NULL REFERENCES hatarozat(egyedi_azonosito),
    ugytipus         TEXT NOT NULL DEFAULT '',
    kimenetel        TEXT,
    modszer          TEXT,
    megbizhatosag    REAL,
    PRIMARY KEY (egyedi_azonosito, ugytipus)
);

CREATE TABLE IF NOT EXISTS futas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipus      TEXT NOT NULL,
    kezdet     TEXT NOT NULL,
    veg        TEXT,
    uj_rekord  INTEGER DEFAULT 0,
    letoltott  INTEGER DEFAULT 0,
    hibak      INTEGER DEFAULT 0,
    keresek    INTEGER DEFAULT 0,
    megjegyzes TEXT
);

CREATE TABLE IF NOT EXISTS kezi_ellenorzes (
    egyedi_azonosito TEXT NOT NULL REFERENCES hatarozat(egyedi_azonosito),
    mezo             TEXT NOT NULL,
    gepi_ertek       TEXT,
    kezi_ertek       TEXT,
    ellenorizte      TEXT,
    datum            TEXT,
    PRIMARY KEY (egyedi_azonosito, mezo)
);

CREATE VIRTUAL TABLE IF NOT EXISTS hatarozat_fts USING fts5(
    egyedi_azonosito UNINDEXED,
    rezume,
    szoveg,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""

FIELD_MAP = {  # API-mező -> oszlop
    "Azonosito": "azonosito",
    "IndexId": "index_id",
    "MeghozoBirosag": "birosag",
    "Kollegium": "kollegium",
    "JogTerulet": "jogterulet",
    "Rezume": "rezume",
    "NemHivatkozhatoSzoveg": "nem_hivatkozhato",
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO meta(kulcs, ertek) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def _text(v) -> str | None:
    """Lista/szótár mezők szöveggé alakítása (a mezők típusa az API-ban nem garantált)."""
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _int(v) -> int | None:
    try:
        return int(str(v).strip()[:4])
    except (TypeError, ValueError):
        return None


def record_to_row(item: dict) -> dict:
    row = {col: _text(item.get(api)) for api, col in FIELD_MAP.items()}
    row["egyedi_azonosito"] = str(item["EgyediAzonosito"])
    row["ev"] = _int(item.get("HatarozatEve"))
    row["indexeles_ideje"] = parse_api_date(item.get("IndexelesIdeje"))
    row["jogszabalyhelyek_raw"] = _text(item.get("Jogszabalyhelyek"))
    row["kapcsolodo_raw"] = _text(item.get("KapcsolodoHatarozatok"))
    row["birosag_szint"] = birosag_szint(row["birosag"])
    row["raw_json"] = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return row


UPSERT_SQL = """
INSERT INTO hatarozat (egyedi_azonosito, azonosito, index_id, birosag, birosag_szint, kollegium,
                       jogterulet, ev, indexeles_ideje, rezume, jogszabalyhelyek_raw, kapcsolodo_raw,
                       nem_hivatkozhato, raw_json, elso_lattuk, utoljara_lattuk)
VALUES (:egyedi_azonosito, :azonosito, :index_id, :birosag, :birosag_szint, :kollegium,
        :jogterulet, :ev, :indexeles_ideje, :rezume, :jogszabalyhelyek_raw, :kapcsolodo_raw,
        :nem_hivatkozhato, :raw_json, :most, :most)
ON CONFLICT(egyedi_azonosito) DO UPDATE SET
    azonosito = excluded.azonosito, index_id = excluded.index_id, birosag = excluded.birosag,
    birosag_szint = excluded.birosag_szint, kollegium = excluded.kollegium,
    jogterulet = excluded.jogterulet, ev = excluded.ev, indexeles_ideje = excluded.indexeles_ideje,
    rezume = excluded.rezume, jogszabalyhelyek_raw = excluded.jogszabalyhelyek_raw,
    kapcsolodo_raw = excluded.kapcsolodo_raw, nem_hivatkozhato = excluded.nem_hivatkozhato,
    raw_json = excluded.raw_json, utoljara_lattuk = excluded.utoljara_lattuk
"""


def upsert_records(conn: sqlite3.Connection, items: list[dict], lekerdezes_id: int,
                   most: str | None = None) -> int:
    """Rekordok beszúrása/frissítése + forrás-hozzárendelés. Visszaadja az új rekordok számát."""
    most = most or now_iso()
    uj = 0
    for item in items:
        row = record_to_row(item)
        exists = conn.execute("SELECT 1 FROM hatarozat WHERE egyedi_azonosito = ?",
                              (row["egyedi_azonosito"],)).fetchone()
        conn.execute(UPSERT_SQL, {**row, "most": most})
        if not exists:
            uj += 1
        conn.execute(
            """INSERT INTO forras (egyedi_azonosito, lekerdezes_id, elso_talalat, utolso_talalat)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(egyedi_azonosito, lekerdezes_id) DO UPDATE SET utolso_talalat = excluded.utolso_talalat""",
            (row["egyedi_azonosito"], lekerdezes_id, most, most))
        _upsert_kapcsolat(conn, row["egyedi_azonosito"], item.get("KapcsolodoHatarozatok"))
    return uj


def _upsert_kapcsolat(conn: sqlite3.Connection, eid: str, kapcsolodo) -> None:
    """KapcsolodoHatarozatok -> kapcsolat tábla. A mező formátuma nem dokumentált, ezért
    lista/szótár/szöveg esetén is megpróbáljuk értelmezni; a nyers érték a hatarozat táblában marad."""
    if not kapcsolodo:
        return
    elemek = kapcsolodo if isinstance(kapcsolodo, list) else [kapcsolodo]
    for e in elemek:
        if isinstance(e, dict):
            ugyszam = e.get("Azonosito") or e.get("Ugyszam") or e.get("ugyszam")
            birosag = e.get("MeghozoBirosag") or e.get("Birosag") or e.get("birosag") or ""
        else:
            ugyszam, birosag = str(e).strip(), ""
        if ugyszam:
            conn.execute("INSERT OR IGNORE INTO kapcsolat VALUES (?, ?, ?)", (eid, str(ugyszam), str(birosag)))


def get_or_create_lekerdezes(conn: sqlite3.Connection, nev: str, tipus: str, ertek: str) -> int:
    conn.execute("""INSERT INTO lekerdezes (nev, tipus, ertek) VALUES (?, ?, ?)
                    ON CONFLICT(nev) DO UPDATE SET tipus = excluded.tipus, ertek = excluded.ertek""",
                 (nev, tipus, ertek))
    return conn.execute("SELECT id FROM lekerdezes WHERE nev = ?", (nev,)).fetchone()["id"]


def update_lekerdezes(conn: sqlite3.Connection, lid: int, count: int, egyedi: int,
                      teljes: bool, megjegyzes: str = "") -> None:
    most = now_iso()
    conn.execute("""UPDATE lekerdezes SET utolso_count = ?, utolso_egyedi = ?, utolso_futas = ?,
                    utolso_teljes = CASE WHEN ? THEN ? ELSE utolso_teljes END, utolso_megjegyzes = ?
                    WHERE id = ?""", (count, egyedi, most, int(teljes), most, megjegyzes, lid))


def max_indexeles(conn: sqlite3.Connection, lid: int) -> str | None:
    """Az adott szelet által eddig látott legfrissebb publikálási időpont."""
    row = conn.execute("""SELECT MAX(h.indexeles_ideje) AS m FROM hatarozat h
                          JOIN forras f ON f.egyedi_azonosito = h.egyedi_azonosito
                          WHERE f.lekerdezes_id = ?""", (lid,)).fetchone()
    return row["m"] if row else None


def start_futas(conn: sqlite3.Connection, tipus: str) -> int:
    cur = conn.execute("INSERT INTO futas (tipus, kezdet) VALUES (?, ?)", (tipus, now_iso()))
    conn.commit()
    return cur.lastrowid


def finish_futas(conn: sqlite3.Connection, fid: int, **kw) -> None:
    cols = ", ".join(f"{k} = ?" for k in kw)
    conn.execute(f"UPDATE futas SET veg = ?{', ' if kw else ''}{cols} WHERE id = ?",
                 (now_iso(), *kw.values(), fid))
    conn.commit()
