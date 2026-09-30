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
from .classify import DOMAINS, SECTORS, TierRules, classify_domain, classify_sector, sponsorship_signal
from .contacts import ContactBook
from .models import Job
from .text import normalise_company

log = logging.getLogger("jobfeed")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
EUROPE_AND_UK = careers.EUROPE_AND_UK | {"LI"}
CHANNELS = ["career_site", "official", "aggregator"]
_CHANNEL_RANK = {"career_site": 2, "official": 1, "aggregator": 0}


def load_sponsor_index(status: dict) -> sponsors.SponsorIndex:
    index = sponsors.SponsorIndex()
    for register, loader in (("UK Home Office", sponsors.load_uk_register),
                             ("NL IND", sponsors.load_nl_register)):
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
    rss_report: dict = {}
    feeds = {
        **sources.SOURCES,
        "rss": lambda d: sources.rss_feeds(d, source_cfg.get("rss", {}).get("feeds", []), rss_report),
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
            report = {"career_sites": career_report, "rss": rss_report}.get(name)
            if report is not None:
                failed = report.get("failed", [])
                status[name].update(ok=report.get("ok", 0), failed=failed)
                if failed:
                    status[name]["status"] = "partial" if report.get("ok") else "error"
                    status[name]["error"] = f"{len(failed)} failed: " + "; ".join(failed)[:600]
                if report.get("slow"):
                    status[name]["slow"] = report["slow"]
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
        if job.country not in EUROPE_AND_UK:
            continue
        # Career-site jobs are the employer's own adverts by definition.
        if agencies and job.channel != "career_site" and agencies.is_agency(job.company, job.description):
            stats["agency_removed"] += 1
            continue

        signal = sponsorship_signal(f"{job.title} {job.description}")
        if signal == "negative":
            continue
        entry = index.lookup(job.register_name or job.company)
        if entry is None and job.channel == "career_site":
            entry = index.lookup_prefix(job.register_name or job.company)
        if signal == "positive" or job.source_says_sponsorship:
            job.sponsorship = "confirmed"
        elif entry and sponsors.REGISTER_COUNTRY.get(entry.register) == job.country:
            # Employer holds a sponsor licence in the job's country; the advert is silent.
            job.sponsorship = "licensed_sponsor"
        else:
            continue
        if entry:
            job.sponsor_register = entry.register
            job.sponsor_routes = sorted(entry.routes)

        job.sector = classify_sector(job)
        job.domain = classify_domain(job)
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
    jobs = enrich(raw, index, TierRules.load(CONFIG / "company_tiers.json"),
                  ContactBook.load(CONFIG / "contacts.json"), days, agencies, stats)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "sectors": SECTORS,
        "domains": DOMAINS,
        "channels": CHANNELS,
        "sources": status,
        "counts": {"fetched": len(raw), "agency_removed": stats["agency_removed"], "published": len(jobs)},
        "jobs": [j.to_dict() for j in jobs],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload
