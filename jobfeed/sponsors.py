"""Official registers of licensed visa sponsors.

* UK  — Home Office "Register of licensed sponsors: workers" (CSV, updated daily).
* NL  — IND public register of recognised sponsors (regular labour & highly skilled migrants).
* US  — USCIS H-1B Employer Data Hub: employers with approved H-1B petitions (not a licence,
        but the official record of who sponsors).
* IE  — Department of Enterprise "Employment permits issued to companies" (this year and last):
        Ireland has no sponsor licence, so this is the official record of who sponsors.

Other countries have no public sponsor register; for those, jobs are only kept
when the advert (or the source) explicitly offers visa sponsorship. In the UAE every
employer sponsors its foreign staff's residence visa, so the pipeline treats that as given.
"""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser

from . import http
from .text import normalise_company

UK_REGISTER_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
NL_REGISTER_PAGE = ("https://ind.nl/en/public-register-recognised-sponsors/"
                    "public-register-regular-labour-and-highly-skilled-migrants")

US_H1B_HUB_PAGE = "https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub"
US_H1B_CSV_PATTERN = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{year}.csv"

IE_PERMITS_PAGE = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-{year}.html"

REGISTER_COUNTRY = {"UK Home Office": "GB", "NL IND": "NL", "US H-1B": "US", "IE employment permits": "IE"}


@dataclass
class SponsorEntry:
    name: str
    register: str
    town: str = ""
    rating: str = ""
    routes: set[str] = field(default_factory=set)


class SponsorIndex:
    def __init__(self) -> None:
        # normalised name -> register -> entry: the same name can be on several countries' registers.
        self._by_name: dict[str, dict[str, SponsorEntry]] = {}
        self._prefix_cache: dict[tuple[str, str], SponsorEntry | None] = {}
        self.counts: dict[str, int] = {}

    def add(self, entry: SponsorEntry, aliases: tuple[str, ...] = ()) -> None:
        self.counts[entry.register] = self.counts.get(entry.register, 0) + 1
        # Register names often read "Legal Name Ltd T/A Trading Name": index both halves.
        for part in [*re.split(r"\bt/a\b|\btrading as\b", entry.name, flags=re.I), *aliases]:
            key = normalise_company(part)
            if not key:
                continue
            existing = self._by_name.setdefault(key, {}).get(entry.register)
            if existing:
                existing.routes |= entry.routes
            else:
                self._by_name[key][entry.register] = entry

    @staticmethod
    def _pick(entries: dict[str, SponsorEntry], country: str) -> SponsorEntry | None:
        if country:
            return next((e for r, e in entries.items() if REGISTER_COUNTRY.get(r) == country), None) \
                or next(iter(entries.values()), None)
        return next(iter(entries.values()), None)

    def lookup(self, company: str, country: str = "") -> SponsorEntry | None:
        """The employer's entry, preferring the register of `country` when it is on several."""
        return self._pick(self._by_name.get(normalise_company(company), {}), country)

    def lookup_prefix(self, company: str, country: str = "") -> SponsorEntry | None:
        """Match "Monzo" to "Monzo Bank Ltd": only when exactly one register name starts with it.

        Used for employer career sites, where the company name comes from our own config
        and is therefore reliable, but may be a shorter trading name.
        """
        key = normalise_company(company)
        if not key:
            return None
        if (key, country) not in self._prefix_cache:
            hits = {id(e): e for name, regs in self._by_name.items() if name.startswith(key + " ")
                    for r, e in regs.items() if not country or REGISTER_COUNTRY.get(r) == country}
            entries = sorted(hits.values(), key=lambda e: e.name)
            # Several Irish permit holders from one group ("Pfizer Ireland Pharmaceuticals", "Pfizer Healthcare
            # Ireland") all count: the permit list records who sponsors, not one licence per legal entity.
            group = len(entries) > 1 and all(e.register == "IE employment permits" for e in entries)
            self._prefix_cache[(key, country)] = entries[0] if len(entries) == 1 or group else None
        return self._prefix_cache[(key, country)]

    def __len__(self) -> int:
        return len(self._by_name)


def load_uk_register(index: SponsorIndex) -> None:
    csv_text = _uk_csv_text()
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = row.get("organisation name")
        if not name:
            continue
        index.add(SponsorEntry(
            name=name, register="UK Home Office",
            town=row.get("town/city", ""), rating=row.get("type & rating", ""),
            routes={row["route"]} if row.get("route") else set(),
        ))


def _uk_csv_text() -> str:
    local = os.environ.get("UK_SPONSOR_REGISTER_CSV")
    if local:
        with open(local, encoding="utf-8-sig") as fh:
            return fh.read()
    page = http.get_text(UK_REGISTER_PAGE)
    match = re.search(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', page)
    if not match:
        raise RuntimeError("could not find the sponsor register CSV link on gov.uk")
    return http.get(match.group(1)).decode("utf-8-sig", errors="replace")


class _FirstCellParser(HTMLParser):
    """Collects the text of the first <td> in each table row."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str] = []
        self._cell = 0
        self._in_td = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._cell = 0
        elif tag == "td":
            self._cell += 1
            self._in_td = self._cell == 1
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            name = " ".join("".join(self._buf).split())
            if name:
                self.names.append(name)
            self._in_td = False

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data)


def load_nl_register(index: SponsorIndex) -> None:
    parser = _FirstCellParser()
    parser.feed(http.get_text(NL_REGISTER_PAGE))
    if not parser.names:
        raise RuntimeError("IND register page contained no sponsor rows")
    for name in parser.names:
        index.add(SponsorEntry(name=name, register="NL IND", routes={"Highly skilled migrant"}))


def load_us_h1b(index: SponsorIndex) -> None:
    """Employers with at least one approved H-1B petition in the latest USCIS Employer Data Hub export."""
    text = _us_h1b_text()
    first = text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text), delimiter="\t" if first.count("\t") > first.count(",") else ",")
    fields = [f.strip() for f in (reader.fieldnames or [])]
    reader.fieldnames = fields
    name_col = next((f for f in fields if "employer" in f.lower() or "petitioner name" in f.lower()), None)
    if not name_col:
        raise RuntimeError(f"no employer column in H-1B data ({fields[:6]})")
    approval_cols = [f for f in fields if "approval" in f.lower()]
    seen: set[str] = set()
    for row in reader:
        name = (row.get(name_col) or "").strip()
        if not name or name.upper() in seen:
            continue
        if approval_cols and not any(_number(row.get(c)) > 0 for c in approval_cols):
            continue
        seen.add(name.upper())
        index.add(SponsorEntry(name=name, register="US H-1B",
                               town=(row.get("Petitioner City") or row.get("City") or "").title(), routes={"H-1B"}))
    if not seen:
        raise RuntimeError("H-1B data contained no employers")


# Words after the brand in Irish subsidiaries' names: "Mastercard Ireland", "Salesforce Ireland Unlimited".
_IE_ENTITY_WORDS = {"ireland", "irish", "unlimited", "dac", "uc", "international", "europe", "emea", "eu", "dublin",
                    "cork", "galway", "limerick", "technologies", "technology", "services", "operations", "global",
                    "teoranta", "ie"}
_IE_SKIP = re.compile(r"^(grand )?total$|^employer name$|production test|^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                      r"[a-z]*$", re.I)


def load_ie_permits(index: SponsorIndex) -> None:
    """Companies issued Irish employment permits this year or last (Department of Enterprise statistics)."""
    names: set[str] = set()
    errors = []
    for year in (date.today().year, date.today().year - 1):
        try:
            page = http.get_text(IE_PERMITS_PAGE.format(year=year))
            link = re.search(r'href="([^"]*issued-to-companies[^"]*\.xlsx)"', page, re.I)
            if not link:
                raise RuntimeError(f"no company file on the {year} statistics page")
            url = link.group(1) if link.group(1).startswith("http") else "https://enterprise.gov.ie" + link.group(1)
            names |= set(_xlsx_first_column(http.get(url)))
        except Exception as err:  # noqa: BLE001 - the current year's page may not exist yet in January
            errors.append(f"{year}: {err}")
    names = {n for n in names if n and not _IE_SKIP.search(n)}
    if not names:
        raise RuntimeError("no Irish permit employers found (" + "; ".join(errors) + ")")
    for name in sorted(names):
        words = normalise_company(re.sub(r"\.com\b", "", name, flags=re.I)).split()  # "Salesforce.com Ireland"
        while len(words) > 1 and words[-1] in _IE_ENTITY_WORDS:
            words.pop()
        alias = " ".join(words)
        useful = len(alias) >= 3 and alias not in _IE_ENTITY_WORDS
        index.add(SponsorEntry(name=name, register="IE employment permits", routes={"Employment permit"}),
                  aliases=(alias,) if useful else ())


def _xlsx_first_column(raw: bytes) -> list[str]:
    """Text in column A of the first worksheet of an .xlsx file (stdlib only)."""
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    out = []
    for cell in sheet.iter(f"{{{ns['m']}}}c"):
        if not re.fullmatch(r"A\d+", cell.get("r", "")):
            continue
        if cell.get("t") == "s":
            value = cell.find("m:v", ns)
            text = shared[int(value.text)] if value is not None and value.text else ""
        elif cell.get("t") == "inlineStr":
            text = "".join(t.text or "" for t in cell.iter(f"{{{ns['m']}}}t"))
        else:
            continue  # numbers are counts, not names
        out.append(" ".join(text.split()))
    return out


def _number(value) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _decode(raw: bytes) -> str:
    # The hub exports UTF-16 tab-separated files under a .csv name; newer ones are UTF-8 commas.
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")


def _us_h1b_text() -> str:
    local = os.environ.get("US_H1B_EMPLOYERS_CSV")
    if local:
        with open(local, "rb") as fh:
            return _decode(fh.read())
    candidates: list[str] = []
    try:
        page = http.get_text(US_H1B_HUB_PAGE)
        candidates += [u if u.startswith("http") else f"https://www.uscis.gov{u}"
                       for u in re.findall(r'href="([^"]+\.csv)"', page)]
    except Exception:  # noqa: BLE001 - fall back to the known file names below
        pass
    candidates += [US_H1B_CSV_PATTERN.format(year=y) for y in range(date.today().year, date.today().year - 4, -1)]
    last_err: Exception | None = None
    for url in dict.fromkeys(candidates):
        try:
            return _decode(http.get(url, retries=1))
        except Exception as err:  # noqa: BLE001
            last_err = err
    raise RuntimeError(f"H-1B employer data unavailable: {last_err}")
