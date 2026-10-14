"""Read a CV (PDF or text) and work out which role families it supports, how experienced the person is, and which
skills to match adverts against.

Evidence per family = title hits (the family's title patterns found in the headline and in job-title lines) and
keyword hits (its skills found anywhere). Contact details are never kept: only the name, headline and skills.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from . import taxonomy

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_RANGE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\s*[–—-]\s*"
    r"(?:(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})|(present|current|now|date))", re.I)


def read_text(path: Path) -> str:
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        if not shutil.which("pdftotext"):
            raise RuntimeError("pdftotext (poppler-utils) is needed to read PDF CVs; install it or pass a .txt export")
        return subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True, text=True).stdout
    return path.read_text(encoding="utf-8", errors="replace")


def experience_months(text: str, today: date | None = None) -> int:
    """Months covered by dated roles (overlaps counted once). Education date ranges carry no month, so are skipped."""
    today = today or date.today()
    spans = []
    for m in _RANGE_RE.finditer(text):
        start = int(m.group(2)) * 12 + _MONTHS[m.group(1).lower()]
        end = (int(m.group(4)) * 12 + _MONTHS[m.group(3).lower()]) if m.group(3) else today.year * 12 + today.month
        if end >= start:
            spans.append((start, end + 1))
    spans.sort()
    total, cur_end = 0, None
    for s, e in spans:
        if cur_end is None or s > cur_end:
            total += e - s
            cur_end = e
        elif e > cur_end:
            total += e - cur_end
            cur_end = e
    return total


_EDU = [("PhD", r"\b(ph\.?d|doctorate)\b"), ("Master's", r"\b(mba|m\.?sc|m\.?a\.?|m\.?eng|master'?s?|m\.?tech)\b"),
        ("Bachelor's", r"\b(b\.?tech|b\.?e\.?|b\.?sc|b\.?a\.?|bachelor'?s?|b\.?eng)\b")]


def education(text: str) -> str:
    for label, pattern in _EDU:
        m = re.search(pattern, text, re.I)
        if m:
            tail = m.group(0).upper() if m.group(0).lower() == "mba" else ""
            return f"{label} ({tail})" if tail else label
    return ""


def _name_and_headline(text: str) -> tuple[str, str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    name = lines[0] if lines and len(lines[0].split()) <= 5 and not re.search(r"[@\d]", lines[0]) else ""
    headline = ""
    for l in lines[1:4]:
        if not re.search(r"[@+]|\d{5}|linkedin", l, re.I):
            headline = l
            break
    return name.title() if name.isupper() else name, headline


def _title_text(text: str) -> str:
    """The parts of a CV that name roles: the first lines, and any line carrying a date range or a 'Role | Employer'."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    picked = lines[:3] + [l for l in lines[3:] if _RANGE_RE.search(l) or re.search(r"\S\s\|\s\S", l)]
    return "\n".join(picked)


def scan(text: str, today: date | None = None) -> dict:
    tax = taxonomy.load()
    titles = _title_text(text)
    families = {}
    for key, fam in tax.families.items():
        title_hits = sum(1 for rx in fam.titles if rx.search(titles))
        found = [term for term, rx in fam.keywords if rx.search(text)]
        strength = min(100, 30 * min(title_hits, 2) + 7 * len(found))
        if strength:
            families[key] = {"strength": strength, "title_hits": title_hits, "skills": found}
    name, headline = _name_and_headline(text)
    return {"name": name, "headline": headline, "months": experience_months(text, today),
            "education": education(text), "families": families}


def tier_families(families: dict, tax: taxonomy.Taxonomy | None = None) -> dict[str, int]:
    """family -> tier (1 core, 2 close, 3 stretch, 4 other roles worth a look)."""
    tax = tax or taxonomy.load()
    strength = {k: v["strength"] for k, v in families.items()}
    ranked = sorted(strength, key=strength.get, reverse=True)
    tiers: dict[str, int] = {}
    for k in ranked[:3]:
        if strength[k] >= 55:
            tiers[k] = 1
    for k in ranked:
        if k in tiers:
            continue
        near_t1 = any(k in tax.families[t].adjacent or t in tax.families[k].adjacent
                      for t, tr in list(tiers.items()) if tr == 1)
        if strength[k] >= 30 or (near_t1 and strength[k] >= 15):
            tiers[k] = 2
    for k in ranked:
        if k in tiers:
            continue
        near_t2 = any(k in tax.families[t].adjacent for t, tr in list(tiers.items()) if tr <= 2)
        if strength[k] >= 12 or near_t2:
            tiers[k] = 3
    for t in [t for t, tr in tiers.items() if tr <= 2]:
        for k in tax.families[t].adjacent:
            if k not in tiers:
                tiers[k] = 4
    for k, s in strength.items():
        if k not in tiers and s >= 6:
            tiers[k] = 4
    return tiers


_BULLET_RE = re.compile(r"^\s*(?:[●•▪◦*\-–]|\d{1,2}[.)])\s*(.+)$")
MAX_LOOSE_WORDS, MAX_LOOSE_CHARS = 8, 70


def _expand(raw: str) -> list[str]:
    """One list item -> its role titles: (notes) dropped; "A / B" is two roles; "Marketing Executive / Coordinator" too."""
    title = " ".join(re.sub(r"\([^)]*\)", "", raw).replace(chr(0x200b), "").split()).strip(" -—–")
    parts = [p.strip() for p in re.split(r"\s+/\s+", title) if p.strip()]
    out = []
    for i, part in enumerate(parts):
        if i and len(part.split()) == 1 and len(parts[0].split()) >= 2:
            part = " ".join(parts[0].split()[:-1] + [part])
        out.append(part)
    return out


def _loose_roles(text: str) -> list[dict]:
    """A list with no bullets or numbers: each short line is a title; a comma-separated line of short items is several."""
    roles = []
    for line in text.splitlines():
        line = " ".join(line.replace(chr(0x200b), "").split())
        if not line or "@" in line or "http" in line.lower():
            continue
        if re.search(r"[;,]", line):
            pieces = [x.strip() for x in re.split(r"[;,]", line) if x.strip()]
            if not all(len(x.split()) <= 5 for x in pieces):
                continue                                  # a sentence with commas, not a list of titles
        else:
            pieces = [line]
        for piece in pieces:
            piece = piece.rstrip(".").strip()
            if not piece or len(piece) > MAX_LOOSE_CHARS or not 1 <= len(piece.split()) <= MAX_LOOSE_WORDS:
                continue
            if not re.search(r"[A-Za-z]", piece) or piece.endswith(":"):
                continue
            roles.extend({"title": title, "section": ""} for title in _expand(piece))
    return roles


def parse_role_list(text: str) -> list[dict]:
    """A list of suitable roles: bullet or numbered lines are role titles, other lines are section headings.
    A list with no bullets at all is read line by line (see `_loose_roles`)."""
    roles, section, bulleted = [], "", False
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _BULLET_RE.match(line)
        if not m:
            section = line.strip().strip("●•").strip()
            continue
        bulleted = True
        for title in _expand(m.group(1)):
            roles.append({"title": title, "section": section})
    return roles if bulleted else _loose_roles(text)
