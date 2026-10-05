"""Transparent 0-100 match score between a job advert and the candidate's CV.

Points (max): title 40 · telecom OSS/BSS domain keywords 35 · network technology 10 ·
architecture practice / cloud 5 · seniority 5 · salary 5. Penalties apply for junior roles,
pay below the candidate's minimum and unverified visa sponsorship. Every point is explained in `reasons`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- hard exclusions ---------------------------------------------------------------------------
# The candidate holds no SC / DV clearance, so adverts that need one are dropped.
CLEARANCE_RE = re.compile(
    r"\b(?:SC|DV|CTC|NPPV\s?\d?)\s*(?:/|,|or|and|&)?\s*(?:SC|DV)?\s*(?:clearance|cleared|level|vetting|eligib\w*)\b"
    r"|\b(?:security\s+clear(?:ance|ed)|developed\s+vetting|counter[- ]terrorist check|active (?:sc|dv))\b"
    r"|\b(?:eligible|able|willing)\s+(?:to|for)\s+(?:obtain|hold|gain|get|achieve)?\s*(?:an?\s+)?(?:SC|DV)\b",
    re.I,
)
# Case-sensitive guard so the lone words "sc"/"dv" in prose are not mistaken for clearance.
CLEARANCE_STRICT_RE = re.compile(r"\b(?:SC|DV)\s*(?:/|or|and)?\s*(?:SC|DV)?\s*(?:clearance|cleared|level|vetting)\b")

# --- scoring tables ----------------------------------------------------------------------------
TITLE_RULES: list[tuple[re.Pattern, int, str]] = [(re.compile(p, re.I), pts, why) for p, pts, why in (
    (r"\b(oss\s*/?\s*bss|bss\s*/?\s*oss)\b.*\b(architect|design authority|consultant)", 40, "OSS/BSS architect title"),
    (r"\boss\b.*\barchitect|\barchitect.*\boss\b", 38, "OSS architect title"),
    (r"\b(telecoms?|telco|communications?)\b.*\b(solutions?|technical|enterprise|network)\s+architect", 38, "Telecom architect title"),
    (r"\b(network|resource|service)\s+inventory\b.*\b(architect|specialist|lead)", 36, "Network inventory architect title"),
    (r"\b(order management|service fulfil?ment|provisioning|assurance|orchestration)\b.*\barchitect", 34, "Fulfilment / order-mgmt architect title"),
    (r"\b(network|transport|transmission|design|ip|access)\b.*\barchitect|\barchitect.*\b(network|transport)", 32, "Network architect title"),
    (r"\bnetwork\s+(capacity|planning)\b|\bcapacity\s+(planning|management)\b.*\bnetwork", 28, "Network capacity / planning title"),
    (r"\bpre-?sales?\b.*\barchitect|\barchitect.*\bpre-?sales?\b", 24, "Presales architect title"),
    (r"\bsolutions?\s+architect\b|\btechnical\s+architect\b|\benterprise\s+architect\b", 20, "Solution / technical architect title"),
    (r"\barchitect\b", 10, "Architect title"),
)]

# (pattern, points) — each counted once; the group is capped.
DOMAIN_KEYWORDS: list[tuple[re.Pattern, int]] = [(re.compile(p, re.I), pts) for p, pts in (
    (r"\boss\s*/\s*bss\b|\boss\b.{0,5}\bbss\b|\bbss\b.{0,5}\boss\b", 8),
    (r"\boss\b", 4), (r"\bbss\b", 4),
    (r"\bnetcracker\b|\bcramer\b|\bgranite\b|\bamdocs\b|\bnetwork inventory\b|\bresource inventory\b|\binventory (?:management|system)", 7),
    (r"\bnetwork discovery\b|\bdiscovery (?:and|&) (?:synchron|reconcil)|\bsynchronis|\breconciliation\b", 5),
    (r"\border management\b|\bservice fulfil?ment\b|\bprovisioning\b|\bservice (?:activation|orchestration)\b", 5),
    (r"\bcapacity (?:planning|management)\b|\bnetwork planning\b", 5),
    (r"\bservice assurance\b|\bservice model(?:l)?ing\b", 3),
    (r"\btm ?forum\b|\bopen ?api\b|\be-?tom\b|\bshared information\b|\bframeworx\b", 4),
    (r"\bhigh[- ]level design\b|\bhld\b|\bdetailed design\b|\bdesign authority\b|\barchitecture review\b", 3),
    (r"\btelecom\w*\b|\btelco\b|\bcsp\b|\bcommunications service provider", 4),
    (r"\bwholesale\b|\bwayleave\b|\bopenreach\b", 2),
)]
DOMAIN_CAP = 35

TECH_KEYWORDS: list[tuple[re.Pattern, int]] = [(re.compile(p, re.I), pts) for p, pts in (
    (r"\bgpon\b|\bxgs-?pon\b|\bftt[ph]\b|\bfibre\b|\bfiber\b", 3),
    (r"\bdocsis\b|\bhfc\b|\bcable\b", 3),
    (r"\bip/?mpls\b|\bmpls\b|\bsegment routing\b", 3),
    (r"\bsdh\b|\bdwdm\b|\boptical transport\b|\btransmission\b", 3),
    (r"\bethernet\b|\bcarrier ethernet\b|\bmef\b", 2),
    (r"\b5g\b|\bran\b|\bcore network\b", 2),
)]
TECH_CAP = 10

PRACTICE_KEYWORDS: list[tuple[re.Pattern, int]] = [(re.compile(p, re.I), pts) for p, pts in (
    (r"\bgcp\b|\bgoogle cloud\b", 3),
    (r"\benterprise architecture\b|\bsolution architecture\b|\btogaf\b|\bsecurity by design\b|\bnon-?functional\b", 2),
)]
PRACTICE_CAP = 5

SENIOR_RE = re.compile(r"\b(senior|principal|lead|head of|chief|staff|manager|director)\b", re.I)
JUNIOR_RE = re.compile(r"\b(junior|graduate|trainee|intern(?:ship)?|apprentice|entry[- ]level|assistant)\b", re.I)
IMMEDIATE_RE = re.compile(r"\b(immediate(?:ly)? (?:start|available)|asap|start (?:date )?(?:immediately|within (?:1|2|one|two) weeks?)|urgent(?:ly)? (?:required|need))", re.I)

_AMOUNT_RE = re.compile(r"£?\s*(\d{1,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s*[kK]|\d{4,6})")


def parse_salary(text: str) -> tuple[float | None, float | None]:
    """(low, high) annual GBP from free text; day rates (< 1,500) and unparseable text give (None, None)."""
    values = []
    for m in _AMOUNT_RE.finditer(text or ""):
        raw = m.group(1).replace(",", "").lower().replace(" ", "")
        try:
            v = float(raw[:-1]) * 1000 if raw.endswith("k") else float(raw)
        except ValueError:
            continue
        if v >= 15000:
            values.append(v)
    if not values:
        return None, None
    return min(values), max(values)


@dataclass
class Result:
    score: int
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)


def requires_clearance(text: str) -> bool:
    return bool(CLEARANCE_RE.search(text) or CLEARANCE_STRICT_RE.search(text))


def _group(text: str, table, cap: int) -> tuple[int, list[str]]:
    pts, hits = 0, []
    for pattern, p in table:
        m = pattern.search(text)
        if m:
            pts += p
            hits.append(m.group(0).strip().lower())
    return min(pts, cap), hits


def score_job(title: str, description: str, salary: str = "", min_salary: int = 60000,
              sponsorship: str = "") -> Result:
    text = f"{title}\n{description}"
    reasons: list[str] = []
    flags: list[str] = []
    matched: list[str] = []

    title_pts = 0
    for pattern, pts, why in TITLE_RULES:
        if pattern.search(title):
            title_pts = pts
            reasons.append(f"+{pts} {why}")
            break

    dom, hits = _group(text, DOMAIN_KEYWORDS, DOMAIN_CAP)
    if dom:
        reasons.append(f"+{dom} telecom OSS/BSS keywords")
        matched += hits
    tech, hits = _group(text, TECH_KEYWORDS, TECH_CAP)
    if tech:
        reasons.append(f"+{tech} network technology (GPON/DOCSIS/MPLS/SDH/DWDM…)")
        matched += hits
    prac, hits = _group(text, PRACTICE_KEYWORDS, PRACTICE_CAP)
    if prac:
        reasons.append(f"+{prac} architecture practice / GCP")
        matched += hits

    total = title_pts + dom + tech + prac

    if JUNIOR_RE.search(title):
        total -= 15
        reasons.append("-15 junior-level title")
    elif SENIOR_RE.search(title) or title_pts >= 20:
        total += 5
        reasons.append("+5 senior / architect level")

    _, hi = parse_salary(salary)
    if hi is not None:
        if hi >= min_salary:
            total += 5
            reasons.append(f"+5 pay reaches £{int(min_salary):,}+")
        else:
            total -= 10
            reasons.append(f"-10 pay tops out below £{int(min_salary):,}")
            flags.append("Below salary expectation")
    else:
        flags.append("Salary not stated")

    if sponsorship == "unverified":
        total -= 5
        reasons.append("-5 sponsorship not confirmed")
    if IMMEDIATE_RE.search(text):
        flags.append("Wants immediate start (candidate's notice is 90 days)")

    return Result(score=max(0, min(100, total)), reasons=reasons, flags=flags, matched=sorted(set(matched))[:12])
