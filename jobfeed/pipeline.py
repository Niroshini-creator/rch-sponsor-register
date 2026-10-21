"""Fetch → verify sponsorship → classify → dedupe → write data/jobs.json."""

from __future__ import annotations

import json
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from candidateboard.checks import required_years

from . import careers, sources, sponsors
from .agencies import AgencyFilter
from .classify import (AVIATION_FAMILIES, DOMAINS, ENGLISH_SPEAKING_COUNTRIES, ROLES, SECTORS, TierRules,
                       classify_aviation, classify_domain, classify_early_career, classify_english, classify_region,
                       classify_role, classify_sector, is_low_sponsorship, sponsorship_evidence, stamp1g_status)
from .contacts import ContactBook
from .deepen import previous_digests, read_full_adverts, reuse_digest
from .digest import digest
from .models import UNDATED, Job
from .salary import salary_check
from .text import normalise_company

log = logging.getLogger("jobfeed")

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
COUNTRIES = careers.TARGET_COUNTRIES | {"LI"}
# Countries where the employer sponsors every foreign hire's work visa (Gulf residence and work visas).
EMPLOYER_VISA_COUNTRIES = careers.GULF_STATES
LOCAL_COUNTRIES = careers.LOCAL_COUNTRIES
# Shown first in the country filter, even before they have jobs.
FEATURED_COUNTRIES = ["GB", "GB-SCT", "IE", "US", "IN", "NL", "LU", "SE", "FI", "PL", "ES", "AE", "AE-DXB"]
REGISTERS = [("UK Home Office", sponsors.load_uk_register), ("NL IND", sponsors.load_nl_register),
             ("US H-1B", sponsors.load_us_h1b), ("IE employment permits", sponsors.load_ie_permits)]
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


MAX_UNDATED_PER_SOURCE = int(os.environ.get("MAX_UNDATED_PER_SOURCE", "300"))
FEED_BUDGET_MINUTES = float(os.environ.get("FEED_BUDGET_MINUTES", "110"))


def fetch_all(days: int, source_cfg: dict, status: dict, employers: list[dict] | None = None) -> list[Job]:
    """Read every source at the same time (they are independent, so the run lasts as long as the slowest one, not the sum).

    A source still reading when the time budget ends is stopped and keeps what it had, so a slow source delays nothing and
    the feed is always published."""
    career_report: dict = {}
    feeds = {
        **sources.SOURCES,
        "rss": lambda d: sources.rss_feeds(d, source_cfg.get("rss", {}).get("feeds", [])),
        "career_sites": lambda d: careers.career_sites(d, employers or [], career_report),
    }
    deadline = time.monotonic() + FEED_BUDGET_MINUTES * 60
    results: dict[str, list[Job]] = {}

    def read(name: str, fn) -> None:
        found: list[Job] = []
        results[name] = found
        try:
            cut_short = False
            for job in fn(days):
                found.append(job)
                if time.monotonic() > deadline:
                    cut_short = True
                    break
            status[name] = {"status": "ok", "count": len(found)}
            if cut_short:
                status[name].update(status="partial", error=f"stopped after the {FEED_BUDGET_MINUTES:g}-minute time budget; kept {len(found)} adverts")
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
            status[name] = {"status": "error", "count": len(found), "error": str(err)[:300]}

    wanted = {}
    for name, fn in feeds.items():
        if not source_cfg.get(name, {}).get("enabled", True):
            status[name] = {"status": "disabled"}
        else:
            wanted[name] = fn
    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
        for future in [pool.submit(read, name, fn) for name, fn in wanted.items()]:
            future.result()
    return [job for name in feeds for job in results.get(name, [])]


def enrich(jobs: Iterable[Job], index: sponsors.SponsorIndex, tiers: TierRules,
           contacts: ContactBook, days: int, agencies: AgencyFilter | None = None,
           stats: dict | None = None) -> list[Job]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stats = stats if stats is not None else {}
    stats.setdefault("agency_removed", 0)
    kept: dict[tuple, Job] = {}
    now = datetime.now(timezone.utc)
    undated: dict[str, int] = {}
    for job in jobs:
        if not job.title or not job.url:
            continue
        if job.posted_at == UNDATED:
            # No posting date in the advert: keep it, marked, dated the day it was found (a capped number per source, as there is
            # no way to tell a new advert from an old one).
            undated[job.source] = undated.get(job.source, 0) + 1
            if undated[job.source] > MAX_UNDATED_PER_SOURCE:
                continue
            job.posted_at, job.date_known = now, False
        elif job.posted_at < cutoff:
            continue
        if job.country not in COUNTRIES:
            continue
        # Career-site jobs are the employer's own adverts by definition.
        if agencies and job.channel != "career_site" and agencies.is_agency(job.company, job.description):
            stats["agency_removed"] += 1
            continue

        signal, evidence = sponsorship_evidence(f"{job.title}. {job.description}")
        entry = index.lookup(job.register_name or job.company, job.country)
        # Career sites and named-employer searches know the employer, so a group prefix match is safe.
        if (job.channel == "career_site" or job.register_name) and (
                entry is None or sponsors.REGISTER_COUNTRY.get(entry.register) != job.country):
            entry = (index.lookup_prefix(job.register_name or job.company, job.country)
                     or (job.register_name and index.lookup_prefix(job.company, job.country)) or entry)
        if job.country in LOCAL_COUNTRIES:
            # India: the role is in the candidate's home country, so sponsorship is not a question.
            job.sponsorship = "local"
        elif job.country == "IE":
            # Ireland: Stamp 1G graduates can take any job without a permit; keep every role the advert
            # doesn't close to them ("Stamp 4 required", "EU citizens only").
            if stamp1g_status(job) == "excluded":
                continue
            if signal == "positive" or (job.source_says_sponsorship and signal != "negative"):
                job.sponsorship = "confirmed"
            elif signal == "possible":
                job.sponsorship = "possible"
            elif signal != "negative" and entry and sponsors.REGISTER_COUNTRY.get(entry.register) == "IE":
                # Issued employment permits this year or last: Ireland's record of who sponsors.
                job.sponsorship = "licensed_sponsor"
            else:
                # No sponsorship evidence, or the advert rules sponsorship out: shown only when Stamp 1G is ticked.
                job.sponsorship = "stamp_1g"
        elif signal == "negative":
            if classify_early_career(job) == "stated":
                # No sponsorship, but the advert welcomes Graduate visa (PSW) / OPT holders, who need none.
                job.sponsorship = "graduate_route"
                job.early_career = "stated"
            else:
                # Kept and labelled with the advert's words, so candidates see why not to apply.
                job.sponsorship = "not_sponsored"
        elif signal == "positive" or job.source_says_sponsorship:
            job.sponsorship = "confirmed"
        elif signal == "possible":
            job.sponsorship = "possible"
        elif entry and sponsors.REGISTER_COUNTRY.get(entry.register) == job.country:
            # Employer holds a sponsor licence in the job's country; the advert is silent.
            job.sponsorship = "licensed_sponsor"
        elif job.country in EMPLOYER_VISA_COUNTRIES:
            job.sponsorship = "employer_visa"
        else:
            continue
        # Quote the advert's own words when they decide the label, so candidates can check it.
        if (job.sponsorship, signal) in (("confirmed", "positive"), ("possible", "possible")):
            job.sponsorship_evidence = evidence
        elif job.sponsorship in ("graduate_route", "stamp_1g", "not_sponsored") and signal == "negative":
            job.sponsorship_evidence = evidence
        if entry:
            job.sponsor_register = entry.register
            job.sponsor_routes = sorted(entry.routes)

        job.sector = classify_sector(job)
        job.domain = classify_domain(job)
        job.role = classify_role(job)
        job.aviation = classify_aviation(job)
        job.low_sponsorship = is_low_sponsorship(job)
        if job.sponsorship not in ("graduate_route", "stamp_1g", "not_sponsored", "local"):
            # Graduate visa / Stamp 1G holders need no sponsorship, so no salary minimum applies to them.
            job.salary_check, job.salary_annual, job.salary_threshold = salary_check(job)
        job.region = classify_region(job)
        job.english = job.country in ENGLISH_SPEAKING_COUNTRIES or classify_english(job)
        job.early_career = job.early_career or classify_early_career(job)
        job.tier, job.size = tiers.classify(job)
        job.kw, job.signals, job.text_len = digest(job.title, job.description)
        job.exp_years = required_years(job.description)
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
    # A copy that rules sponsorship out never hides one that offers it (two boards, two wordings).
    return (job.sponsorship != "not_sponsored", _CHANNEL_RANK.get(job.channel, 0), bool(job.contacts),
            job.sponsorship == "confirmed", job.date_known, job.posted_at)


def run(days: int, out_path: Path) -> dict:
    source_cfg = json.loads((CONFIG / "sources.json").read_text(encoding="utf-8"))
    employers = json.loads((CONFIG / "employers.json").read_text(encoding="utf-8")).get("employers", [])
    status: dict = {}
    index = load_sponsor_index(status)
    raw = fetch_all(days, source_cfg, status, employers)
    stats: dict = {}
    seen = previous_digests(out_path)
    stats["full_adverts_read"] = read_full_adverts(raw, seen)
    agencies = AgencyFilter.load(CONFIG / "agencies.json") if source_cfg.get("exclude_agencies", True) else None
    tiers = TierRules.load(CONFIG / "company_tiers.json")
    jobs = enrich(raw, index, tiers, ContactBook.load(CONFIG / "contacts.json"), days, agencies, stats)
    for job in jobs:
        reuse_digest(job, seen)
    link_employer_sites(jobs, CONFIG / "early_career_employers.json", employers)
    directory = build_directory(jobs, index, tiers, CONFIG / "early_career_employers.json")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days": days,
        "sectors": SECTORS,
        "domains": DOMAINS,
        "roles": ROLES,
        "aviation_families": AVIATION_FAMILIES,
        "channels": CHANNELS,
        "featured_countries": FEATURED_COUNTRIES,
        "sources": status,
        "counts": {"fetched": len(raw), "agency_removed": stats["agency_removed"], "published": len(jobs), "full_adverts_read": stats["full_adverts_read"]},
        "jobs": [j.to_dict() for j in jobs],
        "employers": directory,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return payload


def link_employer_sites(jobs: list[Job], path: Path, career_employers: list[dict] | None = None) -> None:
    """Give job-board adverts a link to the employer's own careers site, when the board knows it: the
    directory's employers (path) and every employer whose careers site the board reads (config/employers.json).

    Board links (Adzuna especially) can be closed to visitors outside the board's country; the careers site is not.
    """
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sites = {(normalise_company(e["name"]), e.get("country", "GB")): e["careers_url"]
             for e in cfg.get("employers", []) if e.get("careers_url")}
    # Career-site employers hire in many countries from one site: match them by name alone.
    anywhere = {normalise_company(e["name"]): page for e in career_employers or []
                if e.get("enabled", True) and (page := careers.careers_page(e))}
    for job in jobs:
        if job.channel != "career_site":
            key = normalise_company(job.company)
            job.employer_site = sites.get((key, job.country)) or anywhere.get(key, "")


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
        # Whether the country's register loaded this run: "not on it" and "couldn't check" differ.
        checked = any(index.counts.get(r) for r, c in sponsors.REGISTER_COUNTRY.items() if c == country)
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
            "register_checked": checked, "open_roles": len(live), "early_career_roles": sum(bool(j.early_career) for j in live),
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
            "on_register": bool(first.sponsor_register), "register": first.sponsor_register, "register_checked": True,
            "open_roles": len(live), "early_career_roles": len(early), "curated": False,
        }
    return sorted(rows.values(), key=lambda r: (-r["early_career_roles"], r["tier"], r["name"].lower()))
