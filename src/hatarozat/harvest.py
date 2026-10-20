"""Metaadat-gyűjtés a forrásszeletekből: teljes és inkrementális mód (TERV 6. fejezet, F1/F2)."""
from __future__ import annotations

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import db
from .api import COUNT_CAP, Client, SchemaError, SearchSpec, TooManyErrors, parse_api_date
from .config import Config, Slice
from .sources import slice_to_spec, year_spec

log = logging.getLogger("hatarozat")


class FilterIgnored(RuntimeError):
    """A szelet szűrőjét a szerver figyelmen kívül hagyta (a találatszám megegyezik a szűretlennel).
    Ilyenkor a szeletet kihagyjuk, különben a teljes adatbázist tükröznénk."""


@dataclass
class SliceReport:
    nev: str
    count: int = 0
    egyedi: int = 0
    uj: int = 0
    keresek: int = 0
    teljes: bool | None = False   # None: darabszámmal nem ellenőrizhető (10 000-es plafon)
    megjegyzes: list[str] = field(default_factory=list)

    def sor(self) -> str:
        allapot = {True: "OK", False: "HIÁNYOS", None: "NEM ELLENŐRIZHETŐ"}[self.teljes]
        megj = ("; " + "; ".join(self.megjegyzes)) if self.megjegyzes else ""
        return (f"{self.nev:<30} Count={self.count:>6}  egyedi={self.egyedi:>6}  új={self.uj:>5}  "
                f"kérés={self.keresek:>4}  {allapot}{megj}")


class Harvester:
    def __init__(self, client: Client, conn: sqlite3.Connection, cfg: Config):
        self.client = client
        self.conn = conn
        self.cfg = cfg
        self.page_size = int(cfg.harvest.get("page_size", 100))
        self._baseline: dict[bool, int] = {}

    def _baseline_spec(self, kollegium_szuro: bool) -> SearchSpec:
        scalars = {"NemHivatkozhato": self.cfg.harvest.get("nem_hivatkozhato", "igen")}
        if kollegium_szuro and self.cfg.harvest.get("kollegium"):
            scalars["Kollegium"] = self.cfg.harvest["kollegium"]
        return SearchSpec(scalars)

    def baseline(self, kollegium_szuro: bool) -> int:
        """Szűretlen találatszám (ugyanazzal a kollégium- és hivatkozhatóság-beállítással)."""
        if kollegium_szuro not in self._baseline:
            self._baseline[kollegium_szuro] = self.client.count(self._baseline_spec(kollegium_szuro))
        return self._baseline[kollegium_szuro]

    def _guard(self, sl: Slice, spec: SearchSpec) -> int:
        """Biztonsági ellenőrzés letöltés előtt: működik-e a szelet szűrője.
        Ha mindkét szám a 10 000-es plafonon van, egy évre szűkítve hasonlítunk (különben a
        jogosan nagy szeleteket tévesen hatástalannak minősítenénk, és az F1-bontás sosem futna le)."""
        c = self.client.count(spec.with_scalars(Rendezes="IndexelesIdejeNovekvo"))
        alap = self.baseline(sl.kollegium_szuro)
        if c < alap:
            return c
        if c >= COUNT_CAP and alap >= COUNT_CAP:
            ev = date.today().year - 1
            c_ev = self.client.count(year_spec(spec, ev))
            alap_ev = self.client.count(year_spec(self._baseline_spec(sl.kollegium_szuro), ev))
            if c_ev < alap_ev:
                return c
            raise FilterIgnored(f"a szűrő hatástalan ({ev}: {c_ev} = szűretlen {alap_ev}) – a szelet kimarad")
        raise FilterIgnored(f"a szűrő hatástalan (Count={c}, szűretlen={alap}) – a szelet kimarad")

    # -- lapozás ------------------------------------------------------------
    def _page_all(self, spec: SearchSpec, rendezes: str, lid: int, rep: SliceReport,
                  seen: set[str], stop_before: str | None = None) -> int:
        """Egy keresés összes oldalának lekérése és mentése. Visszaadja a szerver Count értékét.
        `stop_before`: csökkenő rendezésnél megáll, ha a rekordok ennél régebbiek (inkrementális mód)."""
        spec = spec.with_scalars(Rendezes=rendezes)
        start, count, max_pages = 0, None, None
        page = 0
        while True:
            res = self.client.search(spec, start=start, count=self.page_size)
            rep.keresek += 1
            page += 1
            if count is None:
                count = res.count
                max_pages = math.ceil(min(count, COUNT_CAP) / self.page_size) + 1
            rep.uj += db.upsert_records(self.conn, res.items, lid)
            self.conn.commit()
            for it in res.items:
                seen.add(str(it["EgyediAzonosito"]))
            log.debug("  %s oldal %s: %s tétel (start=%s, Count=%s)", rendezes, page, len(res.items), start, count)

            if stop_before and res.items:
                legregebbi = min((parse_api_date(it.get("IndexelesIdeje")) or "") for it in res.items)
                if legregebbi and legregebbi[:19] < stop_before:
                    break
            if len(res.items) < self.page_size:
                break
            start += self.page_size
            if start >= min(count, COUNT_CAP) or page >= max_pages:
                break
        return count or 0

    # -- teljes gyűjtés -----------------------------------------------------
    def harvest_full(self, sl: Slice) -> SliceReport:
        rep = SliceReport(sl.nev)
        lid = db.get_or_create_lekerdezes(self.conn, sl.nev, sl.tipus, sl.ertek)
        spec = slice_to_spec(sl, self.cfg.harvest)
        seen: set[str] = set()
        self._guard(sl, spec)

        count = self._page_all(spec, "IndexelesIdejeNovekvo", lid, rep, seen)
        rep.count = count
        if count >= COUNT_CAP:
            rep.megjegyzes.append(f"Count ≥ {COUNT_CAP}: évenkénti bontás")
            log.warning("%s: a találatszám eléri a %s-es plafont – évenkénti bontás (TERV F1)", sl.nev, COUNT_CAP)
            self._harvest_by_year(spec, lid, rep, seen)
        elif len(seen) < count:
            hiany = count - len(seen)
            log.warning("%s: %s rekord hiányzik növekvő rendezéssel – második menet csökkenő rendezéssel (TERV F2)",
                        sl.nev, hiany)
            self._page_all(spec, "IndexelesIdejeCsokkeno", lid, rep, seen)
            rep.megjegyzes.append(f"2. menet (hiány: {hiany} -> {max(0, count - len(seen))})")
            if len(seen) < count:
                log.warning("%s: még mindig hiányos – évenkénti bontás", sl.nev)
                self._harvest_by_year(spec, lid, rep, seen)

        rep.egyedi = len(seen)
        rep.teljes = None if count >= COUNT_CAP else rep.egyedi >= count
        db.update_lekerdezes(self.conn, lid, count, rep.egyedi, teljes=bool(rep.teljes),
                             megjegyzes="; ".join(rep.megjegyzes))
        self.conn.commit()
        return rep

    def _harvest_by_year(self, spec: SearchSpec, lid: int, rep: SliceReport, seen: set[str]) -> None:
        ev_tol = int(self.cfg.harvest.get("ev_tol", 1990))
        osszes_eves = 0
        for ev in range(date.today().year, ev_tol - 1, -1):
            yspec = year_spec(spec, ev)
            elotte = len(seen)
            c = self._page_all(yspec, "IndexelesIdejeNovekvo", lid, rep, seen)
            if c and len(seen) - elotte < c:
                self._page_all(yspec, "IndexelesIdejeCsokkeno", lid, rep, seen)
            if c >= COUNT_CAP:
                rep.megjegyzes.append(f"{ev}: egy évben is ≥ {COUNT_CAP} – tovább kell bontani")
                log.error("%s: %s évben is eléri a plafont – a szeletet tovább kell szűkíteni", rep.nev, ev)
            osszes_eves += c
        if rep.count < COUNT_CAP and osszes_eves < rep.count:
            rep.megjegyzes.append(f"évek összege {osszes_eves} < Count {rep.count} (év nélküli rekordok?)")

    # -- inkrementális gyűjtés ---------------------------------------------
    def harvest_incremental(self, sl: Slice) -> SliceReport:
        lid = db.get_or_create_lekerdezes(self.conn, sl.nev, sl.tipus, sl.ertek)
        legutobbi = db.max_indexeles(self.conn, lid)
        if not legutobbi:
            log.info("%s: még nincs adat – teljes gyűjtés", sl.nev)
            return self.harvest_full(sl)

        napok = int(self.cfg.harvest.get("atfedes_napok", 7))
        try:
            hatar = (datetime.fromisoformat(legutobbi[:19]) - timedelta(days=napok)).isoformat(timespec="seconds")
        except ValueError:
            log.warning("%s: értelmezhetetlen dátum (%s) – teljes gyűjtés", sl.nev, legutobbi)
            return self.harvest_full(sl)

        rep = SliceReport(sl.nev)
        spec = slice_to_spec(sl, self.cfg.harvest)
        seen: set[str] = set()
        self._guard(sl, spec)
        rep.count = self._page_all(spec, "IndexelesIdejeCsokkeno", lid, rep, seen, stop_before=hatar)
        rep.egyedi = len(seen)
        rep.teljes = True
        rep.megjegyzes.append(f"inkrementális, határ: {hatar}")
        osszes = self.conn.execute("SELECT COUNT(*) AS n FROM forras WHERE lekerdezes_id = ?", (lid,)).fetchone()["n"]
        if osszes < rep.count:
            rep.megjegyzes.append(f"az adatbázisban {osszes} < Count {rep.count}: heti teljes egyeztetés javasolt")
        db.update_lekerdezes(self.conn, lid, rep.count, osszes, teljes=False, megjegyzes="; ".join(rep.megjegyzes))
        self.conn.commit()
        return rep


def run_harvest(client: Client, conn: sqlite3.Connection, cfg: Config, full: bool,
                csak: list[str] | None = None) -> list[SliceReport]:
    szeletek = [s for s in cfg.szeletek if not csak or s.nev in csak]
    if csak:
        ismeretlen = set(csak) - {s.nev for s in cfg.szeletek}
        if ismeretlen:
            raise ValueError(f"Ismeretlen szelet(ek): {', '.join(sorted(ismeretlen))}")

    fid = db.start_futas(conn, "harvest-full" if full else "harvest")
    h = Harvester(client, conn, cfg)
    reports: list[SliceReport] = []
    hibak = 0
    try:
        for sl in szeletek:
            log.info("Szelet: %s (%s: %s)", sl.nev, sl.tipus, sl.ertek)
            try:
                rep = h.harvest_full(sl) if full else h.harvest_incremental(sl)
            except (TooManyErrors, SchemaError):
                raise
            except Exception as e:  # noqa: BLE001 – egy szelet hibája ne állítsa le a többit
                hibak += 1
                log.error("%s: hiba – %s", sl.nev, e)
                rep = SliceReport(sl.nev, megjegyzes=[f"HIBA: {e}"])
            reports.append(rep)
            log.info("  %s", rep.sor())
    finally:
        db.finish_futas(conn, fid, uj_rekord=sum(r.uj for r in reports), hibak=hibak,
                        keresek=client.requests_made,
                        megjegyzes=" | ".join(r.sor() for r in reports))
    return reports
