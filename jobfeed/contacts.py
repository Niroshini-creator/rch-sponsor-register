"""Hiring contact emails.

Only two kinds of address are ever shown, and each carries its provenance:

1. **advert** – an address printed in the job advert itself (the employer published it
   for applicants to use), or listed by the job board as the advert's contact. When the
   advert names the person and their job title next to the address ("informal enquiries to
   Dr Jane Smith, Head of Biochemistry, on 01234 567890 or jane.smith@…"), those are kept too.
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


_TITLE = r"(?:Dr|Prof|Professor|Mr|Mrs|Ms|Miss|Mx)\.?\s+"
_NAME_WORD = r"[A-Z][a-zà-ÿ]*(?:['’-][A-Z]?[a-zà-ÿ]+)*"
_CONTACT_RE = re.compile(
    r"(?i:contact|speak (?:to|with)|talk (?:to|with)|enquiries (?:to|with|contact)|discussion with|discuss\w* (?:with )?|"
    r"reach out to|questions? to|e-?mail|call|please contact|hiring manager(?: is)?|recruiting manager(?: is)?)"
    rf"\s*:?\s*(?:the\s+)?(?P<title>{_TITLE})?(?P<name>{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}})"
    r"(?:\s*\((?P<role1>[^)@]{3,70})\)|\s+[-–]\s+(?P<role3>[A-Z][^,;:@()\n]{2,50}?)(?=\s*[:,(]|\s+(?:on|at|via)\b)|"
    r"\s*,\s*(?P<role2>[A-Z][^,;:@()\n]{2,70}?)(?=\s*(?:,|\bon\b|\bat\b|\bvia\b|"
    r"\bby\b|\bemail|\btel|\bphone|-|–|\.|$)))?")
_NOT_NAME = {"the", "our", "human", "resources", "recruitment", "team", "hr", "department", "office", "us", "please",
             "email", "university", "school", "trust", "ltd", "hiring", "manager", "talent", "acquisition", "people",
             "service", "services", "careers", "jobs", "medical", "staffing", "nhs", "foundation", "college", "council",
             "for", "informal", "enquiries", "further", "information", "details", "apply", "via", "line"}
_PHONE_RE = re.compile(r"(?:tel(?:ephone)?|phone|call|on|mobile|ring)\.?:?\s*(\+?\(?\d[\d\s().-]{8,17}\d)", re.I)


def _named_contact(window: str) -> dict:
    """The last "contact <Name>, <Role>" before an address, when the advert names the person."""
    found: dict = {}
    for m in _CONTACT_RE.finditer(window):
        words = m.group("name").split()
        if any(w.lower().strip("'’") in _NOT_NAME for w in words):
            continue
        name = f"{(m.group('title') or '').strip()} {m.group('name')}".strip()
        role = (m.group("role1") or m.group("role2") or m.group("role3") or "").strip(" .,-–")
        found = {"name": name, "role": role if not _EMAIL_RE.search(role) else ""}
    return found


def extract_advert_emails(text: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    text = text or ""
    prev_end = 0
    for m in _EMAIL_RE.finditer(text):
        # Only the words since the previous address can describe this one.
        window = text[max(prev_end, m.start() - 220):m.start()]
        prev_end = m.end()
        email = m.group(0).strip(".").lower()
        if email in seen or _IGNORE_RE.search(email):
            continue
        seen.add(email)
        local = email.split("@", 1)[0]
        kind = "recruitment inbox" if _ROLE_INBOX_RE.match(local) else "named contact"
        contact = {"email": email, "type": kind, "provenance": "advert"}
        person = _named_contact(window)
        if person:
            contact.update(person)
        phone = _PHONE_RE.search(window[-120:])
        if phone:
            contact["phone"] = " ".join(phone.group(1).split())
        found.append(contact)
    return found


def published_contacts(job: Job) -> list[dict]:
    """Contacts a job board lists with the advert (e.g. Platsbanken), normalised like advert emails."""
    out = []
    for c in job.advert_contacts:
        email = (c.get("email") or "").strip().lower()
        if email and (_IGNORE_RE.search(email) or not _EMAIL_RE.fullmatch(email)):
            email = ""
        if not (email or c.get("phone")):
            continue
        local = email.split("@", 1)[0]
        named = bool(c.get("name")) or (email and not _ROLE_INBOX_RE.match(local))
        out.append({k: v for k, v in {
            "email": email, "name": c.get("name", ""), "role": c.get("role", ""), "phone": c.get("phone", ""),
            "type": "named contact" if named else "recruitment inbox", "provenance": "advert"}.items() if v})
    return out


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
        advert = []
        for c in published_contacts(job) + extract_advert_emails(job.description):
            key = c.get("email") or c.get("phone")
            if key not in known:
                known.add(key)
                advert.append(c)
        # Named contacts first: they are the closest thing to a hiring manager.
        return sorted(verified + advert, key=lambda c: (c["type"] != "named contact", c["provenance"] != "verified"))
