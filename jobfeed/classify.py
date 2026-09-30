"""Rules that label each job: sponsorship evidence, role domain, employer sector, tier and size."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import Job
from .text import normalise_company

# ----------------------------------------------------------------------------- sponsorship
_POSITIVE = [re.compile(p, re.I) for p in (
    r"visa sponsorship (is |will be |may be |can be )?(available|offered|provided|considered|possible)",
    r"sponsorship (is |will be |may be |can be )?(available|offered|provided|considered)",
    r"(able|willing|happy|pleased|can|will) to (offer|provide|consider|support) (visa |skilled worker |a )?sponsorship",
    r"eligible for (visa |skilled worker )?sponsorship",
    r"(we|employer|trust|university|school) (can |will |may )?(offer|provide|sponsor)s? (a )?(skilled worker |work )?visa",
    r"skilled worker (visa|route) sponsorship",
    r"certificate of sponsorship",
    r"require[sd]? .{0,40}sponsorship .{0,80}(welcome|considered|encouraged)",
    r"\bvisa (support|assistance|sponsorship) (provided|available|offered|included)",
    r"\b(eu )?blue card\b",
    r"relocation (and|&) visa (support|assistance)",
    r"work permit (support|assistance|sponsorship)",
    r"\bsponsorship\s*:\s*(yes|available)",
)]
_STRONG_NEGATIVE = [re.compile(p, re.I) for p in (
    r"(unable|not able|cannot|can ?not|can't|do not|don't|does not|doesn't|won't|will not|are not able|is not able)"
    r" (to )?(offer|provide|consider|support|accept)?\s*(visa |skilled worker |any )?sponsor",
    r"\bno (visa |skilled worker )?sponsorship",
    r"sponsorship (is |will )?not (be )?(available|offered|provided|possible|considered)",
    r"not eligible for (visa |skilled worker )?sponsorship",
    r"without (the need for |requiring |requirement for )?(visa |skilled worker |any )?sponsorship",
    r"sponsorship\s*:\s*no\b",
)]
_WEAK_NEGATIVE = [re.compile(p, re.I) for p in (
    r"must (already )?(have|hold) (the |a |full |existing |an existing )*right to work",
)]


def sponsorship_signal(text: str) -> str:
    """Return "positive", "negative" or "" (no statement) for an advert's text."""
    if any(p.search(text) for p in _STRONG_NEGATIVE):
        return "negative"
    if any(p.search(text) for p in _POSITIVE):
        return "positive"
    if any(p.search(text) for p in _WEAK_NEGATIVE):
        return "negative"
    return ""


# ----------------------------------------------------------------------------- sector (employer type)
SECTORS = ["NHS & Healthcare", "University & Research Institute", "School & College",
           "Public Sector & Government", "Private Sector", "Charity & Non-profit"]

_SECTOR_RULES: list[tuple[str, re.Pattern]] = [
    ("NHS & Healthcare", re.compile(
        r"\bnhs\b|\bhealth ?(board|care|service)s?\b|\bhospitals?\b|foundation trust|\bccg\b|\bicb\b|"
        r"integrated care|\bgp (surgery|practice)\b|medical (centre|practice)|\bklinik|\bclinic\b", re.I)),
    ("University & Research Institute", re.compile(
        r"\buniversit|\bhochschule\b|\bcollege london\b|imperial college|king's college|\binstitute of\b|"
        r"research (institute|council|centre)|\bmax planck|fraunhofer|\bcnrs\b|\bukri\b|\bwellcome sanger\b|"
        r"francis crick|\bcern\b|\bembl\b", re.I)),
    ("School & College", re.compile(
        r"\bschools?\b|\bacadem(y|ies)\b|\bcollege\b|multi.academy trust|\bsixth form\b|"
        r"\bgrammar\b|\bprimary\b|\bsecondary\b|\bnursery\b|\bgymnasium\b|\bschule\b", re.I)),
    ("Public Sector & Government", re.compile(
        r"\bcouncil\b|\bgovernment\b|\bministry\b|\bdepartment for\b|\bhm (revenue|treasury|courts)|"
        r"\bcivil service\b|\bpolice\b|\bfire (and|&) rescue\b|\bhome office\b|\bmet office\b|\bofcom\b|"
        r"\bborough\b|\b(local|combined|transport|port|regulatory) authority\b|\bexecutive agency\b|"
        r"\b(environment|food standards|health security|space) agency\b|\bgemeente\b|\bstadt\b|\bbundes|"
        r"\beuropean (union|commission|parliament|central bank|investment bank|medicines agency)\b|\bparliament\b", re.I)),
    ("Charity & Non-profit", re.compile(
        r"\bcharit|\bfoundation\b|\bnon.?profit\b|\bngo\b|\bhousing association\b|\bred cross\b|\boxfam\b", re.I)),
]


def classify_sector(job: Job) -> str:
    for sector, rx in _SECTOR_RULES:
        if rx.search(job.company):
            return sector
    if job.source == "NHS Jobs":
        return "NHS & Healthcare"
    if job.source == "Teaching Vacancies":
        return "School & College"
    return "Private Sector"


# ----------------------------------------------------------------------------- domain (role function)
DOMAINS = ["Technical & Engineering", "Management & Business", "Science & Research",
           "Healthcare & Clinical", "Teaching & Academic", "Finance & Legal", "Other"]

_DOMAIN_RULES: list[tuple[str, re.Pattern]] = [
    ("Healthcare & Clinical", re.compile(
        r"\bnurs(e|ing)\b|\bdoctor\b|\bphysician\b|\bconsultant (in|psychiatrist|surgeon|physician|anaesth|radiolog)|"
        r"\bregistrar\b|\bmidwi|\bradiograph|\bphysiotherap|\boccupational therap|\bparamedic\b|\bpharmacist\b|"
        r"\bclinical\b|\bsurgeon\b|\bspeciality doctor\b|\bpsychiatr|\bpsycholog|\bdentist|\bgp\b|"
        r"\bsonograph|\bhealth care assistant\b|\bcare assistant\b|\bsenior carer\b|\bsupport worker\b", re.I)),
    ("Teaching & Academic", re.compile(
        r"\bteacher\b|\bteaching\b|\blecturer\b|\bprofessor\b|\bsenco\b|\bhead of (department|year|maths|science|english)|"
        r"\btutor\b|\breader in\b|\bassociate professor\b|\bteaching fellow\b|\bdeputy head\b|\bheadteacher\b", re.I)),
    ("Science & Research", re.compile(
        r"\bscientist\b|\bresearch(er| fellow| associate| assistant)\b|\bpostdoc|\bpost-doctoral|\bchemist\b|"
        r"\bbiolog|\bphysicist\b|\blaboratory\b|\blab\b|\bgenomic|\bbioinformatic|\bepidemiolog|\bstatistician\b|"
        r"\bclinical trial|\bpharmacolog|\bmolecular\b|\bmicrobiolog|\bneuroscien|\bphd\b", re.I)),
    ("Technical & Engineering", re.compile(
        r"\bengineer|\bdeveloper\b|\bsoftware\b|\bprogrammer\b|\bdevops\b|\bdata (analyst|engineer|architect)\b|"
        r"\bmachine learning\b|\b(ai|ml)\b|\bcloud\b|\bsecurity analyst\b|\bcyber\b|\barchitect\b|\bit (support|manager)\b|"
        r"\bnetwork\b|\bsysadmin\b|\bsre\b|\bfull.?stack\b|\bfront.?end\b|\bback.?end\b|\bqa\b|\btester\b|"
        r"\btechnician\b|\bcad\b|\bmechanical\b|\belectrical\b|\bcivil engineer|\bsurveyor\b|\bdesigner\b", re.I)),
    ("Finance & Legal", re.compile(
        r"\baccountant\b|\baccounting\b|\bfinanc|\baudit|\btax\b|\bactuar|\bsolicitor\b|\blawyer\b|\blegal\b|"
        r"\bparalegal\b|\bcompliance\b|\brisk analyst\b|\bquant\b|\btreasury\b|\bpayroll\b", re.I)),
    ("Management & Business", re.compile(
        r"\bmanager\b|\bdirector\b|\bhead of\b|\blead\b|\bchief\b|\bproject manag|\bprogramme manag|\bproduct manag|"
        r"\boperations\b|\bconsultant\b|\bbusiness analyst\b|\bstrateg|\bmarketing\b|\bsales\b|\bhr\b|"
        r"\bhuman resources\b|\bprocurement\b|\bsupply chain\b|\blogistics\b|\badministrat|\bofficer\b", re.I)),
]


def classify_domain(job: Job) -> str:
    for text in (job.title, job.description[:600]):
        for domain, rx in _DOMAIN_RULES:
            if rx.search(text):
                return domain
    return "Other"


# ----------------------------------------------------------------------------- tier & size
@dataclass
class TierRules:
    names: dict[str, tuple[int, str]]        # normalised name -> (tier, size)
    patterns: list[tuple[re.Pattern, int, str]]

    @classmethod
    def load(cls, path: Path) -> "TierRules":
        cfg = json.loads(path.read_text(encoding="utf-8"))
        names: dict[str, tuple[int, str]] = {}
        for tier_key, tier in (("tier1", 1), ("tier2", 2), ("tier3", 3)):
            default_size = cfg.get("default_size", {}).get(tier_key, "unknown")
            for entry in cfg.get(tier_key, []):
                if isinstance(entry, str):
                    entry = {"name": entry}
                names[normalise_company(entry["name"])] = (tier, entry.get("size", default_size))
        patterns = [(re.compile(p["regex"], re.I), int(p["tier"]), p.get("size", "unknown"))
                    for p in cfg.get("patterns", [])]
        return cls(names, patterns)

    def classify(self, job: Job) -> tuple[int, str]:
        key = normalise_company(job.company)
        if key in self.names:
            tier, size = self.names[key]
        else:
            tier, size = 3, "unknown"
            for rx, p_tier, p_size in self.patterns:
                if rx.search(job.company):
                    tier, size = p_tier, p_size
                    break
        if size == "unknown":
            size = _size_from_text(job.description)
        return tier, size


_HEADCOUNT_RE = re.compile(r"(\d{1,3}(?:[,.]\d{3})*|\d+)\s*\+?\s*(?:employees|staff|people|colleagues|team members)", re.I)
_SMALL_HINT_RE = re.compile(r"\b(start-?up|early.stage|seed.funded|series a|small team|sme|boutique)\b", re.I)


def _size_from_text(text: str) -> str:
    """UK Companies Act bands: small < 50, medium 50–249, large 250+."""
    m = _HEADCOUNT_RE.search(text)
    if m:
        n = int(re.sub(r"[,.]", "", m.group(1)))
        if n >= 250:
            return "large"
        if n >= 50:
            return "medium"
        if n > 1:
            return "small"
    if _SMALL_HINT_RE.search(text):
        return "small"
    return "unknown"
