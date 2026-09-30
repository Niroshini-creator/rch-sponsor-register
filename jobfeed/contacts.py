"""Hiring contact emails.

Only two kinds of address are ever shown, and each carries its provenance:

1. **advert** – an address printed in the job advert itself (the employer published it
   for applicants to use).
2. **verified** – an address you have added to config/contacts.json yourself, with the
   public page you confirmed it on.

Addresses are never guessed from name patterns or scraped from personal profiles:
those are frequently wrong and contacting people via inferred personal data breaches
UK GDPR / PECR.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Job
from .text import normalise_company

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IGNORE_RE = re.compile(r"no-?reply|do-?not-?reply|donotreply|example\.(com|org)|@sentry|\.(png|jpe?g|gif)$", re.I)
_ROLE_INBOX_RE = re.compile(
    r"^(jobs?|careers?|recruit\w*|hr|people|talent\w*|hiring|vacanc\w*|apply|applications?|resourcing|"
    r"info|enquir\w*|admin|office|contact|medical\.staffing|workforce|staffing)[._-]?", re.I)


def extract_advert_emails(text: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for raw in _EMAIL_RE.findall(text or ""):
        email = raw.strip(".").lower()
        if email in seen or _IGNORE_RE.search(email):
            continue
        seen.add(email)
        local = email.split("@", 1)[0]
        kind = "recruitment inbox" if _ROLE_INBOX_RE.match(local) else "named contact"
        found.append({"email": email, "type": kind, "provenance": "advert"})
    return found


class ContactBook:
    """Manually verified hiring contacts from config/contacts.json."""

    def __init__(self, entries: dict[str, list[dict]]):
        self._entries = entries

    @classmethod
    def load(cls, path: Path) -> "ContactBook":
        if not path.exists():
            return cls({})
        cfg = json.loads(path.read_text(encoding="utf-8"))
        entries: dict[str, list[dict]] = {}
        for c in cfg.get("contacts", []):
            if not c.get("email") or not c.get("company"):
                continue
            entries.setdefault(normalise_company(c["company"]), []).append({
                "email": c["email"].lower(),
                "name": c.get("name", ""),
                "role": c.get("role", ""),
                "type": "named contact" if c.get("name") else "recruitment inbox",
                "provenance": "verified",
                "source_url": c.get("source_url", ""),
                "verified_on": c.get("verified_on", ""),
            })
        return cls(entries)

    def contacts_for(self, job: Job) -> list[dict]:
        verified = list(self._entries.get(normalise_company(job.company), []))
        known = {c["email"] for c in verified}
        advert = [c for c in extract_advert_emails(job.description) if c["email"] not in known]
        # Named contacts first: they are the closest thing to a hiring manager.
        return sorted(verified + advert, key=lambda c: (c["type"] != "named contact", c["provenance"] != "verified"))
