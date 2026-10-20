"""Beállítások betöltése a config.toml fájlból."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIPUSOK = ("cimke", "kulcsszo", "jogszabaly", "szerv")


@dataclass(frozen=True)
class Slice:
    """Egy forrásszelet (TERV 3.1): egy szűrővel meghatározott lekérdezés."""

    nev: str
    tipus: str
    ertek: str
    leiras: str = ""
    # Kollégium-szűrő a szerveren (TERV 3.1: alapból minden szeleten). A `probe`
    # parancs mutatja meg, hogy a szerver tényleg szűr-e vele; ha nem, utólag szűrünk.
    kollegium_szuro: bool = True


@dataclass
class Config:
    root: Path
    http: dict = field(default_factory=dict)
    harvest: dict = field(default_factory=dict)
    adatvedelem: dict = field(default_factory=dict)
    szeletek: list[Slice] = field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hatarozatok.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "config.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    szeletek: list[Slice] = []
    for i, s in enumerate(raw.get("szelet", []), start=1):
        try:
            sl = Slice(
                nev=s["nev"],
                tipus=s["tipus"],
                ertek=s["ertek"],
                leiras=s.get("leiras", ""),
                kollegium_szuro=bool(s.get("kollegium_szuro", True)),
            )
        except KeyError as e:
            raise ValueError(f"config.toml: a(z) {i}. [[szelet]] blokkból hiányzik: {e}") from e
        if sl.tipus not in TIPUSOK:
            raise ValueError(f"config.toml: ismeretlen szelettípus '{sl.tipus}' ({sl.nev}); "
                             f"lehetséges: {', '.join(TIPUSOK)}")
        szeletek.append(sl)

    nevek = [s.nev for s in szeletek]
    dupl = {n for n in nevek if nevek.count(n) > 1}
    if dupl:
        raise ValueError(f"config.toml: ismétlődő szeletnév: {', '.join(sorted(dupl))}")

    return Config(
        root=path.resolve().parent,
        http=raw.get("http", {}),
        harvest=raw.get("harvest", {}),
        adatvedelem=raw.get("adatvedelem", {}),
        szeletek=szeletek,
    )
