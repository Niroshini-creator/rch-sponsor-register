"""Candidate-specific searches. Each takes the candidate's role titles and returns normalised `Job`s.

Reed and Adzuna are official APIs (the same free keys the main board uses). NHS Jobs and jobs.ac.uk reuse the main
board's readers with the candidate's keywords. Schools (Teaching Vacancies has no keyword search), employer career
sites and everything else come from the main board's shared feed, which is rebuilt every two hours.
LinkedIn, Indeed and Glassdoor offer no public search API and forbid scraping, so they are not read.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

from jobfeed import http, sources as shared
from jobfeed.models import Job
from jobfeed.sources import SkipSource, _salary
from jobfeed.text import parse_date, strip_html

log = logging.getLogger("candidateboard")
ADZUNA_PAUSE = float(os.environ.get("ADZUNA_PAUSE", "2.5"))
ADZUNA_MAX_CALLS = int(os.environ.get("CANDIDATE_ADZUNA_MAX_CALLS", "100"))
REED_PAGES = 2


def reed(days: int, queries: list[str]) -> Iterator[Job]:
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise SkipSource("REED_API_KEY not set")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for query in queries:
        for skip in range(0, 100 * REED_PAGES, 100):
            data = http.get_json("https://www.reed.co.uk/api/1.0/search", basic_auth=(key, ""),
                                 params={"keywords": query, "resultsToTake": 100, "resultsToSkip": skip,
                                         "postedByDirectEmployer": "true"})
            results = data.get("results", [])
            for r in results:
                posted = parse_date(r.get("date"))
                if posted and posted >= cutoff:
                    yield Job(source="Reed", source_id=str(r.get("jobId")), title=r.get("jobTitle", ""),
                              company=r.get("employerName", ""), location=r.get("locationName", ""), country="GB",
                              url=r.get("jobUrl", ""), posted_at=posted, description=strip_html(r.get("jobDescription")),
                              salary=_salary(r.get("minimumSalary"), r.get("maximumSalary")))
            if len(results) < 100:
                break


def adzuna(days: int, queries: list[str]) -> Iterator[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    calls = 0
    for query in queries:
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
                if posted and posted >= cutoff:
                    yield Job(source="Adzuna", source_id=str(r.get("id")), title=strip_html(r.get("title")),
                              company=(r.get("company") or {}).get("display_name", ""),
                              location=(r.get("location") or {}).get("display_name", ""), country="GB",
                              url=r.get("redirect_url", ""), posted_at=posted, description=strip_html(r.get("description")),
                              salary=_salary(r.get("salary_min"), r.get("salary_max")), contract=r.get("contract_time") or "")
            if len(results) < 50:
                break


def nhs(days: int, queries: list[str]) -> Iterator[Job]:
    yield from shared.nhs_jobs(days, keywords=tuple(queries))


def universities(days: int, queries: list[str]) -> Iterator[Job]:
    yield from shared.jobs_ac_uk(days, queries=tuple(queries))


def reed_full_text(job_id: str) -> str:
    """Full advert text from Reed's job-details endpoint (search only returns a short snippet)."""
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise SkipSource("REED_API_KEY not set")
    return strip_html(http.get_json(f"https://www.reed.co.uk/api/1.0/jobs/{job_id}", basic_auth=(key, "")).get("jobDescription"))


def advert_page_text(url: str) -> str:
    return shared._advert_text(url)
