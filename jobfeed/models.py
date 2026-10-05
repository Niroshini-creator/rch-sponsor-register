"""The normalised job record every source is converted into."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime


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
    sponsor_routes: list[str] = field(default_factory=list)
    sector: str = ""            # employer type, see classify.SECTORS
    domain: str = ""            # role function, see classify.DOMAINS
    role: str = ""              # job family, see classify.ROLES
    region: str = ""            # sub-national region shown as its own filter, e.g. "Scotland", "Dubai"
    english: bool = False       # advert is in English and asks for no other language
    early_career: str = ""      # "stated" | "likely": open to UK Graduate visa (PSW) / US OPT holders
    aviation: str = ""          # aviation / aerospace job family, see classify.AVIATION_FAMILIES
    low_sponsorship: bool = False  # front-line role (agent, receptionist...) that is rarely sponsored
    tier: int = 3
    size: str = "unknown"      # "large" | "medium" | "small" | "unknown"
    contacts: list[dict] = field(default_factory=list)

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
