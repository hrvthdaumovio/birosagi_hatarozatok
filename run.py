"""Indító telepítés nélküli futtatáshoz (TERV F10):  python run.py <parancs> [opciók]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from hatarozat.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
