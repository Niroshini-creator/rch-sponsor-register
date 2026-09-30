"""Official registers of licensed visa sponsors.

* UK  — Home Office "Register of licensed sponsors: workers" (CSV, updated daily).
* NL  — IND public register of recognised sponsors (regular labour & highly skilled migrants).

Other EU countries have no public sponsor register; for those, jobs are only kept
when the advert (or the source) explicitly offers visa sponsorship.
"""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from . import http
from .text import normalise_company

UK_REGISTER_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
NL_REGISTER_PAGE = ("https://ind.nl/en/public-register-recognised-sponsors/"
                    "public-register-regular-labour-and-highly-skilled-migrants")

REGISTER_COUNTRY = {"UK Home Office": "GB", "NL IND": "NL"}


@dataclass
class SponsorEntry:
    name: str
    register: str
    town: str = ""
    rating: str = ""
    routes: set[str] = field(default_factory=set)


class SponsorIndex:
    def __init__(self) -> None:
        self._by_name: dict[str, SponsorEntry] = {}
        self.counts: dict[str, int] = {}

    def add(self, entry: SponsorEntry) -> None:
        self.counts[entry.register] = self.counts.get(entry.register, 0) + 1
        # Register names often read "Legal Name Ltd T/A Trading Name": index both halves.
        for part in re.split(r"\bt/a\b|\btrading as\b", entry.name, flags=re.I):
            key = normalise_company(part)
            if not key:
                continue
            existing = self._by_name.get(key)
            if existing and existing.register == entry.register:
                existing.routes |= entry.routes
            else:
                self._by_name.setdefault(key, entry)

    def lookup(self, company: str) -> SponsorEntry | None:
        return self._by_name.get(normalise_company(company))

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
