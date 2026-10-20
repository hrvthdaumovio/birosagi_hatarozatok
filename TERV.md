# Terv – Idegenrendészeti bírósági határozatok automatizált gyűjtése és rendszerezése

*Készült: 2026-10-20 · Frissítve: 2026-10-20 (hatókör- és felhasználási döntések beépítve) · Forrás: https://eakta.birosag.hu/anonimizalt-hatarozatok (Bírósági Határozatok Gyűjteménye, BHGY)*

## 0. Cél és hatókör

**Cél**
1. Az idegenrendészeti tárgyú anonimizált bírósági határozatok **teljes körű** letöltése (metaadat + szöveg).
2. **Inkrementális frissítés**: később csak az újonnan publikált határozatokat töltse le.
3. **Rendszerezés**: SQLite-adatbázis és Excel-export, besorolással (ügytípus, kimenetel, bíróság, év, jogszabályhely) és a fokozatok összekötésével (első fok → Kúria).

**Hatókör (döntés, 2026-10-20)**

| Bent | Kint |
|---|---|
| Harmadik országbeli állampolgárok beutazása és tartózkodása (2007. évi II. tv. – Harmtv., 2024-től 2023. évi XC. tv.): vízum, tartózkodási és letelepedési engedély, kiutasítás, beutazási és tartózkodási tilalom, idegenrendészeti őrizet | Menekültügy, menedékjog (2007. évi LXXX. tv. – Met.), beleértve a Dublin-ügyeket és a menekültügyi őrizetet |
| Szabad mozgás és tartózkodás joga (2007. évi I. tv. – Szmtv.: EGT-állampolgárok és családtagjaik) | Állampolgársági ügyek (1993. évi LV. tv. – Ápt.: honosítás, visszahonosítás) |
| Csak közigazgatási kollégium | Büntetőügyek (pl. embercsempészés, tiltott határátlépés, kiutasítás mint büntetés) és szabálysértési ügyek |

A **vegyes** határozatokat (pl. menekültügyi döntés idegenrendészeti kiutasítással vagy őrizettel) megtartjuk, de megjelöljük, hogy szűrhetők legyenek.

**Felhasználás:** belső, nem publikált; folyamatfejlesztés és szakmai ismeretbővítés. **Kimenet:** SQLite + Excel, keresőfelület nem kell.

---

## 1. Ellenőrzött tények (mérve 2026-10-20-án, kb. 35 kíméletes kéréssel)

A próbaszkriptek a `tools/probe_api*.py` fájlokban vannak.

| Téma | Eredmény |
|---|---|
| **Kereső végpont** | `POST https://eakta.birosag.hu/AnonimizaltHatarozat/Search`, form-data. A válasz JSON: `{Count, List[...]}`. Nem kell hozzá belépni. CAPTCHA-t nem tapasztaltunk. |
| **Tárgycímke paraméter** | `HierarchikusPertargy`. **Pontos egyezés**: az alcímkék *nem* tartoznak bele a főcímkébe, ezért mindhármat külön le kell kérdezni (lásd lent). |
| **Találatok** (kollégium-szűrő nélkül) | Főcímke („Idegenrendészet, menekültügy és állampolgársági ügyek”): **889** · „…/Harmadik országbeli állampolgárok beutazása és tartózkodása”: **2 801** · „…/Menedékjog”: **1 560** · kulcsszó „Országos Idegenrendészeti Főigazgatóság”: **1 286**. A Menedékjog alcímke a hatókör-döntés miatt **kimarad**. A főcímke és az OIF-kulcsszó **vegyes** (menekültügy és állampolgárság is van benne), ezért szűrni kell (3.2). |
| **Találati korlát** | Szűrés nélkül `Count = 10000`, vagyis a rendszer ennyinél többet nem jelez. A mi szeleteink jóval kisebbek, így ez nem érint minket. |
| **Lapozás** | Az alapértelmezett rendezéssel (`Rendezes=BirosagiSzint`) **hiányos az eredmény**: 889 lekért rekordból 27 ismétlődött, tehát 27 hiányzott. **`Rendezes=IndexelesIdejeNovekvo`** rendezéssel 889/889 egyedi rekord jött, 0 ismétlődés. |
| **Rendezés publikálás szerint** | Működik (`IndexelesIdejeCsokkeno` / `…Novekvo`). A legkorábbi publikálási dátum 2020-07-16, a legfrissebb 2026-10-05. **Erre épülhet az inkrementális frissítés.** |
| **Letöltés** | `GET /AnonimizaltHatarozat/DownloadHatarozatMobile?Area=&birosagName={MeghozoBirosag}&ugyszam={Azonosito}&azonosito={IndexId}`. A válasz **`application/rtf`**, kb. 22 KB. |
| **Rekord mezői** | `EgyediAzonosito, Azonosito, IndexId, MeghozoBirosag, Kollegium, JogTerulet, HatarozatEve, IndexelesIdeje, Jogszabalyhelyek, KapcsolodoHatarozatok, Rezume, NemHivatkozhatoSzoveg, Szoveg (a listában mindig null), DownloadLink` |
| **`NemHivatkozhato`** | „nem” és „igen” értékkel is 889 a főcímkén. Nem tudjuk, hogy ennél a címkénél tényleg nincs nem hivatkozható határozat, vagy a szerver figyelmen kívül hagyja a mezőt. **Nyitott kérdés.** |
| **robots.txt** | Nincs (404-es hibaoldal jön vissza). |
| **Felhasználási feltételek** (`/felhasznalasi-feltetelek`) | Csak az E-aktáról és az adatkezelésről szól. Gépi hozzáférést **nem tilt**. A birosag.hu „Jognyilatkozat” oldala automatikus lekérésre 403-at ad, ezt **kézzel kell elolvasni**. |

### 1.1 A mentett keresőoldalból (`tools/_search_page.html`) kiolvasva – élőben még nem tesztelt

| Téma | Amit az oldal kódja mutat | Teendő M1-ben |
|---|---|---|
| **Kulcsszó-operátor** | A felület a kulcsszavakat `KeresoSzavak[]` + `KeresoSzoOperatorok[]` tömbként küldi. Az operátor értéke `Osszes` (összes szó), `Kifejezes` (szavak egymás mellett) vagy `Pontos` (pontos kifejezés). A próbák eddig csak a sima `KeresoSzo` mezőt használták. | Ellenőrizni, hogy a `Pontos` operátorral kevesebb, pontosabb találat jön-e. |
| **Jogszabályhely-szűrő** | A „gyakori jogszabályok” listában azonosítóval szerepel a Harmtv. (`0facc161-05be-4172-9b3f-18d05fc61897`), az Szmtv. (`a97f27e0-461b-4420-8c9d-a94dfd6beead`) és az Ápt. (`b99cde78-231e-4a2d-b98f-f67c473545e4`). A 2023. évi XC. tv. és a Met. **nincs** a listában. A felület `JogszabalyHelyek[]` tömböt küld. | Kideríteni a tömb elemeinek pontos szerkezetét. Ha működik, ez lesz a legpontosabb szelet. |
| **Kollégium-szűrő** | `Kollegium` mező, értékei: büntető, gazdasági, közigazgatási, munkaügyi, polgári. | Ellenőrizni, hogy a szerver tényleg szűr-e vele. A régi scraper elírt kulccsal küldte, így ez nincs kipróbálva. |
| **Érintett közigazgatási szerv** | `ErintettKozigazgatsaiSzerv` (sic) szabad szöveges mező. Az értékek nagyon következetlenek, pl. „Országos Idegenrendészeti Főigazgatóság”, „ORSZÁGOS IDEGENRENDÉSZETI FŐIGAZGATÓSÁG”, „Országos Idegenrendészet Főigazgatóság”, „…Főigazgaatóság”, „bevándorlási.és.állampolgársági.hivatal”. | Ellenőrizni, hogy részszóra (pl. „Idegenrendészet”) keres-e. Ha igen, kiegészítő szelet lehet. |

---

## 2. A meglévő repó (Code-for-Hungary/bmm-birosagscraper) értékelése

- **Állapot:** a PR #4 (új hitelesítés) és a PR #5 (új keresési mód, `just_download`) **be van olvasztva** a main ágba. A helyi `bmm-birosagscraper-main` mappa ZIP-ből jött (nincs benne `.git`), és már tartalmazza mindkettőt.
  - Az **issue #6** („scraper optimalizálás”) több hibát leír. Ezekre **nincs javító PR**.
- **Hasznos belőle:** a végpont, a form-mezők, a letöltési URL mintája, és az SQLite FTS5 (teljes szöveges keresés) séma ötlete.
- **Licenc: nincs.** Ezért **nem másoljuk a kódját**, csak referenciának használjuk. Saját implementáció készül.

| # | Hiba / korlát | Hatás |
|---|---|---|
| 1 | Az alapértelmezett `Rendezes=BirosagiSzint` miatt instabil a lapozás (mértük: 27/889) | Csendben hiányos korpusz |
| 2 | A `FORM_OPTIONS` kulcsa ékezetes (`'Kollégium'`), a mező viszont `Kollegium`, ezért az API eldobja | 5× ugyanaz a lekérdezés, nincs bontás (issue #6) |
| 3 | Nincs `HierarchikusPertargy` (tárgycímke) támogatás | A teljes adatbázist tükrözné, nekünk viszont csak egy szelet kell |
| 4 | `Count == 10000` esetén `NotImplementedError` | Az egész futás leáll |
| 5 | `GET /hatarozat-letoltes`, és **docx**-et vár. Az oldal JS-e ezt POST-tal hívja, a mobil végpont pedig RTF-et ad. | A letöltés valószínűleg hibára fut (nem teszteltük) |
| 6 | `main()` beégetve a `config.ini`-t olvassa, a parancssori argumentumot nem dolgozza fel (PR #5 óta) | A konfiguráció útvonala figyelmen kívül marad |
| 7 | `make_request`: nem 200-as válasz után szünet nélkül próbál újra | Szerverhiba esetén terheli az oldalt |
| 8 | `get_hatarozat` egy nem létező `contracts` táblát kérdez le | Halott kód / hiba |
| 9 | A huspacy függőség nehéz, és a Figyusz-backendhez van kötve (events/notify) | Nekünk felesleges |

**Döntés:** új, önálló modul készül az `idegenrendeszet-scraper/` mappában. A repót nem forkoljuk.

---

## 3. Lefedettség és hatókör-szűrés

### 3.1 Forrásszeletek

A tárgycímkét a régebbi határozatoknál feltehetően hiányosan töltötték ki. Ezért **több szeletből** gyűjtünk, és az eredményeket az `EgyediAzonosito` alapján vonjuk össze. Minden rekordnál rögzítjük, melyik szelet hozta.

Minden szelet `Kollegium=közigazgatási` szűrővel fut. Ha a szerver nem szűr vele, utólag szűrünk a rekord `Kollegium` mezője alapján.

**A) Tárgycímkék** (`HierarchikusPertargy`, pontos érték):
1. `…/Harmadik országbeli állampolgárok beutazása és tartózkodása`: 2 801 találat, ez a **mag**.
2. `Idegenrendészet, menekültügy és állampolgársági ügyek` (főcímke alcímke nélkül): 889 találat, **vegyes**, hatókör-szűrés kell.
3. ~~`…/Menedékjog`~~: **kimarad** (hatókörön kívül).

**B) Jogszabályhely** (ha az 1.1 szerinti szűrő működik): Harmtv., Szmtv.

**C) Kulcsszavak** („Pontos kifejezés”). Kezdő lista, a validálás alapján finomítjuk:
- `2023. évi XC. törvény` (2024-től; nincs a jogszabály-listában)
- `idegenrendészeti őrizet` · `beutazási és tartózkodási tilalom` · `tartózkodási engedély` · `letelepedési engedély` · `vendégmunkás-tartózkodási engedély` · `kiutasítás`
- `Országos Idegenrendészeti Főigazgatóság` (2019. júl. 1-től) · `Bevándorlási és Állampolgársági Hivatal` (2000–2019). Mindkét hatóság menekültügyben is eljárt (a BÁH állampolgársági ügyben is), ezért ezek a kulcsszavak **zajosak**, csak hatókör-szűréssel használhatók.

**D) Érintett közigazgatási szerv** (opcionális, ha az 1.1 szerinti teszt sikeres).

### 3.2 Hatókör-szűrés (`scope.py`)

Kétlépcsős, hogy a biztosan kívül eső határozatokat le se kelljen tölteni.

**1. lépcső: metaadat alapján** (`Jogszabalyhelyek`, `Rezume`, `Kollegium`, ügyszám), letöltés előtt:
- `Kollegium` nem közigazgatási → **kint** (`bunteto` / `egyeb`).
- Van Harmtv., Szmtv. vagy 2023. évi XC. tv. hivatkozás, Met. és Ápt. nincs → **idegenrendeszet**.
- Csak Met. → **menekultugy** (kint). Csak Ápt. → **allampolgarsag** (kint).
- Harmtv./Szmtv./XC. **és** Met. együtt → **vegyes** (bent, megjelölve).
- Nincs eldöntő jogszabályhely → **bizonytalan** → RTF letöltése, majd 2. lépcső.

**2. lépcső: szöveg alapján**, a bizonytalanokra, súlyozott kifejezéslistával:
- idegenrendészeti jelek: „tartózkodási engedély”, „idegenrendészeti őrizet”, „kiutasítás”, „beutazási és tartózkodási tilalom”, „vízum”, „regisztrációs igazolás”, „tartózkodási kártya”;
- menekültügyi jelek: „menekültkénti elismerés”, „oltalmazott”, „menedékjog”, „Dublin”, „menekültügyi őrizet”, „befogadó állomás”;
- állampolgársági jelek: „honosítás”, „visszahonosítás”, „állampolgársági eskü”.
- Ha így sem dönthető el, `bizonytalan` marad, és a Kézi ellenőrzés fülre kerül (7. fejezet).

A kint maradt rekordok **metaadata** megmarad az SQLite-ban (audit, utólagos újraosztályozás), de az RTF-jüket nem töltjük le, és az Excelbe nem kerülnek be. A szabályok és kifejezéslisták a `config.toml`-ban vannak, így kódmódosítás nélkül finomíthatók.

### 3.3 Validálás

- Szeletenként: a letöltött egyedi rekordok száma egyezik a `Count`-tal.
- Kézi mintavétel: 50 „bent” és 50 „kint” rekord átnézése.
  - **Elfogadás:** a bent tartottak legalább 95%-a valóban idegenrendészeti; a kiszűrtek közül legfeljebb 1 téves kizárás.
- A csak kulcsszóból jövő találatokat külön figyeljük. Ha egy kulcsszó szinte csak hatókörön kívüli határozatot hoz, kivesszük a listából.

### 3.4 Várható volumen

Kb. 3,5–4,5 ezer jelölt rekord a szeletekből; a hatókör-szűrés után ennél kevesebb. A pontos szám az M1 végén derül ki. Egy RTF kb. 22 KB, így a teljes gyűjtemény nagyjából 50–100 MB.

---

## 4. Architektúra

```
idegenrendeszet-scraper/
├─ TERV.md
├─ README.md
├─ requirements.txt        # requests, striprtf, openpyxl (minimális)
├─ config.toml             # szeletek, kulcsszavak, hatókör-szabályok, ügytípus-kategóriák, szünetek, User-Agent + kapcsolati e-mail
├─ src/hatarozat/
│  ├─ api.py               # Search + letöltés; rate limit, újrapróbálás, munkamenet
│  ├─ sources.py           # címkék/kulcsszavak → lekérdezés-definíciók
│  ├─ scope.py             # hatókör-szűrés (idegenrendészet / vegyes / kint / bizonytalan)
│  ├─ db.py                # SQLite séma, upsert, FTS5
│  ├─ harvest.py           # listalekérés: teljes / inkrementális
│  ├─ fetch_docs.py        # RTF letöltés, sha256, szövegkinyerés
│  ├─ enrich.py            # jogszabályhely, kimenetel, ügytípus, láncolás
│  ├─ export.py            # Excel-export (+ CSV), kézi ellenőrzés visszaolvasása
│  └─ __main__.py          # CLI: harvest | scope | fetch | enrich | export | review-import | status
├─ data/
│  ├─ hatarozatok.db
│  ├─ raw/{év}/{bíróság}/{EgyediAzonosito}.rtf
│  └─ export/idegenrendeszeti_hatarozatok_{dátum}.xlsx
├─ logs/
├─ tests/
└─ tools/                  # próbaszkriptek; _search_page.html (gyorsítótár, .gitignore)
```

Python 3.12 (telepítve van). A `data/`, `logs/` és `tools/_search_page.html` kerüljön a `.gitignore`-ba. Mindent UTF-8 kódolással írunk, mert a Windows-konzol (cp1252) eltorzítja az ékezeteket.

---

## 5. Adatmodell (SQLite)

| Tábla | Fő mezők |
|---|---|
| `hatarozat` | `egyedi_azonosito` (PK), `azonosito`, `index_id`, `birosag`, `birosag_szint`, `kollegium`, `jogterulet`, `ev`, `indexeles_ideje`, `rezume`, `jogszabalyhelyek_raw`, `kapcsolodo_raw` (JSON), `nem_hivatkozhato`, `elso_lattuk`, `utoljara_lattuk`, `rtf_path`, `rtf_sha256`, `letoltve_at`, `szoveg`, `hatokor` (idegenrendeszet / vegyes / menekultugy / allampolgarsag / bunteto / egyeb / bizonytalan), `hatokor_ok`, `hatokor_modszer` (metaadat / szöveg / kézi) |
| `lekerdezes` | `id`, `tipus` (címke/kulcsszó), `ertek`, `utolso_count`, `utolso_futas` |
| `forras` | `egyedi_azonosito`, `lekerdezes_id`, `elso_talalat`: melyik szelet hozta |
| `kapcsolat` | `egyedi_azonosito`, `kapcsolodo_ugyszam`, `kapcsolodo_birosag` (a `KapcsolodoHatarozatok`-ból) |
| `jogszabalyhely` | `egyedi_azonosito`, `jogszabaly`, `szakasz` (normalizálva) |
| `besorolas` | `egyedi_azonosito`, `ugytipus`, `kimenetel`, `modszer` (szabály/kézi), `megbizhatosag` |
| `hatarozat_fts` | FTS5 (`szoveg`, `rezume`), `unicode61 remove_diacritics 2` |
| `futas` | `id`, `kezdet`, `veg`, `uj_rekord`, `letoltott`, `hibak`: auditnapló |
| `kezi_ellenorzes` | `egyedi_azonosito`, `mezo` (hatókör / ügytípus / kimenetel), `gepi_ertek`, `kezi_ertek`, `ellenorizte`, `datum`: a validálási minták és a kézi javítások. A kézi érték mindig felülírja a gépit. |

Semmit nem törlünk. Ha egy határozat eltűnik a forrásból, csak az `utoljara_lattuk` mező nem frissül tovább.

---

## 6. A letöltő működése

**Kíméletes működés (kötelező):**
- 1 párhuzamos kapcsolat.
- Listakérések között 2–3 s, letöltések között 3 s ± véletlen eltolás.
- Exponenciális visszalépés 429/5xx/időtúllépés esetén (max. 5 próba). 10 egymás utáni hiba után leáll.
- Azonosítható User-Agent kapcsolati e-mail-címmel.
- Éjszakai futtatás.

**Teljes gyűjtés (`harvest --full`):** minden szeletnél `Rendezes=IndexelesIdejeNovekvo`, oldalanként 100 rekord, `ResultStartIndex` léptetésével. Az eredményeket upserttel (beszúrás vagy frissítés) írjuk az adatbázisba, és a végén ellenőrizzük, hogy a darabszám egyezik-e a `Count`-tal.

**Inkrementális (`harvest`):**
- Szeletenként `IndexelesIdejeCsokkeno` rendezéssel lapozunk.
- Megállunk, ha a rekord `IndexelesIdeje` értéke régebbi, mint az eddigi legfrissebb időpont mínusz 7 nap biztonsági ráhagyás.
- Hetente egyszer teljes egyeztetés (kb. 60 listakérés), hogy az utólag indexelt vagy eltávolított tételek is kiderüljenek.

**Dokumentumok (`fetch`):**
- RTF-letöltés minden olyan rekordra, ahol `rtf_path IS NULL` és a hatókör `idegenrendeszet`, `vegyes` vagy `bizonytalan`. A hatókörön kívülieket nem töltjük le.
- sha256 ellenőrzőösszeg, majd szövegkinyerés `striprtf`-fel.
- Mentés a `szoveg` mezőbe és az FTS-indexbe.
- Megszakítás után ott folytatja, ahol abbahagyta (idempotens).
- Letöltés után a bizonytalanokra lefut a szöveg alapú hatókör-szűrés (3.2, 2. lépcső).

**Becsült idő:**
- Első teljes futás: listák kb. 5 perc; letöltés dokumentumonként ~3 s, 3 500 dokumentumnál kb. 3 óra.
- Napi frissítés: néhány perc.
- Ütemezés: Windows Feladatütemező (Task Scheduler).

---

## 7. Rendszerezés (`enrich`, `export`)

1. **Normalizálás:**
   - bírósági szint (Kúria / ítélőtábla / törvényszék / közigazgatási és munkaügyi bíróság / járásbíróság);
   - év;
   - ügyszám felbontása (ügycsoport, pl. K, Kf, Kfv, Kpk).
2. **Jogszabályhelyek:** a `Jogszabalyhelyek` mezőből és a szövegből kinyerjük, és „törvény + §” formára normalizáljuk.
3. **Kimenetel:** szabályalapú kinyerés a rendelkező részből (elutasítja / megsemmisíti / megváltoztatja / hatályon kívül helyezi / megszünteti / hatályában fenntartja).
4. **Ügytípus:** szabályalapú besorolás kulcsszavak és jogszabályhelyek alapján. Kezdő kategóriák (a `config.toml`-ban bővíthetők; egy határozat több kategóriába is eshet):
   - tartózkodási engedély – foglalkoztatási cél (pl. vendégmunkás, összevont engedély, EU Kék Kártya)
   - tartózkodási engedély – egyéb cél (családi, tanulmányi, egyéb)
   - letelepedési engedély (nemzeti, EK, ideiglenes)
   - vízum
   - kiutasítás
   - beutazási és tartózkodási tilalom / SIS-figyelmeztető jelzés
   - idegenrendészeti őrizet
   - szabad mozgás (EGT-állampolgár és családtagja; regisztrációs igazolás, tartózkodási kártya)
   - eljárási kérdés (pl. hiánypótlás, határidő, hatáskör)
   - egyéb

   LLM-es segítség csak az adatvédelmi tisztviselő jóváhagyásával, jóváhagyott belső modellel jöhet szóba; alapból nem használjuk (8. fejezet).
5. **Láncolás:** a `kapcsolat` tábla alapján egy ügy fokozatainak összekötése (K → Kf/Kfv).
6. **Excel-export** (`data/export/idegenrendeszeti_hatarozatok_{dátum}.xlsx`), csak a bent tartott (`idegenrendeszet`, `vegyes`) határozatokkal:
   - **Határozatok** fül: egy sor = egy határozat (azonosító, bíróság, szint, év, publikálás dátuma, hatókör, ügytípus, kimenetel, jogszabályhelyek, rezümé, link a helyi RTF-re). Szűrő és rögzített fejléc. A teljes szöveg nem kerül bele (adattakarékosság); az az SQLite-ban és az RTF-ben van.
   - **Ügyláncok** fül: egy sor = egy ügy fokozatai (első fok → Kúria), a végső kimenetellel.
   - **Összesítő** fül: darabszámok év, ügytípus, kimenetel és bíróság szerint.
   - **Kézi ellenőrzés** fül: a bizonytalan hatókörű és a validálási mintába került rekordok, kitölthető oszlopokkal. A javításokat a `review-import` parancs olvassa vissza a `kezi_ellenorzes` táblába.
   - Keresőfelület nem készül. A teljes szöveges keresés az SQLite FTS5-tel megy, pl. DB Browser for SQLite-ban.

**Elfogadási feltétel:** 100 véletlen határozaton kézi ellenőrzéssel az ügytípus és a kimenetel legalább 90%-ban helyes.

---

## 8. Jogi és adatvédelmi keretek

- **Szerzői jog:** a bírósági határozatok nem állnak szerzői jogi védelem alatt (Szjt. 1. § (4)). A közzétételt a Bszi. 163. §-a írja elő.
- **Felhasználási cél (döntés):** belső, nem publikált; folyamatfejlesztés és szakmai ismeretbővítés.
- **Adatbázis-előállítói jog:** az OBH-t védelem illetheti meg (Szjt. 84/A. §). A gyűjtemény nem kerül továbbadásra vagy publikálásra, az adatbázisnak csak egy tematikus szeletét kérjük le, kíméletes tempóban, így a kockázat alacsony. Ha később mégis felmerül a megosztás vagy a publikálás, előtte tisztázni kell.
- **Adatvédelem (GDPR):** belső felhasználásnál is érvényes. A szövegek az anonimizálás ellenére tartalmazhatnak különleges adatot (származás, vallás, egészség), és a ritka tényállások miatt az újraazonosítás nem kizárt.
  - Mivel a cél szervezeti (folyamatfejlesztés), **röviden egyeztetni kell az adatvédelmi tisztviselővel (DPO)** a célról, a tárolás helyéről, a hozzáférési körről és a megőrzési időről. Az M1-et (csak metaadat) ez nem akadályozza, de az M2 (teljes szövegek) előtt legyen meg.
  - Az érintettek beazonosítása és más adatokkal való összekapcsolása tilos.
  - Tárolás céges gépen vagy jogosultsággal védett belső meghajtón; nyilvános vagy külső felhőbe nem kerül. Hozzáférés csak a projekt résztvevőinek.
  - Adattakarékosság: az Excelbe nem kerül teljes szöveg; a hatókörön kívüli határozatoknak csak a metaadatát tartjuk meg.
  - A szövegeket külső AI-szolgáltatásba nem töltjük fel a DPO jóváhagyása nélkül.
  - Megőrzés: évente felülvizsgáljuk, hogy a gyűjteményre még szükség van-e a célhoz.
- A birosag.hu Jognyilatkozatát kézzel el kell olvasni (automatikus lekérésre 403).

---

## 9. Mérföldkövek

| # | Lépés | Kész, ha… |
|---|---|---|
| M0 | Előkészítés, próbák | ✅ kész (1. fejezet) |
| M1 | `api.py`, `db.py`, `sources.py`, `harvest --full` (csak metaadat) + az 1.1 szerinti szűrők tesztje | Minden szeletnél egyezik a lekért egyedi darabszám és a `Count`; tudjuk, mely szűrők működnek (kollégium, pontos kifejezés, jogszabályhely, érintett szerv) |
| M2 | `scope` (1. lépcső) → `fetch` (RTF + szöveg + FTS) → `scope` (2. lépcső) | Teljesül a hatókör-validálás (3.3); minden bent tartott rekordnak van szövege; hibalista üres vagy dokumentált. **Előfeltétel:** DPO-egyeztetés |
| M3 | Inkrementális mód + ütemezés | Két egymás utáni futás: a második 0 új rekordot hoz; a heti egyeztetés lefut |
| M4 | `enrich` + Excel-export + `review-import` | Teljesül az elfogadási feltétel (7. fejezet); az Excel mind a négy füle elkészül |
| M5 | (opcionális) besorolás finomítása, lemmatizálás | Igény szerint; keresőfelület nem kell |

---

## 10. Tesztelés

- **Egységtesztek** rögzített JSON- és RTF-mintákkal. A teszt nem hív hálózatot.
- **Hatókör-szűrés tesztjei:** rögzített példák minden kategóriára (idegenrendészet, vegyes, menekültügy, állampolgárság, büntető, bizonytalan).
- **Darabszám-egyeztetés:** szeletenként `Count` és a lekért egyedi rekordok összevetése, eltérésnél figyelmeztetés.
- **Ismétlés- és hiánydetektálás** minden futás után, eredmény a `futas` táblába.
- **Kis élő füstteszt** (1 oldal, 1 letöltés) a nagy futás előtt.

---

## 11. Kockázatok és nyitott kérdések

| Kockázat / kérdés | Kezelés |
|---|---|
| Változik az API (mezőnevek, végpont) | A próbaszkript a futás elején ellenőrzi a sémát; eltérésnél leáll |
| Rate limit vagy tiltás | Kíméletes működés; szükség esetén tömeges adatkérés az OBH-tól (e-ugyintezes@birosag.hu) |
| A tárgycímke a régi határozatoknál hiányos | Kulcsszavas szeletek + validálás (3. fejezet) |
| Az OIF és a BÁH menekültügyben is eljárt (a BÁH állampolgársági ügyben is), ezért a hatóság-kulcsszavak zajosak | Hatókör-szűrés (3.2) + mintavételes validálás (3.3) |
| A vegyes ügyek (menekültügy + idegenrendészeti kiutasítás vagy őrizet) határa nem éles | Külön `vegyes` jelölés, az Excelben szűrhető |
| A `Kollegium` szűrő a szerveren esetleg nem működik | Utólagos szűrés a rekord `Kollegium` mezője alapján |
| `NemHivatkozhato` hatása tisztázatlan | „igen” értékkel futtatjuk; egy ismert nem hivatkozható határozattal ellenőrizzük |
| RTF-kódolás, táblázatok | `striprtf`; problémás fájlnál tartalék megoldás LibreOffice-konverzióval |

**Döntések (2026-10-20):**
1. Csak idegenrendészet: a menekültügy és az állampolgársági ügyek **kimaradnak**; a vegyes ügyek megjelölve bent maradnak. Az Szmtv. szerinti szabad mozgásos ügyeket idegenrendészetnek tekintjük.
2. Büntetőügyek **nem kellenek** (szabálysértési ügyek sem).
3. Felhasználás: **belső, nem publikált**, folyamatfejlesztés és ismeretbővítés → DPO-egyeztetés az M2 előtt.
4. Kimenet: **Excel + SQLite**, keresőfelület nem kell.

---

## 12. Következő lépés

M1: az `api.py`, `db.py`, `sources.py` és `harvest.py` megírása; az 1.1 szerinti szűrők kipróbálása; a teljes metaadat-gyűjtés a 3.1 szeleteire és a darabszámok egyeztetése. Ezzel párhuzamosan: a DPO-egyeztetés kezdeményezése.

---

## 13. Terv-felülvizsgálat a kivitelezés előtt (2026-10-20)

A terv a mentett oldal kódjával és a próbák eredményeivel összevetve megvalósítható. Az alábbi hiányokat és pontosításokat találtam; a kivitelezés ezek szerint megy.

| # | Megállapítás | Javítás a tervben / kódban |
|---|---|---|
| F1 | **10 000-es találati plafon.** A széles kulcsszavas szeletek (pl. „kiutasítás”, „tartózkodási engedély”) elérhetik, ilyenkor a lapozás csonka lenne. | Ha `Count ≥ 10000`, a szeletet a letöltő automatikusan **évenként** bontja (`MeghozatalIdejeTol/Ig`). |
| F2 | **Azonos publikálási időpontú rekordok.** A rendezés ilyenkor nem determinisztikus, nagyobb szeletnél a lapozás még `IndexelesIdejeNovekvo` mellett is hiányos lehet (a 889-es próba ezt nem zárja ki a 2 801-es szeletre). | Minden szelet végén egyeztetés: ha `egyedi < Count`, második menet **fordított rendezéssel** és unió; ha még mindig hiányos, évenkénti bontás. Az eltérés a `lekerdezes` táblába és a naplóba kerül. |
| F3 | A nyers API-válasz nem volt tárolva, így egy elemzési hiba javítása újra hálózati lekérést igényelne. | `hatarozat.raw_json` mező: minden rekord teljes JSON-ja megmarad. |
| F4 | Az 1.1 nyitott kérdései közül a mezőnevek a mentett oldal JS-éből kiolvashatók. | Kulcsszó: `KeresoSzavak[]` + `KeresoSzoOperatorok[]`. Jogszabályhely: `JogszabalyHelyek[i]` = `{GyakoriJogszabalyId, JogszabalyHivatkozas, JogszabalyIdejeTol, JogszabalyIdejeIg}`. Érintett szerv: `ErintettKozigazgatsaiSzerv`. Az M1-ben élőben ellenőrizzük. |
| F5 | A weboldal a letöltést `POST /hatarozat-letoltes` (JSON) hívással végzi, a mobil `GET` végpont RTF-et ad (mért). | A mobil GET végpontot használjuk; ha megszűnne, a POST a tartalék. |
| F6 | A bíróság neve (ékezet, szóköz) a fájlútvonalban Windows alatt gondot okozhat. | Az útvonalban ékezet nélküli, kötőjeles név (slug); az eredeti név az adatbázisban marad. |
| F7 | A pytest nincs telepítve, a striprtf sincs. | Tesztek a beépített `unittest`-tel (nem kell új függőség). A `striprtf` csak az M2-ben kell, akkor telepítjük. |
| F8 | A User-Agentbe kapcsolati e-mail kell, ezt nem ismerjük. | `config.toml` → `http.contact`; a felhasználó tölti ki. Üresen is fut, de figyelmeztet. |
| F9 | A DPO-feltétel (8. fejezet) technikailag nem volt kikényszerítve. | `config.toml` → `adatvedelem.dpo_jovahagyva = false`; amíg hamis, a `fetch` (teljes szövegek) nem indul el. A metaadat alapú hatókör-szűrés (3.2, 1. lépcső) ettől függetlenül futhat. |
| F10 | A tervben nem szerepelt, hogyan futtatható a program `src/` elrendezéssel telepítés nélkül. | `run.py` a projekt gyökerében (`python run.py harvest --full`); UTF-8 kimenet. |
| F11 | Ha a szerver egy szűrőt csendben figyelmen kívül hagy (pl. rossz tömbkódolás a jogszabályhelynél), a szelet a teljes adatbázist hozná le (a régi scraper #2-es hibája). | Letöltés előtt minden szeletnél összevetjük a `Count`-ot a szűretlen találatszámmal; ha nem kisebb, a szelet **kimarad** és hibaként jelenik meg. Plafon esetén egy évre szűkítve hasonlítunk. |
