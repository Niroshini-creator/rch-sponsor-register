"""Contact records: employers (B2B prospects) and candidates (job seekers).

Contacts live in CSV files under outreach_data/contacts/. One row per person or inbox:

    id, audience, name, company, role, email, phone, country, city, visa, visa_expiry,
    target_role, source, consent_channels, consent_date, consent_source,
    relationship, relationship_date, tps_status, tps_checked_on, notes

* audience          employer | candidate
* country           ISO code of where the contact is (GB, IE, NL, …)
* visa              candidates: psw | dependant | stamp1g | stamp4 | skilled_worker | other
* source            where you got the contact (URL, event, referral) – required for employers
* consent_channels  channels the person opted in to, separated by ';' (email;sms;whatsapp;call)
* consent_date/source  when and how they opted in (form name, webinar sign-up, …)
* relationship      enquired | client: they asked about / bought your service (soft opt-in)
* tps_status        clear | registered: result of your last TPS/CTPS (UK) or NDD (IE) screen
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

FIELDS = ["id", "audience", "name", "company", "role", "email", "phone", "country", "city", "visa", "visa_expiry",
          "target_role", "source", "consent_channels", "consent_date", "consent_source", "relationship",
          "relationship_date", "tps_status", "tps_checked_on", "notes"]
CHANNELS = ("email", "sms", "whatsapp", "call")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_DIAL = {"GB": "44", "IE": "353"}


def parse_day(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unrecognised date {value!r} (use YYYY-MM-DD)")


def normalise_phone(raw: str, country: str) -> str:
    """E.164 (+447700900123). National numbers are read in the contact's country."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        code = _DIAL.get(country.upper())
        if not code or not digits.startswith("0"):
            raise ValueError(f"phone {raw!r}: give it in international format (+…)")
        digits = f"+{code}{digits[1:]}"
    if not 9 <= len(digits) - 1 <= 15:
        raise ValueError(f"phone {raw!r} is not a valid number")
    return digits


def is_mobile(phone: str) -> bool:
    return phone.startswith("+447") or bool(re.match(r"^\+3538[35679]", phone))


@dataclass
class Contact:
    id: str
    audience: str
    name: str = ""
    company: str = ""
    role: str = ""
    email: str = ""
    phone: str = ""
    country: str = ""
    city: str = ""
    visa: str = ""
    visa_expiry: date | None = None
    target_role: str = ""
    source: str = ""
    consent: frozenset = frozenset()
    consent_date: date | None = None
    consent_source: str = ""
    relationship: str = ""
    relationship_date: date | None = None
    tps_status: str = ""
    tps_checked_on: date | None = None
    notes: str = ""
    errors: list = field(default_factory=list)

    @property
    def first_name(self) -> str:
        parts = [p for p in self.name.split() if p.rstrip(".").lower() not in {"dr", "prof", "mr", "mrs", "ms", "miss", "mx"}]
        return parts[0] if parts else ""

    def address(self, channel: str) -> str:
        return self.email if channel == "email" else self.phone


def _contact_id(row: dict) -> str:
    key = (row.get("email") or row.get("phone") or row.get("name", "")).strip().lower()
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def from_row(row: dict) -> Contact:
    row = {k: (v or "").strip() for k, v in row.items() if k}
    errors: list[str] = []
    country = row.get("country", "").upper()
    audience = row.get("audience", "").lower()
    if audience not in ("employer", "candidate"):
        errors.append("audience must be 'employer' or 'candidate'")
    email = row.get("email", "").lower()
    if email and not _EMAIL_RE.match(email):
        errors.append(f"invalid email {email!r}")
        email = ""
    try:
        phone = normalise_phone(row.get("phone", ""), country)
    except ValueError as exc:
        errors.append(str(exc))
        phone = ""
    consent = frozenset(c.strip().lower() for c in re.split(r"[;,|]", row.get("consent_channels", "")) if c.strip())
    if bad := consent - set(CHANNELS):
        errors.append(f"unknown consent channel(s) {sorted(bad)}")
    dates = {}
    for name in ("visa_expiry", "consent_date", "relationship_date", "tps_checked_on"):
        try:
            dates[name] = parse_day(row.get(name, ""))
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            dates[name] = None
    return Contact(
        id=row.get("id") or _contact_id(row), audience=audience, name=row.get("name", ""),
        company=row.get("company", ""), role=row.get("role", ""), email=email, phone=phone, country=country,
        city=row.get("city", ""), visa=row.get("visa", "").lower(), target_role=row.get("target_role", ""),
        source=row.get("source", ""), consent=consent, consent_source=row.get("consent_source", ""),
        relationship=row.get("relationship", "").lower(), tps_status=row.get("tps_status", "").lower(),
        notes=row.get("notes", ""), errors=errors, **dates)


def load_contacts(folder: Path) -> list[Contact]:
    contacts: dict[str, Contact] = {}
    for path in sorted(folder.glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for line, row in enumerate(csv.DictReader(fh), start=2):
                c = from_row(row)
                c.errors = [f"{path.name}:{line}: {e}" for e in c.errors]
                if c.id in contacts:
                    c.errors.append(f"{path.name}:{line}: duplicate id {c.id} (kept the first row)")
                    contacts[c.id].errors.extend(c.errors)
                    continue
                contacts[c.id] = c
    return list(contacts.values())


def import_employers_from_jobs(jobs_path: Path, out_csv: Path) -> int:
    """Add the recruitment inboxes that employers published in their job adverts (data/jobs.json)
    as employer prospects. Existing rows are kept; addresses already present are skipped."""
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))["jobs"]
    existing: set[str] = set()
    if out_csv.exists():
        with out_csv.open(newline="", encoding="utf-8-sig") as fh:
            existing = {(r.get("email") or "").strip().lower() for r in csv.DictReader(fh)}
    rows = []
    for job in jobs:
        for ct in job.get("contacts") or []:
            email = (ct.get("email") or "").lower()
            if not email or email in existing:
                continue
            existing.add(email)
            rows.append({"audience": "employer", "name": ct.get("name", ""), "company": job["company"],
                         "role": ct.get("role", ""), "email": email, "phone": ct.get("phone", ""),
                         "country": job.get("country", ""), "city": job.get("location", ""),
                         "source": f"{ct.get('provenance', 'advert')}: {job['url']}",
                         "notes": f"hiring for: {job['title']}"})
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out_csv.exists()
    with out_csv.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)
