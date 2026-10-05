"""UK job sources for the candidate's searches. Reuses the shared HTTP and date helpers; touches nothing else.

Reed and Adzuna are official job-board APIs (free keys, the same secrets the main board uses). LinkedIn, Indeed
and Glassdoor offer no public search API and forbid scraping, so they are not read here; Adzuna re-lists many
Indeed / agency adverts. Employer career feeds come from config/employers.json.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

from jobfeed import careers, http
from jobfeed.models import Job
from jobfeed.sources import SkipSource, _salary
from jobfeed.text import parse_date, strip_html

log = logging.getLogger("mugilan")
ADZUNA_PAUSE = float(os.environ.get("ADZUNA_PAUSE", "2.5"))
ADZUNA_MAX_CALLS = int(os.environ.get("MUGILAN_ADZUNA_MAX_CALLS", "80"))


def reed(days: int, searches: list[str]) -> Iterator[Job]:
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise SkipSource("REED_API_KEY not set")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for query in searches:
        for skip in range(0, 300, 100):
            data = http.get_json("https://www.reed.co.uk/api/1.0/search",
                                 params={"keywords": query, "resultsToTake": 100, "resultsToSkip": skip,
                                         "minimumSalary": 50000},
                                 basic_auth=(key, ""))
            results = data.get("results", [])
            for r in results:
                posted = parse_date(r.get("date"))
                if not posted or posted < cutoff:
                    continue
                yield Job(source="Reed", source_id=str(r.get("jobId")), title=r.get("jobTitle", ""),
                          company=r.get("employerName", ""), location=r.get("locationName", ""), country="GB",
                          url=r.get("jobUrl", ""), posted_at=posted,
                          description=strip_html(r.get("jobDescription")),
                          salary=_salary(r.get("minimumSalary"), r.get("maximumSalary")))
            if len(results) < 100:
                break


def adzuna(days: int, searches: list[str]) -> Iterator[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    calls = 0
    for query in searches:
        for page in (1, 2):
            if calls >= ADZUNA_MAX_CALLS:
                return
            if calls:
                time.sleep(ADZUNA_PAUSE)
            calls += 1
            data = http.get_json(f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}",
                                 params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                                         "max_days_old": days, "sort_by": "date", "what_phrase": query})
            results = data.get("results", [])
            for r in results:
                posted = parse_date(r.get("created"))
                if not posted or posted < cutoff:
                    continue
                yield Job(source="Adzuna", source_id=str(r.get("id")), title=strip_html(r.get("title")),
                          company=(r.get("company") or {}).get("display_name", ""),
                          location=(r.get("location") or {}).get("display_name", ""), country="GB",
                          url=r.get("redirect_url", ""), posted_at=posted,
                          description=strip_html(r.get("description")),
                          salary=_salary(r.get("salary_min"), r.get("salary_max")),
                          contract=r.get("contract_time") or "")
            if len(results) < 50:
                break


def career_feeds(days: int, employers: list[dict], report: dict) -> Iterator[Job]:
    yield from careers.career_sites(days, employers, report)


def reed_full_text(job_id: str) -> str:
    """Full advert text from Reed's job-details endpoint (the search endpoint only returns a short snippet)."""
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise SkipSource("REED_API_KEY not set")
    data = http.get_json(f"https://www.reed.co.uk/api/1.0/jobs/{job_id}", basic_auth=(key, ""))
    return strip_html(data.get("jobDescription"))
