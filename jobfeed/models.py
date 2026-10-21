"""The normalised job record every source is converted into."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


# Stands in for "no posting date" while a source reads adverts; the pipeline turns it into date_known=False.
UNDATED = datetime(9999, 12, 30, tzinfo=timezone.utc)


@dataclass
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    country: str               # ISO 3166 alpha-2, e.g. "GB", "DE"
    url: str
    posted_at: datetime
    description: str = ""
    salary: str = ""
    contract: str = ""
    # How the candidate applies: "career_site" (employer's own careers portal),
    # "official" (NHS Jobs, Teaching Vacancies, jobs.ac.uk, government boards) or
    # "aggregator" (job boards that repost adverts).
    channel: str = "aggregator"
    # Set by the source when the feed itself flags sponsorship (e.g. a filter or field).
    source_says_sponsorship: bool = False
    # Legal name on the sponsor register when it differs from the trading name (career sites).
    register_name: str = ""
    # Hiring contacts the source publishes alongside the advert (e.g. Platsbanken's contact list).
    advert_contacts: list[dict] = field(default_factory=list)

    # Filled in by the enrichment pipeline.
    sponsorship: str = ""       # "confirmed" | "licensed_sponsor"
    sponsor_register: str = ""  # which official register the employer was matched on
    sponsorship_evidence: str = ""  # the advert's sentence that offers (or rules out) sponsorship
    sponsor_routes: list[str] = field(default_factory=list)
    sector: str = ""            # employer type, see classify.SECTORS
    domain: str = ""            # role function, see classify.DOMAINS
    role: str = ""              # job family, see classify.ROLES
    region: str = ""            # sub-national region shown as its own filter, e.g. "Scotland", "Dubai"
    english: bool = False       # advert is in English and asks for no other language
    early_career: str = ""      # "stated" | "likely": open to UK Graduate visa (PSW) / US OPT holders
    aviation: str = ""          # aviation / aerospace job family, see classify.AVIATION_FAMILIES
    low_sponsorship: bool = False  # front-line role (agent, receptionist...) that is rarely sponsored
    # Advertised pay against the visa minimum, see salary.salary_check: "meets" | "partial" | "reduced" | "below" | "".
    salary_check: str = ""
    salary_annual: int = 0      # top of the advertised range as a yearly figure (0 when unread)
    salary_threshold: int = 0   # the minimum it was compared with, in the country's currency
    tier: int = 3
    size: str = "unknown"      # "large" | "medium" | "small" | "unknown"
    contacts: list[dict] = field(default_factory=list)
    # Employer's own careers site, for job-board adverts at directory employers (board links can be region-locked).
    employer_site: str = ""
    date_known: bool = True     # False when the advert gives no posting date (posted_at is then the day it was found)
    # Digest of the whole advert (see digest.py): keywords found, clearance / licence / nationality sentences, full length.
    kw: list[str] = field(default_factory=list)
    signals: str = ""
    text_len: int = 0
    exp_years: int = 0          # smallest number of years of experience the advert asks for (0 = none stated)

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.source}:{self.source_id}".encode()).hexdigest()[:12]

    def dedupe_key(self) -> tuple[str, str, str]:
        from .text import normalise_company
        return (" ".join(self.title.lower().split()), normalise_company(self.company),
                self.location.lower().split(",")[0].strip())

    def to_dict(self, description_chars: int = 400) -> dict:
        data = asdict(self)
        data["id"] = self.id
        data["posted_at"] = self.posted_at.isoformat()
        desc = self.description
        data["description"] = desc if len(desc) <= description_chars else desc[:description_chars].rsplit(" ", 1)[0] + "…"
        del data["source_says_sponsorship"], data["register_name"], data["advert_contacts"]
        return data
