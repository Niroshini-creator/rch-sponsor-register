"""Direct employer career sites.

Most employers publish their careers page through an applicant tracking system (ATS)
that exposes a public, unauthenticated job feed. Reading that feed gives the same
vacancies (and the same Apply link) as the employer's own careers page, with no
recruitment agency in between.

Employers are listed in config/employers.json:

    {"name": "Monzo", "ats": "greenhouse", "id": "monzo", "country": "GB"}

`id` is the employer's board name in the ATS; find it in the careers page URL
(boards.greenhouse.io/<id>, jobs.lever.co/<id>, jobs.ashbyhq.com/<id>,
<id>.recruitee.com, <id>.jobs.personio.de, apply.workable.com/<id>,
jobs.smartrecruiters.com/<id>). Workday also needs `host` and `site`, taken from
https://<host>/<site> e.g. host "gsk.wd5.myworkdayjobs.com", site "GSKCareers".
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

from . import http
from .models import Job
from .sources import _guess_country, _local
from .text import parse_date, strip_html

log = logging.getLogger("jobfeed")

EUROPE_AND_UK = {"GB", "IE", "DE", "NL", "FR", "BE", "AT", "CH", "ES", "IT", "PL", "PT", "SE", "DK", "FI", "NO",
                 "CZ", "LU", "EE", "GR", "RO", "HU", "LT", "LV", "SK", "SI", "HR", "BG", "CY", "MT", "IS"}

EmployerFeed = Callable[[dict, datetime], Iterator[Job]]


def _job(emp: dict, **kw) -> Job:
    location = kw.pop("location", "") or ""
    # Global employers list jobs worldwide, so an unrecognised location is not assumed to be
    # in the employer's home country unless the config marks every vacancy as local.
    fallback = emp.get("country", "GB") if (emp.get("local") or not location.strip()) else ""
    country = kw.pop("country", "") or _guess_country(location, default=fallback)
    return Job(source=f"{emp['name']} careers", channel="career_site", company=emp["name"],
               register_name=emp.get("register_name", ""), location=location, country=country.upper()[:2], **kw)


# ----------------------------------------------------------------------------- Greenhouse
def greenhouse(emp: dict, cutoff: datetime) -> Iterator[Job]:
    data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{emp['id']}/jobs", params={"content": "true"})
    for j in data.get("jobs", []):
        posted = parse_date(j.get("first_published") or j.get("updated_at"))
        if posted and posted >= cutoff:
            yield _job(emp, source_id=str(j["id"]), title=j.get("title", ""),
                       location=(j.get("location") or {}).get("name", ""), url=j.get("absolute_url", ""),
                       posted_at=posted, description=strip_html(j.get("content")))


# ----------------------------------------------------------------------------- Lever
def lever(emp: dict, cutoff: datetime) -> Iterator[Job]:
    host = "api.eu.lever.co" if emp.get("region") == "eu" else "api.lever.co"
    for j in http.get_json(f"https://{host}/v0/postings/{emp['id']}", params={"mode": "json"}):
        posted = parse_date((j.get("createdAt") or 0) / 1000)
        if posted and posted >= cutoff:
            lists = " ".join(f"{li.get('text', '')} {strip_html(li.get('content'))}" for li in j.get("lists") or [])
            yield _job(emp, source_id=j["id"], title=j.get("text", ""),
                       location=(j.get("categories") or {}).get("location", ""), country=j.get("country") or "",
                       url=j.get("hostedUrl", ""), posted_at=posted,
                       description=" ".join(filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")])),
                       contract=(j.get("categories") or {}).get("commitment", ""))


# ----------------------------------------------------------------------------- Ashby
def ashby(emp: dict, cutoff: datetime) -> Iterator[Job]:
    data = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{emp['id']}")
    for j in data.get("jobs", []):
        posted = parse_date(j.get("publishedAt"))
        if j.get("isListed", True) and posted and posted >= cutoff:
            addr = ((j.get("address") or {}).get("postalAddress") or {})
            yield _job(emp, source_id=j["id"], title=j.get("title", ""), location=j.get("location", ""),
                       country=_iso(addr.get("addressCountry")), url=j.get("jobUrl", ""), posted_at=posted,
                       description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
                       contract=j.get("employmentType", ""))


# ----------------------------------------------------------------------------- SmartRecruiters
def smartrecruiters(emp: dict, cutoff: datetime) -> Iterator[Job]:
    base = f"https://api.smartrecruiters.com/v1/companies/{emp['id']}/postings"
    for offset in range(0, 1000, 100):
        page = http.get_json(base, params={"limit": 100, "offset": offset})
        content = page.get("content", [])
        for j in content:
            posted = parse_date(j.get("releasedDate"))
            if not posted or posted < cutoff:
                continue
            loc = j.get("location") or {}
            if loc.get("country") and loc["country"].upper() not in EUROPE_AND_UK:
                continue
            # The list omits the advert text; one extra call per recent UK/Europe posting fetches it.
            try:
                detail = http.get_json(f"{base}/{j['id']}")
                sections = (detail.get("jobAd") or {}).get("sections") or {}
                description = " ".join(strip_html(s.get("text")) for s in sections.values() if isinstance(s, dict))
                url = detail.get("postingUrl") or detail.get("applyUrl") or ""
            except Exception:  # noqa: BLE001 - keep the posting even without its text
                description, url = "", ""
            yield _job(emp, source_id=j["id"], title=j.get("name", ""),
                       location=", ".join(filter(None, [loc.get("city"), loc.get("region")])),
                       country=loc.get("country", ""), posted_at=posted, description=description,
                       url=url or f"https://jobs.smartrecruiters.com/{emp['id']}/{j['id']}")
        if len(content) < 100:
            break


# ----------------------------------------------------------------------------- Workable
def workable(emp: dict, cutoff: datetime) -> Iterator[Job]:
    data = http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{emp['id']}", params={"details": "true"})
    for j in data.get("jobs", []):
        posted = parse_date(j.get("published_on") or j.get("created_at"))
        if posted and posted >= cutoff:
            yield _job(emp, source_id=j.get("shortcode", ""), title=j.get("title", ""),
                       location=", ".join(filter(None, [j.get("city"), j.get("country")])),
                       country=_iso(j.get("country")), url=j.get("url") or j.get("application_url", ""),
                       posted_at=posted, description=strip_html(j.get("description")),
                       contract=j.get("employment_type", ""))


# ----------------------------------------------------------------------------- Recruitee
def recruitee(emp: dict, cutoff: datetime) -> Iterator[Job]:
    data = http.get_json(f"https://{emp['id']}.recruitee.com/api/offers/")
    for j in data.get("offers", []):
        posted = parse_date(j.get("published_at") or j.get("created_at"))
        if posted and posted >= cutoff:
            yield _job(emp, source_id=str(j["id"]), title=j.get("title", ""), location=j.get("location", ""),
                       country=j.get("country_code", ""), url=j.get("careers_url", ""), posted_at=posted,
                       description=strip_html(f"{j.get('description', '')} {j.get('requirements', '')}"),
                       contract=j.get("employment_type_code", ""))


# ----------------------------------------------------------------------------- Personio
def personio(emp: dict, cutoff: datetime) -> Iterator[Job]:
    tld = emp.get("tld", "de")
    root = ET.fromstring(http.get(f"https://{emp['id']}.jobs.personio.{tld}/xml"))
    for pos in (el for el in root.iter() if _local(el.tag) == "position"):
        f = {_local(c.tag): (c.text or "").strip() for c in pos}
        posted = parse_date(f.get("createdAt"))
        if not posted or posted < cutoff:
            continue
        description = " ".join(strip_html(el.text) for el in pos.iter() if _local(el.tag) == "value")
        yield _job(emp, source_id=f.get("id", ""), title=f.get("name", ""), location=f.get("office", ""),
                   url=f"https://{emp['id']}.jobs.personio.{tld}/job/{f.get('id', '')}", posted_at=posted,
                   description=description, contract=f.get("employmentType", ""))


# ----------------------------------------------------------------------------- Workday
_WORKDAY_AGE = re.compile(r"(\d+)\+?\s+days? ago", re.I)


def _workday_posted(text: str, now: datetime) -> datetime | None:
    """Workday lists relative dates: "Posted Today", "Posted Yesterday", "Posted 3 Days Ago", "Posted 30+ Days Ago"."""
    text = (text or "").lower()
    if "today" in text:
        return now
    if "yesterday" in text:
        return now - timedelta(days=1)
    m = _WORKDAY_AGE.search(text)
    return now - timedelta(days=int(m.group(1))) if m else None


def workday(emp: dict, cutoff: datetime) -> Iterator[Job]:
    host, tenant, site = emp["host"], emp.get("id") or emp["host"].split(".")[0], emp["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    now = datetime.now(timezone.utc)
    for offset in range(0, emp.get("max_jobs", 1000), 20):
        page = http.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset,
                                              "searchText": emp.get("search", "")})
        postings = page.get("jobPostings", [])
        for j in postings:
            posted = _workday_posted(j.get("postedOn", ""), now)
            if not posted or posted < cutoff:
                continue
            # Skip the detail call for roles clearly outside the UK/Europe ("3 Locations" is checked).
            listed = _guess_country(j.get("locationsText", ""), default="")
            if listed and listed not in EUROPE_AND_UK:
                continue
            path = j.get("externalPath", "")
            try:
                info = http.get_json(f"{api}{path}").get("jobPostingInfo", {})
            except Exception:  # noqa: BLE001
                info = {}
            yield _job(emp, source_id=info.get("jobReqId") or path, title=j.get("title", ""),
                       location=info.get("location") or j.get("locationsText", ""),
                       country=_iso((info.get("country") or {}).get("descriptor")),
                       url=info.get("externalUrl") or f"https://{host}/{site}{path}", posted_at=posted,
                       description=strip_html(info.get("jobDescription")), contract=info.get("timeType", ""))
        if len(postings) < 20:
            break


# ----------------------------------------------------------------------------- driver
ATS: dict[str, EmployerFeed] = {
    "greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters,
    "workable": workable, "recruitee": recruitee, "personio": personio, "workday": workday,
}


def career_sites(days: int, employers: list[dict], report: dict) -> Iterator[Job]:
    """Yield jobs from every configured employer; one broken board never stops the others."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    report.update(ok=0, failed=[])
    for emp in employers:
        if emp.get("enabled", True) is False:
            continue
        feed = ATS.get(emp.get("ats", "").lower())
        if not feed:
            report["failed"].append(f"{emp.get('name')}: unknown ATS '{emp.get('ats')}'")
            continue
        try:
            yield from feed(emp, cutoff)
            report["ok"] += 1
        except Exception as err:  # noqa: BLE001
            log.warning("career site %s (%s) failed: %s", emp.get("name"), emp.get("ats"), err)
            report["failed"].append(f"{emp.get('name')}: {str(err)[:120]}")


_COUNTRY_NAMES = {
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "ireland": "IE", "germany": "DE", "netherlands": "NL", "france": "FR",
    "spain": "ES", "italy": "IT", "belgium": "BE", "austria": "AT", "switzerland": "CH", "poland": "PL",
    "portugal": "PT", "sweden": "SE", "denmark": "DK", "finland": "FI", "norway": "NO", "czechia": "CZ",
    "czech republic": "CZ", "luxembourg": "LU", "estonia": "EE", "greece": "GR", "romania": "RO",
    "hungary": "HU", "lithuania": "LT", "latvia": "LV", "united states": "US", "usa": "US", "canada": "CA",
    "india": "IN", "singapore": "SG", "australia": "AU",
}


def _iso(country: str | None) -> str:
    """Accept an ISO code or an English country name; return ISO alpha-2 or ""."""
    if not country:
        return ""
    c = country.strip()
    if len(c) == 2:
        return "GB" if c.upper() == "UK" else c.upper()
    return _COUNTRY_NAMES.get(c.lower(), "")
