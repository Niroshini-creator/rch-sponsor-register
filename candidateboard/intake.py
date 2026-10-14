"""Turn CVs + the recruiter's suitable-roles list + visa facts into an editable candidate profile.

Everything the scan decides (tiers, tracks, skills, extra roles) is written to profile.json as plain data, so a
recruiter can correct it by editing the file; the daily build only reads the profile.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import cv, taxonomy

SKILLS_PER_TRACK = 60
SUGGEST_MIN_STRENGTH = 30     # only suggest titles for families the CV clearly supports


GENERIC_SKILLS = {"word", "excel", "support", "customer", "sales", "reporting", "coordination", "sap", "plan", "content", "records",
                  "documentation", "administration", "tickets?", "sla"}


def generic_terms(tax: taxonomy.Taxonomy) -> set[str]:
    """Skills too common to tell roles apart: on the stoplist, or listed under three or more role families."""
    counts: dict[str, int] = {}
    for fam in tax.families.values():
        for term, _ in fam.keywords:
            counts[term] = counts.get(term, 0) + 1
    return GENERIC_SKILLS | {t for t, n in counts.items() if n >= 3}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _track_for_section(section: str, tracks: list[str]) -> str | None:
    words = taxonomy.tokens(section) - {"cv"}
    best, top = None, 0.0
    for t in tracks:
        have = taxonomy.tokens(t)
        score = len(words & have) / len(have) if have else 0
        if score > top:
            best, top = t, score
    return best if top >= 0.67 else None


def build_profile(cvs: dict[str, Path], roles_text: str = "", *, name: str = "", slug: str = "", location: str = "",
                  visa: dict | None = None, clearance: str = "none", driving_licence: bool | None = None,
                  current_status: str = "", notes: str = "", today: date | None = None) -> dict:
    tax = taxonomy.load()
    scans = {track: cv.scan(cv.read_text(path), today) for track, path in cvs.items()}

    # One strength per family across all CVs, remembering which CV shows it best.
    combined: dict[str, dict] = {}
    for track, s in scans.items():
        for fam, ev in s["families"].items():
            if fam not in combined or ev["strength"] > combined[fam]["strength"]:
                combined[fam] = {**ev, "track": track}
    tiers = cv.tier_families(combined, tax)

    generic = generic_terms(tax)
    tracks = []
    for track, s in scans.items():
        skills: list[str] = []
        for fam, ev in sorted(s["families"].items(), key=lambda kv: -kv[1]["strength"]):
            if ev["strength"] >= 12:
                skills += [k for k in ev["skills"] if k not in skills and k not in generic]
        first = next(iter(scans.values()))
        tracks.append({"name": track, "cv": Path(cvs[track]).name, "headline": s["headline"],
                       "skills": skills[:SKILLS_PER_TRACK]})
    first = next(iter(scans.values()))

    roles, seen = [], set()

    def add(title: str, family: str | None, source: str, section: str = "") -> None:
        key = title.lower()
        if key in seen:
            return
        seen.add(key)
        named_track = _track_for_section(section, list(cvs)) if section else None
        track = named_track or (combined[family]["track"] if family in combined else list(cvs)[0])
        tier = tiers.get(family, 3) if family else 3
        if section and not named_track:
            # The recruiter filed this under a CV that does not exist yet (e.g. "With Retail CV"), so it cannot be a
            # first-choice role: there is nothing to apply with until that CV is written.
            tier = max(tier, 3)
        roles.append({"title": title, "family": family, "tier": min(tier, 3), "track": track, "source": source})

    for item in cv.parse_role_list(roles_text) if roles_text else []:
        add(item["title"], tax.family_for_title(item["title"]), "recruiter list", item["section"])
    # Suggest roles for families the CV supports but the recruiter's list does not cover.
    covered = {r["family"] for r in roles}
    for fam, tier in tiers.items():
        if tier <= 2 and fam not in covered and combined[fam]["strength"] >= SUGGEST_MIN_STRENGTH:
            for title in tax.families[fam].searches[:2]:
                add(title, fam, "suggested from CV")
    roles.sort(key=lambda r: (r["tier"], r["track"], r["title"]))

    months = max(s["months"] for s in scans.values())
    return {
        "slug": slug or slugify(name or first["name"]),
        "name": name or first["name"],
        "headline": first["headline"],
        "base_location": location,
        "country": "GB",
        "countries": ["GB"],
        "current_status": current_status,
        "experience_years": round(months / 12, 1),
        "education": first["education"],
        "visa": visa or {"type": "", "label": "", "expires": "", "sponsorship": "required", "new_entrant": False},
        "clearance": {"held": clearance},
        "driving_licence": driving_licence,
        "window_days": 7,
        "min_match": 40,
        "tracks": tracks,
        "roles": roles,
        "also_consider": sorted(k for k, t in tiers.items() if t == 4 or k not in {r["family"] for r in roles}),
        "family_evidence": {k: {"strength": v["strength"], "tier": tiers.get(k)} for k, v in
                            sorted(combined.items(), key=lambda kv: -kv[1]["strength"]) if v["strength"] >= 12},
        "notes": notes,
    }


def write_profile(profile: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
