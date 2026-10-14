"""Score one job against one candidate profile and label everything a recruiter checks before sending it on.

Match % (0-100, explained in `reasons`) is CV fit only: title 50 · skills 40 · level 10.
Visa sponsorship, security clearance, driving licence and visa pay are shown as separate labels, never folded into
the percentage, so a 90% role that needs SC clearance still reads as 90% and says SC clearance.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from jobfeed import salary
from jobfeed.classify import ENGLISH_SPEAKING_COUNTRIES
from jobfeed.models import Job

from . import checks, taxonomy

TIER_FACTOR = {1: 1.0, 2: 0.94, 3: 0.86}
TITLE_LITERAL, TITLE_FAMILY, TITLE_PARTIAL, TITLE_OTHER = 50, 44, 30, 32
SKILL_MAX, SKILL_EXTRACT_MAX, SKILLS_FOR_FULL = 40, 22, 5
EXTRACT_CHARS = 600           # shorter adverts are extracts (the shared feed keeps ~400 characters)

# sponsorship status -> (label shown, sort rank: lower is better, offered?)
SPONSORSHIP = {
    "confirmed": ("Sponsorship offered", 0, True),
    "possible": ("Sponsorship may be available", 1, True),
    "licensed_sponsor": ("Licensed sponsor (advert silent)", 2, True),
    "employer_visa": ("Employer provides visa", 2, True),
    "graduate_route": ("Not sponsoring, open to Graduate visa holders", 4, False),
    "stamp_1g": ("No sponsorship evidence (Ireland: open to Stamp 1G holders only)", 5, False),
    "unverified": ("Employer not on sponsor register", 5, False),
    "agency": ("Agency advert, end employer unknown", 5, False),
    "not_sponsored": ("Sponsorship not offered", 6, False),
}
_VERY_SENIOR = re.compile(r"\b(director|head of|vice president|vp|avp|svp|chief|principal|partner)\b", re.I)
_SENIOR = re.compile(r"\b(senior|lead|manager|staff|sr\.?)\b", re.I)
_JUNIOR = re.compile(r"\b(junior|graduate|trainee|entry[- ]level|associate)\b", re.I)
_ASSISTANT = re.compile(r"\b(assistant|intern(ship)?|apprentice(ship)?|placement)\b", re.I)


class Matcher:
    def __init__(self, profile: dict, tax: taxonomy.Taxonomy | None = None):
        self.profile = profile
        self.tax = tax or taxonomy.load()
        self.years = float(profile.get("experience_years") or 0)
        self.held = (profile.get("clearance") or {}).get("held", "none")
        self.licence = profile.get("driving_licence")
        visa = profile.get("visa") or {}
        self.needs_sponsorship = visa.get("sponsorship", "required") != "not_needed"
        self.new_entrant = bool(visa.get("new_entrant"))
        self.english_only = profile.get("english_only", True)
        self.tracks = {t["name"]: [(s, taxonomy.keyword_re(s)) for s in t.get("skills", [])] for t in profile["tracks"]}
        self.cv_for = {t["name"]: t.get("cv") or t["name"] for t in profile["tracks"]}
        every = {}
        for skills in self.tracks.values():
            for s, rx in skills:
                every[s] = rx
        self.all_skills = list(every.items())
        self.roles = []
        for r in profile["roles"]:
            self.roles.append({**r, "tokens": taxonomy.tokens(r["title"]),
                               "literal": re.compile(r"(?<![a-z0-9])" + re.escape(r["title"].lower()) + r"(?![a-z0-9])")})
        self.family_tier: dict[str, tuple[int, str]] = {}
        for r in sorted(self.roles, key=lambda r: r["tier"]):
            if r.get("family"):
                self.family_tier.setdefault(r["family"], (r["tier"], r["track"]))
        self.also = set(profile.get("also_consider", []))

    # ------------------------------------------------------------------ title
    def _title(self, title: str) -> tuple[float, dict] | None:
        low = title.lower()
        best: tuple[float, dict] | None = None
        words = taxonomy.tokens(title)
        for r in self.roles:
            if r["literal"].search(low):
                base, why = TITLE_LITERAL, f"title contains the target role “{r['title']}”"
            elif r.get("family") and self.tax.families[r["family"]].title_match(title):
                base, why = TITLE_FAMILY, f"title is a {self.tax.families[r['family']].label} role"
            elif len(words & r["tokens"]) >= 2 and len(words & r["tokens"]) / len(words | r["tokens"]) >= 0.6:
                base, why = TITLE_PARTIAL, f"title is close to “{r['title']}”"
            else:
                continue
            pts = base * TIER_FACTOR.get(r["tier"], 0.86)
            if best is None or pts > best[0]:
                best = (pts, {"role": r["title"], "family": r.get("family"), "tier": r["tier"], "track": r["track"], "why": why})
        if best:
            return best
        family = self.tax.family_for_title(title)
        if family and family in self.also:
            return TITLE_OTHER, {"role": self.tax.families[family].label, "family": family, "tier": 4,
                                       "track": None, "why": f"{self.tax.families[family].label}: another route for this skill set"}
        return None

    # ------------------------------------------------------------------ level
    def _level(self, title: str) -> tuple[int, str, str]:
        if _VERY_SENIOR.search(title) and self.years < 9:
            return 0, "0 leadership level", "More senior than the CV"
        if _SENIOR.search(title):
            return (3, "+3 senior title", "Senior level") if self.years < 5 else (8, "+8 senior title", "")
        if _ASSISTANT.search(title):
            return 4, "+4 assistant-level title", "Assistant level, below the CV"
        if _JUNIOR.search(title):
            return 6, "+6 junior/graduate title", ""
        return 10, "+10 level fits the CV", ""

    # ------------------------------------------------------------------ visa pay
    def visa_pay(self, job: dict) -> dict:
        if not self.needs_sponsorship:
            return {"status": "", "note": "", "required": 0}
        j = Job(source="", source_id="", title=job.get("title", ""), company="", location="", country=job.get("country", "GB"),
                url="", posted_at=datetime.now(timezone.utc), domain=job.get("domain", ""), sector=job.get("sector", ""))
        limits = salary.thresholds(j)
        if not limits:
            return {"status": "", "note": "", "required": 0}
        full, lowest = limits
        need = lowest if self.new_entrant else full
        cur = salary.currency(j.country)
        rng = salary.annual_range(job.get("salary", ""), j.country)
        who = "new-entrant rate" if self.new_entrant and lowest != full else "minimum"
        if not rng:
            return {"status": "unstated", "required": need, "note": f"Pay not stated. Skilled Worker {who} is {cur}{need:,}."}
        low, high = rng
        if low >= need:
            return {"status": "meets", "required": need, "note": f"Pay meets the {cur}{need:,} Skilled Worker {who}."}
        if high >= need:
            return {"status": "partial", "required": need, "note": f"Only the top of the range reaches the {cur}{need:,} {who}."}
        return {"status": "below", "required": need, "note": f"Pay tops out below the {cur}{need:,} Skilled Worker {who}: cannot be sponsored at this pay."}

    # ------------------------------------------------------------------ whole job
    def evaluate(self, job: dict) -> dict | None:
        title = job.get("title", "")
        found = self._title(title)
        if not found:
            return None
        title_pts, info = found
        text = f"{title}\n{job.get('full_text') or job.get('description', '')}"
        extract = len(job.get("full_text") or job.get("description", "")) < EXTRACT_CHARS
        skills = self.tracks.get(info["track"]) if info["track"] else self.all_skills
        hits = [s for s, rx in (skills or []) if rx.search(text)]
        skill_pts = (SKILL_EXTRACT_MAX if extract else SKILL_MAX) * min(1.0, len(hits) / SKILLS_FOR_FULL)
        level_pts, level_why, level_flag = self._level(title)
        total = round(title_pts + skill_pts + level_pts)
        reasons = [f"+{round(title_pts)} {info['why']}"]
        reasons.append(f"+{round(skill_pts)} {len(hits)} CV skill(s) found in the advert" + (" (extract only)" if extract else ""))
        reasons.append(level_why)

        status = job.get("sponsorship", "unverified")
        label, rank, offered = SPONSORSHIP.get(status, SPONSORSHIP["unverified"])
        clear = checks.clearance(text, self.held)
        if extract and clear["level"] == "none":
            clear["label"] = "No clearance in the extract: check the advert"
        licence = checks.driving_licence(text, self.licence)
        nationality = checks.nationality_restriction(text)
        pay = self.visa_pay(job)
        family = self.tax.families.get(info["family"]) if info["family"] else None
        sponsor_note = self.tax.sponsor_notes.get(family.sponsor, "") if family else ""

        flags = [f for f in (level_flag,) if f]
        routes = job.get("sponsor_routes") or []
        # Route names are the UK register's; other countries' registers name theirs differently.
        no_route = (job.get("country") == "GB" and bool(routes) and status == "licensed_sponsor"
                    and not any("skilled worker" in r.lower() for r in routes))
        if no_route:
            flags.append("Sponsor licence does not list the Skilled Worker route")
        hidden = []
        # Outside the English-speaking countries, an advert in another language or asking for one is no use to this candidate.
        if self.english_only and job.get("country") not in ENGLISH_SPEAKING_COUNTRIES and job.get("english") is False:
            flags.append("Advert is not in English or asks for another language")
            hidden.append("language")
        if nationality["restricted"]:
            flags.append("Reserved for the country's own nationals")
            hidden.append("nationals_only")
        if no_route and self.needs_sponsorship:
            hidden.append("no_skilled_worker_route")
        if clear["blocks"]:
            hidden.append("clearance")
        if self.needs_sponsorship and not offered:
            hidden.append("no_sponsorship")
        if pay["status"] == "below":
            hidden.append("pay_below_visa")
        if licence["status"] == "missing" and licence["need"] == "required":
            hidden.append("licence")
        return {
            "match": max(0, min(100, total)), "reasons": reasons, "skills_matched": hits[:12], "evidence": "extract" if extract else "full",
            "tier": info["tier"], "role": info["role"], "family": info["family"], "family_label": family.label if family else "",
            "track": info["track"], "cv_to_use": self.cv_for.get(info["track"], "") if info["track"] else "",
            "sponsorship": status, "sponsorship_label": label, "sponsorship_rank": rank, "sponsorship_offered": offered,
            "sponsorability": family.sponsor if family else "check", "sponsorability_note": sponsor_note,
            "clearance": clear, "driving_licence": licence, "nationality": nationality, "work_mode": checks.work_mode(text, job.get("location", "")),
            "visa_pay": pay, "flags": flags, "hidden_by_default": hidden,
        }
