"""Detect adverts placed by recruitment agencies / consultancies rather than the employer."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .text import normalise_company

# Words that almost only appear in agency names.
_NAME_RE = re.compile(
    r"\b(recruit\w*|staffing|resourcing|personnel|headhunt\w*|executive search|search (and|&) selection|"
    r"talent (solutions|partners)|employment (agency|business|services)|locums?|"
    r"appointments|selection ltd|workforce solutions|job(s)? agency|interim (partners|solutions))\b", re.I)

# Standard agency wording in advert text.
_TEXT_RE = re.compile(
    r"(acting as an employment (agency|business)|is an employment (agency|business)|"
    r"on behalf of (our|a|an|the) (client|leading|well|global|established|prestigious|fast)|"
    r"\bour client (is|are|has|seeks|requires|operates|based|,)|we are (currently )?recruiting (for|on behalf of) (a|an|our)|"
    r"(recruitment|staffing) (agency|consultancy) (acting|specialising|specializing)|"
    r"we are an? (specialist )?(recruitment|staffing) (agency|consultancy|business|company)|"
    r"your (recruitment )?consultant will|please contact .{0,40} consultant)", re.I)


class AgencyFilter:
    def __init__(self, names: set[str], allow: set[str]):
        self._names = names
        self._allow = allow

    @classmethod
    def load(cls, path: Path) -> "AgencyFilter":
        cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls({normalise_company(n) for n in cfg.get("agencies", [])},
                   {normalise_company(n) for n in cfg.get("never_agency", [])})

    def is_agency(self, company: str, description: str = "") -> bool:
        key = normalise_company(company)
        if key in self._allow:
            return False
        if key in self._names or any(key.startswith(n + " ") for n in self._names if n):
            return True
        if _NAME_RE.search(company or ""):
            return True
        return bool(_TEXT_RE.search(description or ""))
