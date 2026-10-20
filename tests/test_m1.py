"""M1 egységtesztek – hálózat nélkül (TERV 10. fejezet).  Futtatás:  python -m unittest -v"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hatarozat import api, db  # noqa: E402
from hatarozat.config import Config, Slice, load_config  # noqa: E402
from hatarozat.harvest import FilterIgnored, Harvester  # noqa: E402
from hatarozat.sources import slice_to_spec, year_spec  # noqa: E402
from hatarozat.util import birosag_szint, slugify  # noqa: E402


def rec(i: int, ts: str = "2024-01-01T10:00:00", **kw) -> dict:
    r = {"EgyediAzonosito": f"E{i:05d}", "Azonosito": f"{i}.K.700/2024/5", "IndexId": f"idx{i}",
         "MeghozoBirosag": "Fővárosi Törvényszék", "Kollegium": "közigazgatási",
         "JogTerulet": "közigazgatási jog", "HatarozatEve": "2024", "IndexelesIdeje": ts,
         "Jogszabalyhelyek": "2007. évi II. törvény 43. §", "KapcsolodoHatarozatok": None,
         "Rezume": "", "NemHivatkozhatoSzoveg": None, "Szoveg": None, "DownloadLink": None}
    r.update(kw)
    return r


class FakeClient:
    """A Client.search/count viselkedését utánozza egy rögzített rekordlistán.
    `drop_ascending`: növekvő rendezésnél ezeket az indexeket kihagyja (instabil lapozás szimulálása)."""

    def __init__(self, records, baseline=100000, drop_ascending=()):
        self.records = records
        self.baseline_count = baseline
        self.drop = set(drop_ascending)
        self.requests_made = 0
        self.calls = []

    def search(self, spec, start=0, count=100, kodolas=None):
        self.requests_made += 1
        self.calls.append((dict(spec.scalars), start, count))
        if not any(k in spec.scalars for k in ("HierarchikusPertargy", "KeresoSzo", "ErintettKozigazgatsaiSzerv")) \
                and not spec.keresoszavak and not spec.jogszabalyhelyek:
            return api.SearchResult(self.baseline_count, [])
        recs = self.records
        ev = spec.scalars.get("MeghozatalIdejeTol")
        if ev:
            recs = [r for r in recs if r["HatarozatEve"] == ev]
        asc = spec.scalars.get("Rendezes") == "IndexelesIdejeNovekvo"
        recs = sorted(recs, key=lambda r: r["IndexelesIdeje"], reverse=not asc)
        if asc and self.drop:
            # Instabil lapozás: a kihagyott elemek helyén ismétlődés jelenik meg.
            recs = [recs[i - 1] if i in self.drop else r for i, r in enumerate(recs)]
        return api.SearchResult(len(self.records) if not ev else len(recs), recs[start:start + count])

    def count(self, spec, kodolas=None):
        return self.search(spec, 0, 1).count


def make_cfg(tmp: Path, **harvest) -> Config:
    return Config(root=tmp, http={}, harvest={"kollegium": "közigazgatási", "nem_hivatkozhato": "igen",
                                              "page_size": 10, "ev_tol": 2020, **harvest})


class TestUtil(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Fővárosi Törvényszék"), "fovarosi-torvenyszek")
        self.assertEqual(slugify(""), "ismeretlen")

    def test_birosag_szint(self):
        self.assertEqual(birosag_szint("Kúria"), "Kúria")
        self.assertEqual(birosag_szint("Fővárosi Ítélőtábla"), "ítélőtábla")
        self.assertEqual(birosag_szint("Debreceni Közigazgatási és Munkaügyi Bíróság"),
                         "közigazgatási és munkaügyi bíróság")
        self.assertEqual(birosag_szint("Budai Központi Kerületi Bíróság"), "járásbíróság")


class TestApi(unittest.TestCase):
    def test_build_form_jquery(self):
        spec = api.SearchSpec({"Kollegium": "közigazgatási"}, [("kiutasítás", "Pontos")],
                              [{"GyakoriJogszabalyId": "abc", "JogszabalyHivatkozas": ""}])
        form = dict(api.build_form(spec, "jquery"))
        self.assertEqual(form["Kollegium"], "közigazgatási")
        self.assertEqual(form["KeresoSzavak[]"], "kiutasítás")
        self.assertEqual(form["KeresoSzoOperatorok[]"], "Pontos")
        self.assertEqual(form["JogszabalyHelyek[0][GyakoriJogszabalyId]"], "abc")
        self.assertEqual(form["Rendezes"], "IndexelesIdejeNovekvo")

    def test_build_form_mvc(self):
        spec = api.SearchSpec({}, [("a", "Osszes"), ("b", "Pontos")], [{"GyakoriJogszabalyId": "x"}])
        form = api.build_form(spec, "mvc")
        self.assertEqual([v for k, v in form if k == "KeresoSzavak"], ["a", "b"])
        self.assertIn(("JogszabalyHelyek[0].GyakoriJogszabalyId", "x"), form)

    def test_build_json(self):
        body = api.build_json(api.SearchSpec({}, [("a", "Pontos")]))
        self.assertEqual(body["KeresoSzavak"], ["a"])
        self.assertEqual(body["KeresoSzoOperatorok"], ["Pontos"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            api.build_form(api.SearchSpec({"Kollégium": "x"}))  # ékezetes kulcs (régi scraper hibája)
        with self.assertRaises(ValueError):
            api.build_form(api.SearchSpec({"Rendezes": "rossz"}))
        with self.assertRaises(ValueError):
            api.build_form(api.SearchSpec({}, [("a", "Rossz")]))

    def test_parse_api_date(self):
        self.assertEqual(api.parse_api_date("2024-03-01T12:00:00"), "2024-03-01T12:00:00")
        self.assertEqual(api.parse_api_date("/Date(0)/"), "1970-01-01T00:00:00+00:00")
        self.assertIsNone(api.parse_api_date(None))

    def test_filename(self):
        self.assertEqual(api._filename("attachment; filename*=UTF-8''hat%C3%A1rozat.rtf"), "határozat.rtf")
        self.assertEqual(api._filename('attachment; filename="a.rtf"'), "a.rtf")

    def test_search_schema_error(self):
        sess = mock.Mock()
        ok = mock.Mock(status_code=200)
        bad = mock.Mock(status_code=200)
        bad.json.return_value = {"valami": 1}
        sess.get.return_value = ok
        sess.request.return_value = bad
        sess.headers = {}
        c = api.Client({"list_delay_s": [0, 0], "contact": "x@y.hu"}, session=sess)
        with self.assertRaises(api.SchemaError):
            c.search(api.SearchSpec())


class TestSources(unittest.TestCase):
    def test_slice_to_spec(self):
        h = {"kollegium": "közigazgatási", "nem_hivatkozhato": "igen", "kulcsszo_mod": "operator"}
        s = slice_to_spec(Slice("a", "cimke", "X/Y"), h)
        self.assertEqual(s.scalars["HierarchikusPertargy"], "X/Y")
        self.assertEqual(s.scalars["Kollegium"], "közigazgatási")
        s = slice_to_spec(Slice("b", "kulcsszo", "kiutasítás"), h)
        self.assertEqual(s.keresoszavak, [("kiutasítás", "Pontos")])
        s = slice_to_spec(Slice("c", "kulcsszo", "kiutasítás"), {**h, "kulcsszo_mod": "egyszeru"})
        self.assertEqual(s.scalars["KeresoSzo"], "kiutasítás")
        s = slice_to_spec(Slice("d", "jogszabaly", "guid", kollegium_szuro=False), h)
        self.assertEqual(s.jogszabalyhelyek[0]["GyakoriJogszabalyId"], "guid")
        self.assertNotIn("Kollegium", s.scalars)
        y = year_spec(s, 2021)
        self.assertEqual((y.scalars["MeghozatalIdejeTol"], y.scalars["MeghozatalIdejeIg"]), ("2021", "2021"))

    def test_config_file(self):
        cfg = load_config(ROOT / "config.toml")
        self.assertTrue(cfg.szeletek)
        self.assertNotIn("Menedékjog", " ".join(s.ertek for s in cfg.szeletek))  # hatókör-döntés


class TestDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_upsert_idempotent(self):
        lid = db.get_or_create_lekerdezes(self.conn, "s", "cimke", "X")
        self.assertEqual(db.upsert_records(self.conn, [rec(1), rec(2)], lid), 2)
        self.assertEqual(db.upsert_records(self.conn, [rec(1, Rezume="új")], lid), 0)
        row = self.conn.execute("SELECT * FROM hatarozat WHERE egyedi_azonosito='E00001'").fetchone()
        self.assertEqual(row["rezume"], "új")
        self.assertEqual(row["birosag_szint"], "törvényszék")
        self.assertEqual(row["ev"], 2024)
        self.assertIn('"EgyediAzonosito"', row["raw_json"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM forras").fetchone()[0], 2)

    def test_kapcsolat_formats(self):
        lid = db.get_or_create_lekerdezes(self.conn, "s", "cimke", "X")
        db.upsert_records(self.conn, [
            rec(1, KapcsolodoHatarozatok=[{"Azonosito": "Kfv.1/2024", "MeghozoBirosag": "Kúria"}]),
            rec(2, KapcsolodoHatarozatok=["3.K.1/2023"]),
            rec(3, KapcsolodoHatarozatok="4.K.2/2023"),
        ], lid)
        rows = self.conn.execute("SELECT * FROM kapcsolat ORDER BY egyedi_azonosito").fetchall()
        self.assertEqual([(r[0], r[1], r[2]) for r in rows],
                         [("E00001", "Kfv.1/2024", "Kúria"), ("E00002", "3.K.1/2023", ""),
                          ("E00003", "4.K.2/2023", "")])

    def test_fts5(self):
        self.conn.execute("INSERT INTO hatarozat_fts VALUES ('E1', '', 'idegenrendészeti őrizet elrendelése')")
        n = self.conn.execute("SELECT COUNT(*) FROM hatarozat_fts WHERE hatarozat_fts MATCH 'orizet'").fetchone()[0]
        self.assertEqual(n, 1)  # ékezet nélküli keresés is talál


class TestHarvest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.conn = db.connect(self.path / "t.db")
        self.sl = Slice("teszt", "cimke", "X")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _records(self, n):
        return [rec(i, f"2024-01-{1 + i % 28:02d}T{i % 24:02d}:00:00") for i in range(n)]

    def test_full_complete(self):
        fc = FakeClient(self._records(35))
        rep = Harvester(fc, self.conn, make_cfg(self.path)).harvest_full(self.sl)
        self.assertEqual((rep.count, rep.egyedi, rep.uj, rep.teljes), (35, 35, 35, True))

    def test_unstable_paging_second_pass(self):
        fc = FakeClient(self._records(35), drop_ascending={5, 17, 30})
        rep = Harvester(fc, self.conn, make_cfg(self.path)).harvest_full(self.sl)
        self.assertTrue(rep.teljes, rep.sor())
        self.assertEqual(rep.egyedi, 35)
        self.assertTrue(any("2. menet" in m for m in rep.megjegyzes))

    def test_filter_ignored(self):
        fc = FakeClient(self._records(35), baseline=35)
        with self.assertRaises(FilterIgnored):
            Harvester(fc, self.conn, make_cfg(self.path)).harvest_full(self.sl)

    def test_incremental_stops_early(self):
        recs = self._records(60)
        fc = FakeClient(recs[:50])
        h = Harvester(fc, self.conn, make_cfg(self.path, atfedes_napok=0))
        h.harvest_full(self.sl)
        uj = [rec(1000 + i, f"2025-06-0{i + 1}T00:00:00") for i in range(3)]
        fc.records = recs[:50] + uj
        fc.calls.clear()
        rep = h.harvest_incremental(self.sl)
        self.assertEqual(rep.uj, 3)
        lapok = [c for c in fc.calls if c[2] == 10]
        self.assertLessEqual(len(lapok), 2)  # nem lapozza végig mind a 6 oldalt


if __name__ == "__main__":
    unittest.main()
