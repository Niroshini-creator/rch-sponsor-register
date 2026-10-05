"""Fetch → drop clearance / no-sponsorship adverts → score → merge with last run → write data/jobs.json."""

from __future__ import annotations

import json
import logging
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobfeed import sponsors
from jobfeed.agencies import AgencyFilter
from jobfeed.classify import sponsorship_signal
from jobfeed.models import Job
from jobfeed.sources import SkipSource
from jobfeed.text import normalise_company

from . import sources
from .score import requires_clearance, score_job

log = logging.getLogger("mugilan")
HERE = Path(__file__).resolve().parent.parent          # mugilan/
MAIN_CONFIG = HERE.parent / "config"                   # read-only: the main board's agency list
DEFAULT_OUT = HERE / "data" / "jobs.json"
NEAR_MISS_MIN = 20                                     # lowest score shown under "closest matches"
NEAR_MISS_MAX = 25
DEEP_MIN_SCORE = 20                                    # snippet score that makes an advert worth reading in full
DEEP_MAX = int(os.environ.get("MUGILAN_DEEP_MAX", "80"))
DEEP_PAUSE = float(os.environ.get("MUGILAN_DEEP_PAUSE", "0.2"))


def load_profile() -> dict:
    return json.loads((HERE / "config" / "profile.json").read_text(encoding="utf-8"))


def fetch(days: int, profile: dict, status: dict) -> list[Job]:
    employers = json.loads((HERE / "config" / "employers.json").read_text(encoding="utf-8")).get("employers", [])
    report: dict = {}
    searches = profile["searches"]
    feeds = {"Reed": lambda: sources.reed(days, searches),
             "Adzuna": lambda: sources.adzuna(days, searches),
             "Career sites": lambda: sources.career_feeds(days, employers, report)}
    jobs: list[Job] = []
    for name, make in feeds.items():
        before = len(jobs)
        try:
            jobs.extend(make())
            status[name] = {"status": "ok", "count": len(jobs) - before}
            if report.get("failed") and name == "Career sites":
                status[name].update(status="partial", error="; ".join(report["failed"])[:400])
        except SkipSource as why:
            status[name] = {"status": "skipped", "reason": str(why)}
        except Exception as err:  # noqa: BLE001 - keep what the other sources returned
            log.warning("source %s failed: %s", name, err)
            log.debug(traceback.format_exc())
            status[name] = {"status": "error", "count": len(jobs) - before, "error": str(err)[:300]}
    return jobs


def deepen(jobs: list[Job], profile: dict, stats: dict, fetch_full=sources.reed_full_text) -> None:
    """Replace Reed's short search snippet with the full advert for roles that already look promising.

    Reed's search API truncates descriptions, so OSS/BSS keywords deep in an advert would otherwise be missed
    (and clearance / sponsorship wording too). Best candidates first; capped at DEEP_MAX calls per run.
    """
    stats.setdefault("full_advert_fetched", 0)
    cutoff = datetime.now(timezone.utc) - timedelta(days=profile["window_days"])
    candidates = []
    for job in jobs:
        if job.source != "Reed" or job.posted_at < cutoff or job.country != "GB":
            continue
        pre = score_job(job.title, job.description, job.salary, profile["min_salary"], "confirmed").score
        if pre >= DEEP_MIN_SCORE:
            candidates.append((pre, job))
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _, job in candidates[:DEEP_MAX]:
        try:
            full = fetch_full(job.source_id)
        except SkipSource:
            return
        except Exception as err:  # noqa: BLE001 - keep the snippet when one advert can't be read
            log.warning("full advert %s unavailable: %s", job.source_id, err)
            continue
        if len(full) > len(job.description):
            job.description = full
            stats["full_advert_fetched"] += 1
        time.sleep(DEEP_PAUSE)


def build(jobs: list[Job], profile: dict, days: int, index: sponsors.SponsorIndex | None,
          agencies: AgencyFilter | None, stats: dict, near: dict | None = None) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    min_salary, min_match = profile["min_salary"], profile["min_match"]
    best: dict[tuple, dict] = {}
    for job in jobs:
        if job.posted_at < cutoff or not (job.title and job.url) or job.country != "GB":
            continue
        text = f"{job.title}\n{job.description}"
        if requires_clearance(text):
            stats["clearance_removed"] += 1
            continue
        if sponsorship_signal(text) == "negative":
            stats["no_sponsorship_removed"] += 1
            continue

        is_agency = bool(agencies and job.channel != "career_site" and agencies.is_agency(job.company, job.description))
        if sponsorship_signal(text) == "positive" or job.source_says_sponsorship:
            sponsorship = "confirmed"
        elif index and (index.lookup(job.register_name or job.company, "GB")
                        or (job.channel == "career_site" and index.lookup_prefix(job.register_name or job.company, "GB"))):
            sponsorship = "licensed_sponsor"
        elif is_agency:
            sponsorship = "agency"       # the end client is unnamed, so the licence cannot be checked
        else:
            sponsorship = "unverified"

        res = score_job(job.title, job.description, job.salary, min_salary, sponsorship)
        below = res.score < min_match
        if below:
            stats["below_threshold"] += 1
            if near is None or res.score < NEAR_MISS_MIN:
                continue
        record = job.to_dict(description_chars=600)
        record.update(match=res.score, reasons=res.reasons, flags=res.flags + (["Recruitment agency advert"] if is_agency else []),
                      matched_keywords=res.matched, sponsorship=sponsorship, agency=is_agency)
        record.pop("advert_contacts", None)
        title, company, city = job.dedupe_key()
        key = (title, normalise_company(job.company), city)
        if below:
            if key not in near or record["match"] > near[key]["match"]:
                near[key] = record
            continue
        if key not in best or record["match"] > best[key]["match"]:
            best[key] = record
    return list(best.values())


def merge_previous(fresh: list[dict], path: Path, days: int, now: datetime) -> list[dict]:
    """Keep earlier finds still inside the window, so a day's results never vanish because a source hiccuped."""
    cutoff = now - timedelta(days=days)
    merged = {r["id"]: r for r in fresh}
    first_seen = {}
    if path.exists():
        try:
            for old in json.loads(path.read_text(encoding="utf-8")).get("jobs", []):
                first_seen[old["id"]] = old.get("first_seen") or old["posted_at"]
                if old["id"] not in merged and datetime.fromisoformat(old["posted_at"]) >= cutoff:
                    merged[old["id"]] = old
        except (ValueError, KeyError, json.JSONDecodeError):
            log.warning("previous feed unreadable; starting clean")
    for r in merged.values():
        r["first_seen"] = first_seen.get(r["id"], now.isoformat(timespec="seconds"))
    return sorted(merged.values(), key=lambda r: (r["match"], r["posted_at"]), reverse=True)


def run(days: int, out_path: Path = DEFAULT_OUT) -> dict:
    profile = load_profile()
    days = days or profile["window_days"]
    now = datetime.now(timezone.utc)
    status: dict = {}
    index = sponsors.SponsorIndex()
    try:
        sponsors.load_uk_register(index)
        status["UK sponsor register"] = {"status": "ok", "count": len(index)}
    except Exception as err:  # noqa: BLE001
        index = None
        status["UK sponsor register"] = {"status": "error", "error": str(err)[:300]}
    raw = fetch(days, profile, status)
    stats = {"clearance_removed": 0, "no_sponsorship_removed": 0, "below_threshold": 0}
    deepen(raw, profile, stats)
    agency_path = MAIN_CONFIG / "agencies.json"
    agencies = AgencyFilter.load(agency_path) if agency_path.exists() else None
    near: dict = {}
    fresh = build(raw, profile, days, index, agencies, stats, near)
    jobs = merge_previous(fresh, out_path, days, now)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": days,
        "profile": {k: profile[k] for k in ("name", "headline", "min_salary", "min_match", "notice_period_days",
                                             "visa", "driving_licence", "clearance")},
        "sources": status,
        "counts": {"fetched": len(raw), **stats, "published": len(jobs)},
        "jobs": jobs,
        "near_misses": sorted(near.values(), key=lambda r: (r["match"], r["posted_at"]), reverse=True)[:NEAR_MISS_MAX],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload
