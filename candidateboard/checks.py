"""What an advert asks of the candidate beyond skills: security clearance, a driving licence, where the work is done."""

from __future__ import annotations

import re

# Highest level wins. "unspecified" = the advert says clearance/vetting without a level.
CLEARANCE_ORDER = ["none", "dbs", "basic", "unspecified", "nppv", "ctc", "sc", "dv"]
BLOCKING = {"unspecified", "nppv", "ctc", "sc", "dv"}   # a candidate holding no clearance cannot meet these
_LEVELS: list[tuple[str, re.Pattern]] = [
    # Case-sensitive acronyms so the words "sc" / "dv" in prose are not mistaken for clearance.
    ("dv", re.compile(r"\bDV\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|vetting|check|cleared))|\bdv\s+(?:clearance|cleared|vetting)\b|\bdeveloped vetting\b|\bactive DV\b|(?<=/)dv\s+clearance", 0)),
    ("sc", re.compile(r"\bSC\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|vetting|check|cleared|eligib\w*))|\bsc\s+(?:clearance|cleared|vetting)\b|\bactive SC\b|\bsecurity check \(SC\)|\bSC[- ]cleared\b|\b(?:eligible|able|willing)\s+(?:to|for)\s+(?:obtain|hold|gain|get|achieve|undergo)?\s*(?:an?\s+)?SC\b")),
    ("ctc", re.compile(r"\bCTC\b(?=[\s/,&()-]{0,4}(?:clear\w*|level|check))|\bcounter[- ]terroris[tm] check\b", re.I)),
    ("nppv", re.compile(r"\bNPPV\s?\d?\b", re.I)),
    ("unspecified", re.compile(r"\b(?:security\s+clear(?:ance|ed)|security[- ]vetted|national security vetting|\bvetting\b)", re.I)),
    ("basic", re.compile(r"\b(?:BPSS|baseline personnel security|baseline (?:security )?(?:check|standard)|basic (?:security )?check)\b", re.I)),
    ("dbs", re.compile(r"\b(?:DBS|disclosure and barring|criminal record check|enhanced (?:dbs|disclosure))\b", re.I)),
]
_OBTAIN_RE = re.compile(r"\b(?:eligible|able|willing|prepared|ability|capable|can|must be able|undergo|obtain|gain|achieve|working towards|process of)\b", re.I)
LABELS = {
    "dv": "DV clearance", "sc": "SC clearance", "ctc": "CTC clearance", "nppv": "NPPV police vetting",
    "unspecified": "Security clearance / vetting", "basic": "Basic check (BPSS)", "dbs": "DBS check",
}


def _sentence(text: str, pos: int, limit: int = 200) -> str:
    start = max(text.rfind(c, 0, pos) for c in ".;!?\n") + 1
    ends = [i for i in (text.find(c, pos) for c in ".;!?\n") if i != -1]
    end = min(ends) + 1 if ends else len(text)
    s = " ".join(text[start:end].split())
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0] + "…"


def clearance(text: str, held: str = "none") -> dict:
    """{"level", "stance" (required | obtain | ""), "label", "quote", "blocks"} for the highest clearance named.

    `blocks` is True when the candidate (who holds `held`) could not meet it. Basic checks (BPSS, DBS) never block:
    anyone can be put through them.
    """
    found: dict[str, str] = {}
    for level, rx in _LEVELS:
        m = rx.search(text)
        if m:
            found[level] = _sentence(text, m.start())
    if not found:
        return {"level": "none", "stance": "", "label": "No clearance mentioned", "quote": "", "blocks": False}
    level = max(found, key=CLEARANCE_ORDER.index)
    quote = found[level]
    stance = "obtain" if _OBTAIN_RE.search(quote) else "required"
    blocked = level in BLOCKING and CLEARANCE_ORDER.index(level) > CLEARANCE_ORDER.index(held if held in CLEARANCE_ORDER else "none")
    if level in BLOCKING:
        label = f"{LABELS[level]} {'(must be eligible to obtain)' if stance == 'obtain' else 'required'}"
    else:
        label = f"{LABELS[level]} (standard, no clearance needed)"
    return {"level": level, "stance": stance, "label": label, "quote": quote, "blocks": bool(blocked)}


_LICENCE_RE = re.compile(r"\b(?:full |valid |clean |current )?(?:uk |united kingdom |european )?driving licen[cs]e\b|\bdrive(?:r)?'?s? licen[cs]e\b|\bown (?:vehicle|transport|car)\b|\bable to drive\b", re.I)
_DESIRABLE_RE = re.compile(r"\b(?:desirable|preferred|advantageous|an advantage|beneficial|ideally|nice to have|would be useful)\b", re.I)


def driving_licence(text: str, has_licence: bool | None = None) -> dict:
    """{"need": "" | "required" | "desirable", "quote", "status"} where status says how the candidate stands."""
    m = _LICENCE_RE.search(text)
    if not m:
        return {"need": "", "quote": "", "status": ""}
    quote = _sentence(text, m.start())
    need = "desirable" if _DESIRABLE_RE.search(quote) else "required"
    if has_licence is None:
        status = "unknown"
    elif has_licence:
        status = "ok"
    else:
        status = "missing"
    return {"need": need, "quote": quote, "status": status}


_REMOTE_RE = re.compile(r"\b(?:fully remote|100% remote|remote[- ]first|remote working|work(?:ing)? (?:from home|remotely)|home[- ]based|remote)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b|\b\d\s*days? (?:a|per|in the) (?:week|office)\b", re.I)


def work_mode(text: str, location: str = "") -> str:
    blob = f"{location} {text}"
    if _HYBRID_RE.search(blob):
        return "hybrid"
    if _REMOTE_RE.search(blob):
        return "remote"
    return ""
