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
# A job with no target title is still shown when its advert uses many of the CV's skills and keywords (tier 4).
TITLE_KEYWORD, KEYWORD_MIN, KEYWORD_MIN_EXTRACT = 24, 6, 4
EXTRACT_CHARS = 600           # shorter adverts are extracts (the shared feed keeps ~400 characters)

# sponsorship status -> (label shown, sort rank: lower is better, offered?)
LOCAL = {"IN"}      # countries where the candidate is a local and needs no visa
RIGHTS = {"us_opt": "US", "ie_stamp_1g": "IE"}      # visa.work_rights key -> country where it lets the holder work without a sponsor
RIGHT_LABELS = {("US", "graduate_route"): "No sponsorship, open to OPT holders", ("US", "not_sponsored"): "No sponsorship offered: check the advert accepts OPT",
                ("IE", "stamp_1g"): "No sponsorship needed: open to Stamp 1G holders"}
SPONSORSHIP = {
    "confirmed": ("Sponsorship offered", 0, True),
    "possible": ("Sponsorship may be available", 1, True),
    "licensed_sponsor": ("Licensed sponsor (advert silent)", 2, True),
    "employer_visa": ("Employer provides visa", 2, True),
    "graduate_route": ("Not sponsoring, open to Graduate visa holders", 4, False),
    "local": ("India role: no visa needed", 2, True),
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
        # Work rights that need no sponsor in one country: US OPT / STEM OPT, Irish Stamp 1G (Graduate visa is the sponsorship answer for GB).
        self.rights = {RIGHTS[k] for k in (visa.get("work_rights") or []) if k in RIGHTS}
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

    def _skills_for(self, info: dict) -> list:
        """CV skills for the role's CV, plus the keywords of the role's own domain (a role from an attached document may be
        outside what the CV shows, e.g. marketing roles on a business analyst CV)."""
        base = self.tracks.get(info["track"]) if info["track"] else self.all_skills
        fam = self.tax.families.get(info.get("family") or "")
        if not fam:
            return base or []
        have = {s for s, _ in (base or [])}
        return list(base or []) + [(t, rx) for t, rx in fam.keywords if t not in have]

    @staticmethod
    def _hits(skills: list, text: str, kw: set | None) -> list[str]:
        """Skills found in the advert: by the feed's digest of the whole advert when there is one, else in the text."""
        return [s for s, rx in (skills or []) if (s in kw if kw is not None else rx.search(text))]

    def _keyword_match(self, text: str, extract: bool, kw: set | None) -> tuple[float, dict] | None:
        best_name, best = None, []
        for name, skills in self.tracks.items():
            hits = self._hits(skills, text, kw)
            if len(hits) > len(best):
                best_name, best = name, hits
        if best_name is None or len(best) < (KEYWORD_MIN_EXTRACT if extract else KEYWORD_MIN):
            return None
        return TITLE_KEYWORD, {"role": "Matched on CV keywords", "family": None, "tier": 4, "track": best_name,
                               "why": f"no target title, but the advert uses {len(best)} keywords from your CV"}

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
    def needs_for(self, job: dict) -> bool:
        """Whether this candidate needs the employer to sponsor them for this job (not if they hold work rights in its country)."""
        return self.needs_sponsorship and job.get("country") not in self.rights and job.get("country") not in LOCAL

    def india_pay(self, job: dict) -> dict:
        """Pay against the candidate's minimum (lakhs per annum) for a role in India."""
        need = float(self.profile.get("india_min_lpa", 8)) * 100_000
        rng = salary.inr_range(job.get("salary", ""))
        if not rng:
            return {"status": "unstated", "required": need, "note": f"Pay not stated. You asked for ₹{need / 100_000:g} LPA or more."}
        low, high = rng
        if low >= need:
            return {"status": "meets", "required": need, "note": f"Pay meets your ₹{need / 100_000:g} LPA minimum."}
        if high >= need:
            return {"status": "partial", "required": need, "note": f"Only the top of the range reaches your ₹{need / 100_000:g} LPA minimum."}
        return {"status": "below", "required": need, "note": f"Pay tops out below your ₹{need / 100_000:g} LPA minimum."}

    def visa_pay(self, job: dict) -> dict:
        if job.get("country") in LOCAL:
            return self.india_pay(job)
        if not self.needs_for(job):
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
        # The feed publishes 400 characters of each advert plus a digest of the whole advert (keywords, clearance / licence /
        # nationality sentences, length); a full_text read by the board builder takes priority over the digest.
        full = job.get("full_text") or ""
        body = full or job.get("description", "")
        signals = "" if full else job.get("signals", "")
        text = f"{title}\n{body}" + (f"\n{signals}" if signals else "")
        kw = set(job["kw"]) if not full and job.get("text_len") and job.get("kw") is not None else None
        extract = (len(full) if full else max(job.get("text_len") or 0, len(body))) < EXTRACT_CHARS
        found = self._title(title) or self._keyword_match(text, extract, kw)
        if not found:
            return None
        title_pts, info = found
        skills = self._skills_for(info)
        hits = self._hits(skills, text, kw)
        skill_pts = (SKILL_EXTRACT_MAX if extract else SKILL_MAX) * min(1.0, len(hits) / SKILLS_FOR_FULL)
        level_pts, level_why, level_flag = self._level(title)
        total = round(title_pts + skill_pts + level_pts)
        reasons = [f"+{round(title_pts)} {info['why']}"]
        reasons.append(f"+{round(skill_pts)} {len(hits)} CV skill(s) found in the advert" + (" (extract only)" if extract else ""))
        reasons.append(level_why)

        status = job.get("sponsorship", "unverified")
        label, rank, offered = SPONSORSHIP.get(status, SPONSORSHIP["unverified"])
        right_label = RIGHT_LABELS.get((job.get("country"), status)) if job.get("country") in self.rights else None
        if right_label:                            # holds US OPT / Irish Stamp 1G: a role that needs no sponsor is a fit
            label, rank, offered = right_label, 3, True
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
        needs = self.needs_for(job)
        if no_route and needs:
            hidden.append("no_skilled_worker_route")
        if clear["blocks"]:
            hidden.append("clearance")
        if needs and not offered:
            hidden.append("no_sponsorship")
        if pay["status"] == "below":
            hidden.append("pay_below_minimum" if job.get("country") in LOCAL else "pay_below_visa")
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
