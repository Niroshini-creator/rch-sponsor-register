"""Build one candidate's board: shared feed + candidate-specific searches → label → score → rank → candidates/data/<slug>.json."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jobfeed import sponsors
from jobfeed.agencies import AgencyFilter
from jobfeed.classify import (TierRules, classify_domain, classify_early_career, classify_role, classify_sector,
                              sponsorship_evidence)
from jobfeed.models import Job
from jobfeed.sources import SkipSource
from jobfeed.text import normalise_company, parse_date

from . import sources, taxonomy
from .match import SPONSORSHIP, Matcher

log = logging.getLogger("candidateboard")
ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "candidates" / "profiles"
DATA = ROOT / "candidates" / "data"
FEED = ROOT / "data" / "jobs.json"
MAX_JOBS = 700
DEEP_MAX = int(os.environ.get("CANDIDATE_DEEP_MAX", "60"))
DEEP_PAUSE = float(os.environ.get("CANDIDATE_DEEP_PAUSE", "0.3"))
OTHER_ROLES_EXTRA = 5
DEEP_MIN_MATCH = 45                  # worth reading in full once the extract already scores this well
OFFERED = ("confirmed", "possible", "licensed_sponsor", "employer_visa")
_CHANNEL_RANK = {"career_site": 2, "official": 1, "aggregator": 0}


def load_profile(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- what to search for
def search_terms(profile: dict, limit: int = 28) -> list[str]:
    """Role titles to search, best tiers first, then a couple of searches for each 'other roles' family."""
    tax = taxonomy.load()
    terms: list[str] = []
    for r in sorted(profile["roles"], key=lambda r: r["tier"]):
        if r["title"] not in terms:
            terms.append(r["title"])
    terms = terms[:limit - 8]
    for fam in profile.get("also_consider", []):
        for q in tax.families[fam].searches[:1]:
            if q not in terms:
                terms.append(q)
    return terms[:limit]


# ----------------------------------------------------------------------------- the shared feed
def feed_jobs(path: Path, days: int, countries: set[str]) -> tuple[list[dict], dict]:
    if not Path(path).exists():
        return [], {"status": "skipped", "reason": f"{path} not found"}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    jobs = [j for j in data.get("jobs", []) if j.get("country") in countries
            and (parse_date(j.get("posted_at")) or cutoff) >= cutoff]
    return jobs, {"status": "ok", "count": len(jobs), "feed_generated_at": data.get("generated_at", "")}


# ----------------------------------------------------------------------------- candidate searches
def fetch_fresh(profile: dict, days: int, status: dict) -> list[Job]:
    terms = search_terms(profile)
    feeds = {"Reed": lambda: sources.reed(days, terms), "Adzuna": lambda: sources.adzuna(days, terms),
             "NHS Jobs": lambda: sources.nhs(days, terms[:12]), "jobs.ac.uk": lambda: sources.universities(days, terms[:12])}
    jobs: list[Job] = []
    for name, make in feeds.items():
        before = len(jobs)
        try:
            jobs.extend(make())
            status[name] = {"status": "ok", "count": len(jobs) - before}
        except SkipSource as why:
            status[name] = {"status": "skipped", "reason": str(why)}
        except Exception as err:  # noqa: BLE001 - keep what the other sources returned
            log.warning("source %s failed: %s", name, err)
            log.debug(traceback.format_exc())
            status[name] = {"status": "error", "count": len(jobs) - before, "error": str(err)[:300]}
    return jobs


def classify_sponsorship(text: str, job: Job, index: sponsors.SponsorIndex | None, is_agency: bool) -> tuple[str, str, object]:
    signal, evidence = sponsorship_evidence(text)
    entry = None
    if index:
        entry = index.lookup(job.register_name or job.company, "GB")
        if job.channel == "career_site" and entry is None:
            entry = index.lookup_prefix(job.register_name or job.company, "GB")
    if signal == "negative":
        return ("graduate_route" if classify_early_career(job) == "stated" else "not_sponsored"), evidence, entry
    if signal == "positive" or job.source_says_sponsorship:
        return "confirmed", evidence, entry
    if signal == "possible":
        return "possible", evidence, entry
    if entry and sponsors.REGISTER_COUNTRY.get(entry.register) == "GB":
        return "licensed_sponsor", "", entry
    return ("agency" if is_agency else "unverified"), "", entry


def enrich_fresh(jobs: list[Job], days: int, countries: set[str], index, tiers: TierRules,
                 agencies: AgencyFilter | None) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for job in jobs:
        if job.posted_at < cutoff or not (job.title and job.url) or job.country not in countries:
            continue
        agency = bool(agencies and job.channel != "career_site" and agencies.is_agency(job.company, job.description))
        status, evidence, entry = classify_sponsorship(f"{job.title}. {job.description}", job, index, agency)
        job.sector, job.domain, job.role = classify_sector(job), classify_domain(job), classify_role(job)
        tier, size = tiers.classify(job)
        rec = job.to_dict(description_chars=500)
        rec.update(sponsorship=status, sponsorship_evidence=evidence, employer_tier=tier, size=size,
                   sponsor_register=entry.register if entry else "", sponsor_routes=sorted(entry.routes) if entry else [],
                   full_text=job.description)
        rec.pop("tier", None)
        out.append(rec)
    return out


def deepen(recs: list[dict], matcher: Matcher, stats: dict, reed_full=sources.reed_full_text,
           page_text=sources.advert_page_text) -> None:
    """Read the whole advert for the best-scoring Reed and NHS adverts: clearance, licence and sponsorship wording
    often sits below the short snippet the search APIs return. Capped per run."""
    stats.setdefault("full_advert_read", 0)
    ranked = []
    for r in recs:
        if r.get("source") not in ("Reed", "NHS Jobs") or len(r.get("full_text") or r["description"]) > 1500:
            continue
        ev = matcher.evaluate(r)
        if ev and ev["match"] >= DEEP_MIN_MATCH:
            ranked.append((ev["match"], r))
    ranked.sort(key=lambda x: x[0], reverse=True)
    for _, r in ranked[:DEEP_MAX]:
        try:
            text = reed_full(r["source_id"]) if r["source"] == "Reed" else page_text(r["url"])
        except SkipSource:
            return
        except Exception as err:  # noqa: BLE001 - keep the snippet when one advert can't be read
            log.warning("full advert %s unavailable: %s", r.get("url"), err)
            continue
        if len(text) > len(r.get("full_text") or ""):
            r["full_text"] = text
            stats["full_advert_read"] += 1
            refine_sponsorship(r)
        time.sleep(DEEP_PAUSE)


def refine_sponsorship(rec: dict) -> None:
    """The full advert may state what the extract did not. A refusal always wins; an offer upgrades 'licensed'."""
    signal, evidence = sponsorship_evidence(rec["full_text"])
    if signal == "negative" and rec["sponsorship"] in ("confirmed", "possible", "licensed_sponsor", "unverified", "agency"):
        rec["sponsorship"], rec["sponsorship_evidence"] = "not_sponsored", evidence
    elif signal == "positive" and rec["sponsorship"] in ("licensed_sponsor", "unverified", "agency", "possible"):
        rec["sponsorship"], rec["sponsorship_evidence"] = "confirmed", evidence
    elif signal == "possible" and rec["sponsorship"] in ("licensed_sponsor", "unverified", "agency"):
        rec["sponsorship"], rec["sponsorship_evidence"] = "possible", evidence


# ----------------------------------------------------------------------------- score, dedupe, rank
def _rank(rec: dict) -> tuple:
    return (-SPONSORSHIP.get(rec["sponsorship"], SPONSORSHIP["unverified"])[1], _CHANNEL_RANK.get(rec.get("channel"), 0),
            len(rec.get("full_text") or ""), rec["posted_at"])


def build(recs: list[dict], matcher: Matcher, profile: dict, days: int, stats: dict) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    countries = set(profile.get("countries", ["GB"]))
    min_match = profile.get("min_match", 40)
    best: dict[tuple, dict] = {}
    for rec in recs:
        posted = parse_date(rec.get("posted_at"))
        if not posted or posted < cutoff or rec.get("country") not in countries or not (rec.get("title") and rec.get("url")):
            continue
        ev = matcher.evaluate(rec)
        if not ev:
            stats["not_relevant"] += 1
            continue
        # "Other roles" (tier 4) are a different route for the same skills: held to a higher bar, at employers that can
        # sponsor, and never above the candidate's level.
        if ev["match"] < min_match + (OTHER_ROLES_EXTRA if ev["tier"] == 4 else 0):
            stats["below_threshold"] += 1
            continue
        if ev["tier"] == 4 and (not ev["sponsorship_offered"] or ev["flags"]):
            stats["other_roles_without_sponsor"] += 1
            continue
        out = {k: v for k, v in rec.items() if k not in ("full_text", "tier", "contacts")}
        if "employer_tier" not in out:
            out["employer_tier"] = rec.get("tier", 3)
        out.update(ev)
        out["description"] = (rec.get("full_text") or rec.get("description") or "")[:500]
        title, company, city = (" ".join(rec["title"].lower().split()), normalise_company(rec["company"]),
                                rec.get("location", "").lower().split(",")[0].strip())
        key = (title, company, city)
        if key not in best or (_rank(rec), ev["match"]) > (_rank(best[key]["_src"]), best[key]["match"]):
            out["_src"] = rec
            best[key] = out
    result = []
    for r in best.values():
        r.pop("_src")
        result.append(r)
    result.sort(key=lambda r: (r["tier"], -r["match"], r["sponsorship_rank"], r["posted_at"]), reverse=False)
    return result[:MAX_JOBS]


def fingerprint(profile: dict) -> str:
    """Changes whenever the profile or the role/skill rules change, so old results scored under other rules are not kept."""
    blob = json.dumps(profile, sort_keys=True) + (Path(__file__).parent / "roles.json").read_text(encoding="utf-8")
    for module in ("match.py", "checks.py"):
        blob += (Path(__file__).parent / module).read_text(encoding="utf-8")
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def merge_previous(fresh: list[dict], path: Path, days: int, now: datetime, version: str = "") -> list[dict]:
    """Earlier finds still inside the window stay, so a bad day at one source never empties the board."""
    cutoff = now - timedelta(days=days)
    merged = {r["id"]: r for r in fresh}
    first_seen = {}
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            keep_old = not version or previous.get("rules_version") == version
            for old in previous.get("jobs", []):
                first_seen[old["id"]] = old.get("first_seen") or old["posted_at"]
                if keep_old and old["id"] not in merged and (parse_date(old["posted_at"]) or cutoff) >= cutoff:
                    merged[old["id"]] = old
        except (ValueError, KeyError, json.JSONDecodeError):
            log.warning("previous board unreadable; starting clean")
    for r in merged.values():
        r["first_seen"] = first_seen.get(r["id"], now.isoformat(timespec="seconds"))
    return sorted(merged.values(), key=lambda r: (r["tier"], -r["match"], r["sponsorship_rank"]))


# ----------------------------------------------------------------------------- run
def candidate_summary(profile: dict) -> dict:
    tax = taxonomy.load()
    keep = ("slug", "name", "headline", "base_location", "current_status", "experience_years", "education", "visa",
            "clearance", "driving_licence", "min_match", "countries", "tracks", "roles", "notes")
    summary = {k: profile.get(k) for k in keep}
    summary["tracks"] = [{"name": t["name"], "cv": t.get("cv"), "headline": t.get("headline"), "skills": t.get("skills", [])}
                         for t in profile["tracks"]]
    summary["also_consider"] = [{"key": k, "label": tax.families[k].label, "sponsorability": tax.families[k].sponsor}
                                for k in profile.get("also_consider", [])]
    return summary


def run(profile_path: Path, days: int = 0, feed: Path = FEED, out_dir: Path = DATA, offline: bool = False) -> dict:
    profile = load_profile(profile_path)
    days = days or profile.get("window_days", 7)
    now = datetime.now(timezone.utc)
    countries = set(profile.get("countries", ["GB"]))
    status: dict = {}
    matcher = Matcher(profile)

    recs, status["Shared sponsor feed"] = feed_jobs(feed, days, countries)
    stats = {"not_relevant": 0, "below_threshold": 0, "other_roles_without_sponsor": 0}
    if offline:
        status["Candidate searches"] = {"status": "skipped", "reason": "offline run"}
    else:
        index = sponsors.SponsorIndex()
        try:
            sponsors.load_uk_register(index)
            status["UK sponsor register"] = {"status": "ok", "count": len(index)}
        except Exception as err:  # noqa: BLE001
            index = None
            status["UK sponsor register"] = {"status": "error", "error": str(err)[:300]}
        agencies = AgencyFilter.load(ROOT / "config" / "agencies.json")
        tiers = TierRules.load(ROOT / "config" / "company_tiers.json")
        recs += enrich_fresh(fetch_fresh(profile, days, status), days, countries, index, tiers, agencies)
        deepen(recs, matcher, stats)
    fresh = build(recs, matcher, profile, days, stats)
    out_path = Path(out_dir) / f"{profile['slug']}.json"
    version = fingerprint(profile)
    jobs = merge_previous(fresh, out_path, days, now, version)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"), "window_days": days, "rules_version": version,
        "candidate": candidate_summary(profile), "sources": status,
        "counts": {"considered": len(recs), **stats, "published": len(jobs),
                   "by_tier": {str(t): sum(1 for j in jobs if j["tier"] == t) for t in (1, 2, 3, 4)}},
        "jobs": jobs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_index(Path(out_dir), Path(PROFILES) if Path(profile_path).parent == PROFILES else Path(profile_path).parent)
    return payload


def write_index(data_dir: Path, profiles_dir: Path) -> None:
    """candidates/data/index.json: the list the /candidates/ page opens on."""
    items = []
    for path in sorted(Path(profiles_dir).glob("*.json")):
        profile = load_profile(path)
        board = data_dir / f"{profile['slug']}.json"
        counts, generated = {}, ""
        if board.exists():
            payload = json.loads(board.read_text(encoding="utf-8"))
            counts, generated = payload.get("counts", {}), payload.get("generated_at", "")
        items.append({"slug": profile["slug"], "name": profile["name"], "headline": profile.get("headline", ""),
                      "visa": (profile.get("visa") or {}).get("label", ""), "visa_expires": (profile.get("visa") or {}).get("expires", ""),
                      "published": counts.get("published", 0), "by_tier": counts.get("by_tier", {}), "generated_at": generated})
    (data_dir / "index.json").write_text(json.dumps({"candidates": items}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
