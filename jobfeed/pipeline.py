"""Fetch → verify sponsorship → classify → dedupe → write data/jobs.json."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from . import sources, sponsors
from .classify import DOMAINS, SECTORS, TierRules, classify_domain, classify_sector, sponsorship_signal
from .contacts import ContactBook
from .models import Job

log = logging.getLogger("jobfeed")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
EUROPE = {"AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
          "IE", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT", "RO", "SE", "SI", "SK"}


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


def fetch_all(days: int, source_cfg: dict, status: dict) -> list[Job]:
    jobs: list[Job] = []
    for name, fn in sources.SOURCES.items():
        if not source_cfg.get(name, {}).get("enabled", True):
            status[name] = {"status": "disabled"}
            continue
        args = (days, source_cfg.get("rss", {}).get("feeds", [])) if name == "rss" else (days,)
        before = len(jobs)
        try:
            for job in fn(*args):
                jobs.append(job)
            status[name] = {"status": "ok", "count": len(jobs) - before}
        except sources.SkipSource as why:
            status[name] = {"status": "skipped", "reason": str(why)}
        except Exception as err:  # noqa: BLE001 - keep partial results from other sources
            log.warning("source %s failed: %s", name, err)
            log.debug(traceback.format_exc())
            status[name] = {"status": "error", "count": len(jobs) - before, "error": str(err)[:300]}
    return jobs


def enrich(jobs: Iterable[Job], index: sponsors.SponsorIndex, tiers: TierRules,
           contacts: ContactBook, days: int) -> list[Job]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: dict[tuple, Job] = {}
    for job in jobs:
        if job.posted_at < cutoff or not job.title or not job.url:
            continue
        if job.country != "GB" and job.country not in EUROPE:
            continue

        signal = sponsorship_signal(f"{job.title} {job.description}")
        if signal == "negative":
            continue
        entry = index.lookup(job.company)
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

        key = job.dedupe_key()
        existing = kept.get(key)
        # Prefer the copy with contacts / confirmed sponsorship / the newest date.
        if existing is None or _rank(job) > _rank(existing):
            kept[key] = job
    return sorted(kept.values(), key=lambda j: j.posted_at, reverse=True)


def _rank(job: Job) -> tuple:
    return (bool(job.contacts), job.sponsorship == "confirmed", job.posted_at)


def run(days: int, out_path: Path) -> dict:
    source_cfg = json.loads((CONFIG / "sources.json").read_text(encoding="utf-8"))
    status: dict = {}
    index = load_sponsor_index(status)
    raw = fetch_all(days, source_cfg, status)
    jobs = enrich(raw, index, TierRules.load(CONFIG / "company_tiers.json"),
                  ContactBook.load(CONFIG / "contacts.json"), days)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "sectors": SECTORS,
        "domains": DOMAINS,
        "sources": status,
        "counts": {"fetched": len(raw), "published": len(jobs)},
        "jobs": [j.to_dict() for j in jobs],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload
