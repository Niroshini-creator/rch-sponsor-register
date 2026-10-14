"""Role families (roles.json) compiled for matching."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROLES_FILE = Path(__file__).resolve().parent / "roles.json"
_STOP = {"and", "the", "of", "for", "a", "an", "in", "to", "with", "or", "&", "/", "-", "senior", "junior", "lead",
         "graduate", "associate", "entry", "level"}


def keyword_re(term: str) -> re.Pattern:
    """A taxonomy keyword is a regex fragment; match it as a whole word/phrase."""
    return re.compile(r"(?<![a-z0-9])(?:" + term + r")(?![a-z0-9])", re.I)


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in _STOP and len(w) > 1}


@dataclass
class Family:
    key: str
    label: str
    titles: list[re.Pattern]
    keywords: list[tuple[str, re.Pattern]]
    searches: list[str]
    adjacent: list[str]
    sponsor: str
    _tokens: set[str] = field(default_factory=set)

    def title_match(self, title: str) -> int:
        """Length of the longest title pattern match (0 = none); longer = more specific."""
        best = 0
        for rx in self.titles:
            m = rx.search(title)
            if m:
                best = max(best, len(m.group(0)))
        return best


@dataclass
class Taxonomy:
    families: dict[str, Family]
    sponsor_notes: dict[str, str]

    def family_for_title(self, title: str) -> str | None:
        """The family whose title pattern matches most specifically; token overlap with its searches as a fallback."""
        scored = [(f.title_match(title), k) for k, f in self.families.items()]
        best = max(scored)
        if best[0]:
            return best[1]
        want = tokens(title)
        if not want:
            return None
        top, key = 0.0, None
        for k, f in self.families.items():
            for cand in f.searches + [f.label]:
                have = tokens(cand)
                if have and len(want & have) >= 2:   # one shared word ("analyst") says nothing
                    j = len(want & have) / len(want | have)
                    if j > top:
                        top, key = j, k
        return key if top >= 0.6 else None


@lru_cache(maxsize=1)
def load(path: Path = ROLES_FILE) -> Taxonomy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    families = {}
    for key, f in raw["families"].items():
        families[key] = Family(
            key=key, label=f["label"], titles=[re.compile(p, re.I) for p in f["titles"]],
            keywords=[(k, keyword_re(k)) for k in f["keywords"]], searches=f["searches"],
            adjacent=f.get("adjacent", []), sponsor=f.get("sponsor", "check"))
    return Taxonomy(families, raw["sponsor_notes"])
