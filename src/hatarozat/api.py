"""HTTP-kliens az eakta.birosag.hu anonimizált határozatkeresőjéhez.

Kíméletes működés (TERV 6. fejezet): egyetlen kapcsolat, véletlenített szünetek,
exponenciális visszalépés 429/5xx/időtúllépés esetén, leállás sok egymás utáni hiba után.
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote

import requests

from . import __version__

log = logging.getLogger("hatarozat")

SEARCH_PATH = "/AnonimizaltHatarozat/Search"
DOWNLOAD_PATH = "/AnonimizaltHatarozat/DownloadHatarozatMobile"
SEARCH_PAGE = "/anonimizalt-hatarozatok"
COUNT_CAP = 10000  # a szerver ennél nagyobb találatszámot nem jelez (TERV 1. fejezet)

REQUIRED_FIELDS = ("EgyediAzonosito", "Azonosito", "IndexId", "MeghozoBirosag")

# A felület által küldött összes skalármező, üres alapértékkel (a mentett oldal JS-e alapján).
BASE_FORM: dict[str, str] = {
    "ResultCount": "1",
    "ResultStartIndex": "0",
    "KeresoSzo": "",
    "Rezume": "",
    "JogTerulet": "",
    "MeghozoBirosag": "",
    "ErintettKozigazgatsaiSzerv": "",  # sic, a szerver így várja
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
    "Rendezes": "IndexelesIdejeNovekvo",
    "HierarchikusPertargy": "",
    "NemHivatkozhato": "igen",
}

RENDEZES = ("BirosagiSzint", "HatarozatEveCsokkeno", "HatarozatEveNovekvo",
            "IndexelesIdejeCsokkeno", "IndexelesIdejeNovekvo")
OPERATOROK = ("Osszes", "Kifejezes", "Pontos")


class ApiError(RuntimeError):
    """Nem helyreállítható API-hiba."""


class SchemaError(ApiError):
    """A válasz szerkezete eltér a várttól – az API valószínűleg megváltozott (TERV 11)."""


class TooManyErrors(ApiError):
    """Túl sok egymás utáni hiba – a futás leáll, hogy ne terheljük a szervert."""


@dataclass
class SearchSpec:
    """Egy keresés paraméterei a lapozástól függetlenül."""

    scalars: dict[str, str] = field(default_factory=dict)
    keresoszavak: list[tuple[str, str]] = field(default_factory=list)   # (szó, operátor)
    jogszabalyhelyek: list[dict[str, str]] = field(default_factory=list)

    def with_scalars(self, **kw: str) -> "SearchSpec":
        return SearchSpec({**self.scalars, **kw}, list(self.keresoszavak),
                          [dict(j) for j in self.jogszabalyhelyek])


KODOLASOK = ("jquery", "mvc", "json")


def _validate(spec: SearchSpec) -> None:
    unknown = set(spec.scalars) - set(BASE_FORM)
    if unknown:
        raise ValueError(f"ismeretlen keresési mező(k): {', '.join(sorted(unknown))}")
    rendezes = spec.scalars.get("Rendezes", BASE_FORM["Rendezes"])
    if rendezes not in RENDEZES:
        raise ValueError(f"ismeretlen rendezés: {rendezes}")
    for _, op in spec.keresoszavak:
        if op not in OPERATOROK:
            raise ValueError(f"ismeretlen operátor: {op}")


def build_form(spec: SearchSpec, kodolas: str = "jquery") -> list[tuple[str, str]]:
    """Form-data összeállítása. A tömbök kódolása:
    - "jquery": KeresoSzavak[]=…, JogszabalyHelyek[0][Mezo]=… (jQuery $.param alapértelmezés)
    - "mvc":    KeresoSzavak=… (ismételve), JogszabalyHelyek[0].Mezo=…
    """
    if kodolas not in ("jquery", "mvc"):
        raise ValueError(f"ismeretlen form-kódolás: {kodolas}")
    _validate(spec)
    form = [(k, str(v)) for k, v in {**BASE_FORM, **spec.scalars}.items()]
    arr = "[]" if kodolas == "jquery" else ""
    for szo, _ in spec.keresoszavak:
        form.append((f"KeresoSzavak{arr}", szo))
    for _, op in spec.keresoszavak:
        form.append((f"KeresoSzoOperatorok{arr}", op))
    for i, jh in enumerate(spec.jogszabalyhelyek):
        for k, v in jh.items():
            key = f"JogszabalyHelyek[{i}][{k}]" if kodolas == "jquery" else f"JogszabalyHelyek[{i}].{k}"
            form.append((key, "" if v is None else str(v)))
    return form


def build_json(spec: SearchSpec) -> dict:
    """JSON-törzs (tartalék kódolás, ha a szerver a form-tömböket nem köti meg)."""
    _validate(spec)
    body: dict = {**BASE_FORM, **spec.scalars}
    if spec.keresoszavak:
        body["KeresoSzavak"] = [s for s, _ in spec.keresoszavak]
        body["KeresoSzoOperatorok"] = [o for _, o in spec.keresoszavak]
    if spec.jogszabalyhelyek:
        body["JogszabalyHelyek"] = [{k: (v or None) for k, v in j.items()} for j in spec.jogszabalyhelyek]
    return body


def parse_api_date(value) -> str | None:
    """API-dátum -> ISO 8601 szöveg. Kezeli az ISO formát és az ASP.NET `/Date(ms)/` formát."""
    if value in (None, ""):
        return None
    s = str(value)
    m = re.match(r"^/Date\((-?\d+)([+-]\d{4})?\)/$", s)
    if m:
        dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        return dt.isoformat(timespec="seconds")
    return s


@dataclass
class SearchResult:
    count: int
    items: list[dict]


@dataclass
class Document:
    content: bytes
    content_type: str
    filename: str | None


class Client:
    def __init__(self, http_cfg: dict, kodolas: str = "jquery", session: requests.Session | None = None):
        self.base = http_cfg.get("base_url", "https://eakta.birosag.hu").rstrip("/")
        self.list_delay = tuple(http_cfg.get("list_delay_s", (2.0, 3.0)))
        self.doc_delay = tuple(http_cfg.get("doc_delay_s", (3.0, 4.5)))
        self.timeout = float(http_cfg.get("timeout_s", 30))
        self.max_retries = int(http_cfg.get("max_retries", 5))
        self.max_consecutive = int(http_cfg.get("max_consecutive_errors", 10))
        if kodolas not in KODOLASOK:
            raise ValueError(f"ismeretlen kódolás: {kodolas} (lehetséges: {', '.join(KODOLASOK)})")
        self.kodolas = kodolas
        contact = (http_cfg.get("contact") or "").strip()
        if not contact:
            log.warning("config.toml: http.contact üres – kérjük, adjon meg kapcsolati e-mailt (TERV F8).")
        self.user_agent = (f"Mozilla/5.0 (compatible; idegenrendeszet-hatarozat-gyujto/{__version__}"
                           + (f"; +mailto:{contact}" if contact else "") + ")")
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Language": "hu-HU,hu;q=0.9",
        })
        self._last_request = 0.0
        self._consecutive_errors = 0
        self._initialized = False
        self.requests_made = 0

    # -- belső segédek ---------------------------------------------------
    def _throttle(self, delay: tuple[float, float]) -> None:
        wait = random.uniform(*delay) - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _init_session(self) -> None:
        """A keresőoldal megnyitása (sütik, munkamenet), ahogy a böngésző is tenné."""
        self._throttle(self.list_delay)
        r = self.session.get(self.base + SEARCH_PAGE, timeout=self.timeout)
        self._last_request = time.monotonic()
        self.requests_made += 1
        r.raise_for_status()
        self._initialized = True

    @staticmethod
    def _retry_after(resp: requests.Response | None) -> float | None:
        if resp is None:
            return None
        ra = resp.headers.get("Retry-After")
        if not ra:
            return None
        try:
            return float(ra)
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(ra) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None

    def _request(self, method: str, path: str, delay: tuple[float, float], **kw) -> requests.Response:
        if not self._initialized:
            self._init_session()
        url = self.base + path
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(delay)
            resp = None
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kw)
                self.requests_made += 1
                self._last_request = time.monotonic()
                if resp.status_code == 200:
                    self._consecutive_errors = 0
                    return resp
                if resp.status_code in (401, 403, 419, 440):
                    # Lejárt munkamenet: egyszer újranyitjuk az oldalt.
                    log.warning("HTTP %s – munkamenet újranyitása (%s/%s)", resp.status_code, attempt, self.max_retries)
                    self._initialized = False
                    self._init_session()
                    last_exc = ApiError(f"HTTP {resp.status_code}")
                elif resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = ApiError(f"HTTP {resp.status_code}")
                else:
                    self._register_error()
                    raise ApiError(f"HTTP {resp.status_code} – {url}")
            except (requests.Timeout, requests.ConnectionError) as e:
                self._last_request = time.monotonic()
                last_exc = e
            backoff = self._retry_after(resp) or min(300.0, 5.0 * 2 ** (attempt - 1))
            backoff *= random.uniform(1.0, 1.3)
            log.warning("Hiba (%s), újrapróbálás %.0f s múlva (%s/%s)", last_exc, backoff, attempt, self.max_retries)
            time.sleep(backoff)
        self._register_error()
        raise ApiError(f"{self.max_retries} próbálkozás után sem sikerült: {last_exc}")

    def _register_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.max_consecutive:
            raise TooManyErrors(f"{self._consecutive_errors} egymás utáni hiba – leállás.")

    # -- nyilvános műveletek --------------------------------------------
    def search(self, spec: SearchSpec, start: int = 0, count: int = 100,
               kodolas: str | None = None) -> SearchResult:
        kodolas = kodolas or self.kodolas
        spec = spec.with_scalars(ResultStartIndex=str(start), ResultCount=str(count))
        body = ({"json": build_json(spec)} if kodolas == "json"
                else {"data": build_form(spec, kodolas)})
        resp = self._request("POST", SEARCH_PATH, self.list_delay, **body,
                             headers={"X-Requested-With": "XMLHttpRequest",
                                      "Referer": self.base + SEARCH_PAGE})
        try:
            js = resp.json()
        except ValueError as e:
            # HTML jött JSON helyett: többnyire lejárt munkamenet vagy hibaoldal.
            self._initialized = False
            self._register_error()
            raise ApiError(f"A keresés nem JSON-t adott vissza ({resp.headers.get('Content-Type')})") from e
        if isinstance(js, dict) and js.get("Success") is False:
            self._register_error()
            raise ApiError(f"A szerver hibát jelzett: {js.get('Message')}")
        if not isinstance(js, dict) or "Count" not in js or "List" not in js:
            raise SchemaError(f"Váratlan válaszszerkezet: {str(js)[:200]}")
        items = js.get("List") or []
        for it in items:
            missing = [f for f in REQUIRED_FIELDS if f not in it]
            if missing:
                raise SchemaError(f"Hiányzó mező(k) a találatban: {', '.join(missing)}")
        return SearchResult(count=int(js.get("Count") or 0), items=items)

    def count(self, spec: SearchSpec, kodolas: str | None = None) -> int:
        return self.search(spec, start=0, count=1, kodolas=kodolas).count

    def download(self, birosag: str, ugyszam: str, index_id: str) -> Document:
        resp = self._request("GET", DOWNLOAD_PATH, self.doc_delay,
                             params={"Area": "", "birosagName": birosag, "ugyszam": ugyszam,
                                     "azonosito": index_id},
                             headers={"Referer": self.base + SEARCH_PAGE})
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype in ("text/html", "application/json"):
            self._register_error()
            raise ApiError(f"Letöltés helyett {ctype} jött: {resp.text[:200]}")
        if not resp.content:
            self._register_error()
            raise ApiError("Üres letöltés")
        return Document(resp.content, ctype, _filename(resp.headers.get("Content-Disposition", "")))


def _filename(cd: str) -> str | None:
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I)
    if m:
        return unquote(m.group(1).strip('"'))
    m = re.search(r'filename="?([^";]+)"?', cd, re.I)
    return m.group(1) if m else None
