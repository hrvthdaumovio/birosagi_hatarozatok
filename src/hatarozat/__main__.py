"""Parancssori belépési pont.

    python run.py harvest --full            # teljes metaadat-gyűjtés (M1)
    python run.py harvest                   # inkrementális frissítés
    python run.py harvest --full --csak cimke_fo
    python run.py status                    # adatbázis-összesítő
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import load_config
from .util import setup_logging


def _reconfigure_stdout() -> None:
    # A Windows-konzol (cp1252) eltorzítja az ékezeteket (TERV 4. fejezet).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def cmd_harvest(args, cfg) -> int:
    from . import db
    from .api import Client, SchemaError, TooManyErrors
    from .harvest import run_harvest

    log = setup_logging(cfg.log_dir, "harvest", args.verbose)
    conn = db.connect(cfg.db_path)
    client = Client(cfg.http, kodolas=cfg.harvest.get("kodolas", "jquery"))
    log.info("Gyűjtés indul (%s), adatbázis: %s", "teljes" if args.full else "inkrementális", cfg.db_path)
    try:
        reports = run_harvest(client, conn, cfg, full=args.full, csak=args.csak)
    except (TooManyErrors, SchemaError) as e:
        log.error("A futás leállt: %s", e)
        return 2
    except KeyboardInterrupt:
        log.warning("Megszakítva. A már lekért adatok el vannak mentve; az újraindítás folytatja.")
        return 130
    finally:
        conn.close()

    log.info("Összesítő:")
    for r in reports:
        log.info("  %s", r.sor())
    hianyos = [r.nev for r in reports if r.teljes is False]
    if hianyos:
        log.warning("Hiányos vagy hibás szeletek: %s", ", ".join(hianyos))
    log.info("HTTP-kérések száma: %s", client.requests_made)
    return 1 if hianyos else 0


def cmd_status(args, cfg) -> int:
    from . import db

    if not cfg.db_path.exists():
        print("Még nincs adatbázis. Futtassa: python run.py harvest --full")
        return 0
    conn = db.connect(cfg.db_path)
    q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
    n = q("SELECT COUNT(*) AS n FROM hatarozat")[0]["n"]
    print(f"Határozatok (egyedi): {n}")
    print("\nSzeletek:")
    print(f"  {'név':<30} {'Count':>6} {'egyedi':>7} {'adatbázisban':>13}  utolsó futás")
    for r in q("""SELECT l.nev, l.utolso_count, l.utolso_egyedi, l.utolso_futas, l.utolso_megjegyzes,
                         (SELECT COUNT(*) FROM forras f WHERE f.lekerdezes_id = l.id) AS db_n
                  FROM lekerdezes l ORDER BY l.id"""):
        print(f"  {r['nev']:<30} {r['utolso_count'] or 0:>6} {r['utolso_egyedi'] or 0:>7} {r['db_n']:>13}  "
              f"{(r['utolso_futas'] or '')[:19]}  {r['utolso_megjegyzes'] or ''}")
    print("\nKollégium szerint:")
    for r in q("SELECT COALESCE(kollegium, '?') AS k, COUNT(*) AS n FROM hatarozat GROUP BY k ORDER BY n DESC"):
        print(f"  {r['k']:<20} {r['n']:>6}")
    print("\nBírósági szint szerint:")
    for r in q("SELECT COALESCE(birosag_szint, '?') AS k, COUNT(*) AS n FROM hatarozat GROUP BY k ORDER BY n DESC"):
        print(f"  {r['k']:<36} {r['n']:>6}")
    print("\nCsak egy szeletből jött rekordok (szeletenként):")
    for r in q("""SELECT l.nev, COUNT(*) AS n FROM forras f JOIN lekerdezes l ON l.id = f.lekerdezes_id
                  WHERE f.egyedi_azonosito IN (SELECT egyedi_azonosito FROM forras
                                               GROUP BY egyedi_azonosito HAVING COUNT(*) = 1)
                  GROUP BY l.nev ORDER BY n DESC"""):
        print(f"  {r['nev']:<30} {r['n']:>6}")
    rng = q("SELECT MIN(indexeles_ideje) AS a, MAX(indexeles_ideje) AS b FROM hatarozat")[0]
    print(f"\nPublikálás: {(rng['a'] or '')[:10]} – {(rng['b'] or '')[:10]}")
    print("\nUtolsó futások:")
    for r in q("SELECT * FROM futas ORDER BY id DESC LIMIT 5"):
        print(f"  #{r['id']} {r['tipus']:<13} {r['kezdet'][:19]} – {(r['veg'] or 'fut/megszakadt')[:19]}  "
              f"új={r['uj_rekord']} hibák={r['hibak']} kérések={r['keresek']}")
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdout()
    p = argparse.ArgumentParser(prog="hatarozat", description="Idegenrendészeti határozatok gyűjtése")
    p.add_argument("--config", help="config.toml útvonala (alapértelmezés: a projekt gyökerében)")
    p.add_argument("-v", "--verbose", action="store_true", help="részletes napló a konzolon")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ph = sub.add_parser("harvest", help="metaadatok gyűjtése a forrásszeletekből")
    ph.add_argument("--full", action="store_true", help="teljes gyűjtés (különben inkrementális)")
    ph.add_argument("--csak", nargs="+", metavar="SZELET", help="csak a megadott szeletek")
    ph.set_defaults(func=cmd_harvest)

    ps = sub.add_parser("status", help="adatbázis-összesítő")
    ps.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
