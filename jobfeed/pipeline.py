"""Fetch → verify sponsorship → classify → dedupe → write data/jobs.json."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import careers, sources, sponsors
from .agencies import AgencyFilter
from .classify import (DOMAINS, ENGLISH_SPEAKING_COUNTRIES, ROLES, SECTORS, TierRules, classify_domain,
                       classify_early_career, classify_english, classify_region, classify_role, classify_sector,
                       sponsorship_signal)
from .contacts import ContactBook
from .models import Job
from .text import normalise_company

log = logging.getLogger("jobfeed")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
COUNTRIES = careers.TARGET_COUNTRIES | {"LI"}
# Countries where the employer sponsors every foreign hire's work visa by law (UAE residence visas).
EMPLOYER_VISA_COUNTRIES = {"AE"}
# Shown first in the country filter, even before they have jobs.
FEATURED_COUNTRIES = ["GB", "GB-SCT", "US", "NL", "LU", "SE", "FI", "PL", "ES", "AE", "AE-DXB"]
REGISTERS = [("UK Home Office", sponsors.load_uk_register), ("NL IND", sponsors.load_nl_register),
             ("US H-1B", sponsors.load_us_h1b)]
CHANNELS = ["career_site", "official", "aggregator"]
_CHANNEL_RANK = {"career_site": 2, "official": 1, "aggregator": 0}


def load_sponsor_index(status: dict) -> sponsors.SponsorIndex:
    index = sponsors.SponsorIndex()
    for register, loader in REGISTERS:
        name = f"{register} register"
        try:
            loader(index)
            status[name] = {"status": "ok", "count": index.counts.get(register, 0)}
        except Exception as err:  # noqa: BLE001 - a missing register must not stop the run
            log.warning("%s unavailable: %s", name, err)
            status[name] = {"status": "error", "error": str(err)[:300]}
    return index


def fetch_all(days: int, source_cfg: dict, status: dict, employers: list[dict] | None = None) -> list[Job]:
    jobs: list[Job] = []
    career_report: dict = {}
    feeds = {
        **sources.SOURCES,
        "rss": lambda d: sources.rss_feeds(d, source_cfg.get("rss", {}).get("feeds", [])),
        "career_sites": lambda d: careers.career_sites(d, employers or [], career_report),
    }
    for name, fn in feeds.items():
        if not source_cfg.get(name, {}).get("enabled", True):
            status[name] = {"status": "disabled"}
            continue
        before = len(jobs)
        try:
            for job in fn(days):
                jobs.append(job)
            status[name] = {"status": "ok", "count": len(jobs) - before}
            if name == "career_sites":
                failed = career_report.get("failed", [])
                status[name].update(employers_ok=career_report.get("ok", 0), employers_failed=failed)
                if failed:
                    status[name]["status"] = "partial" if career_report.get("ok") else "error"
                    status[name]["error"] = f"{len(failed)} career site(s) failed: " + "; ".join(failed)[:600]
        except sources.SkipSource as why:
            status[name] = {"status": "skipped", "reason": str(why)}
        except Exception as err:  # noqa: BLE001 - keep partial results from other sources
            log.warning("source %s failed: %s", name, err)
            log.debug(traceback.format_exc())
            status[name] = {"status": "error", "count": len(jobs) - before, "error": str(err)[:300]}
    return jobs


def enrich(jobs: Iterable[Job], index: sponsors.SponsorIndex, tiers: TierRules,
           contacts: ContactBook, days: int, agencies: AgencyFilter | None = None,
           stats: dict | None = None) -> list[Job]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats = stats if stats is not None else {}
    stats.setdefault("agency_removed", 0)
    kept: dict[tuple, Job] = {}
    for job in jobs:
        if job.posted_at < cutoff or not job.title or not job.url:
            continue
        if job.country not in COUNTRIES:
            continue
        # Career-site jobs are the employer's own adverts by definition.
        if agencies and job.channel != "career_site" and agencies.is_agency(job.company, job.description):
            stats["agency_removed"] += 1
            continue

        signal = sponsorship_signal(f"{job.title} {job.description}")
        entry = index.lookup(job.register_name or job.company, job.country)
        if job.channel == "career_site" and (entry is None or sponsors.REGISTER_COUNTRY.get(entry.register) != job.country):
            entry = index.lookup_prefix(job.register_name or job.company, job.country) or entry
        if signal == "negative":
            # No sponsorship, but the advert welcomes Graduate visa (PSW) / OPT holders, who need none.
            if classify_early_career(job) != "stated":
                continue
            job.sponsorship = "graduate_route"
            job.early_career = "stated"
        elif signal == "positive" or job.source_says_sponsorship:
            job.sponsorship = "confirmed"
        elif entry and sponsors.REGISTER_COUNTRY.get(entry.register) == job.country:
            # Employer holds a sponsor licence in the job's country; the advert is silent.
            job.sponsorship = "licensed_sponsor"
        elif job.country in EMPLOYER_VISA_COUNTRIES:
            job.sponsorship = "employer_visa"
        else:
            continue
        if entry:
            job.sponsor_register = entry.register
            job.sponsor_routes = sorted(entry.routes)

        job.sector = classify_sector(job)
        job.domain = classify_domain(job)
        job.role = classify_role(job)
        job.region = classify_region(job)
        job.english = job.country in ENGLISH_SPEAKING_COUNTRIES or classify_english(job)
        job.early_career = job.early_career or classify_early_career(job)
        job.tier, job.size = tiers.classify(job)
        job.contacts = contacts.contacts_for(job)

        # Key on the register's legal name when matched, so "Monzo" and "Monzo Bank Ltd" merge.
        title, company, city = job.dedupe_key()
        key = (title, normalise_company(entry.name) if entry else company, city)
        existing = kept.get(key)
        # Prefer the employer's own site, then contacts, confirmed sponsorship and the newest date.
        if existing is None or _rank(job) > _rank(existing):
            if existing is not None and not job.contacts and existing.contacts:
                job.contacts = existing.contacts  # keep an advert email found on another copy
            kept[key] = job
    return sorted(kept.values(), key=lambda j: j.posted_at, reverse=True)


def _rank(job: Job) -> tuple:
    return (_CHANNEL_RANK.get(job.channel, 0), bool(job.contacts), job.sponsorship == "confirmed", job.posted_at)


def run(days: int, out_path: Path) -> dict:
    source_cfg = json.loads((CONFIG / "sources.json").read_text(encoding="utf-8"))
    employers = json.loads((CONFIG / "employers.json").read_text(encoding="utf-8")).get("employers", [])
    status: dict = {}
    index = load_sponsor_index(status)
    raw = fetch_all(days, source_cfg, status, employers)
    stats: dict = {}
    agencies = AgencyFilter.load(CONFIG / "agencies.json") if source_cfg.get("exclude_agencies", True) else None
    tiers = TierRules.load(CONFIG / "company_tiers.json")
    jobs = enrich(raw, index, tiers, ContactBook.load(CONFIG / "contacts.json"), days, agencies, stats)
    directory = build_directory(jobs, index, tiers, CONFIG / "early_career_employers.json")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "sectors": SECTORS,
        "domains": DOMAINS,
        "roles": ROLES,
        "channels": CHANNELS,
        "featured_countries": FEATURED_COUNTRIES,
        "sources": status,
        "counts": {"fetched": len(raw), "agency_removed": stats["agency_removed"], "published": len(jobs)},
        "jobs": [j.to_dict() for j in jobs],
        "employers": directory,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload


def build_directory(jobs: list[Job], index: sponsors.SponsorIndex, tiers: TierRules, path: Path) -> list[dict]:
    """Employers that take UK Graduate visa (PSW) or US OPT holders.

    Two kinds of row: the curated list in config/early_career_employers.json (graduate schemes and
    new-grad programmes), each re-checked against the sponsor registers on every run, and employers
    discovered in this run's feed with at least one "stated" or "likely" early-career vacancy.
    """
    open_roles: dict[tuple[str, str], list[Job]] = {}
    for job in jobs:
        open_roles.setdefault((normalise_company(job.company), job.country), []).append(job)

    rows: dict[tuple[str, str], dict] = {}
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for emp in cfg.get("employers", []):
        country = emp.get("country", "GB")
        names = emp.get("register_name") or []
        names = ([names] if isinstance(names, str) else names) + [emp["name"]]
        entry = next((e for n in names for e in (index.lookup(n, country), index.lookup_prefix(n, country))
                      if e and sponsors.REGISTER_COUNTRY.get(e.register) == country), None)
        on_register = bool(entry and sponsors.REGISTER_COUNTRY.get(entry.register) == country)
        probe = Job(source="", source_id="", title="", company=emp["name"], location="", country=country, url="",
                    posted_at=datetime.now(timezone.utc))
        tier, size = tiers.classify(probe)
        key = (normalise_company(emp["name"]), country)
        live = open_roles.get(key, [])
        rows[key] = {
            "name": emp["name"], "country": country, "route": "PSW" if country == "GB" else "OPT",
            "size": emp.get("size") or size, "tier": tier, "sector": emp.get("sector", "Private Sector"),
            "programme": emp.get("programme", ""), "careers_url": emp.get("careers_url", ""),
            "on_register": on_register, "register": entry.register if on_register else "",
            "open_roles": len(live), "early_career_roles": sum(bool(j.early_career) for j in live),
            "curated": True,
        }
    for key, live in open_roles.items():
        early = [j for j in live if j.early_career]
        if key in rows or not early or key[1] not in ("GB", "US"):
            continue
        first = early[0]
        rows[key] = {
            "name": first.company, "country": first.country, "route": "PSW" if first.country == "GB" else "OPT",
            "size": first.size, "tier": first.tier, "sector": first.sector, "programme": "",
            "careers_url": first.url if first.channel == "career_site" else "",
            "on_register": bool(first.sponsor_register), "register": first.sponsor_register,
            "open_roles": len(live), "early_career_roles": len(early), "curated": False,
        }
    return sorted(rows.values(), key=lambda r: (-r["early_career_roles"], r["tier"], r["name"].lower()))
