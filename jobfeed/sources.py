"""Job source connectors.

Each connector yields `Job` objects posted within the requested window. Connectors
that need API keys are skipped (not failed) when the key is missing, so the
pipeline always produces output from whatever sources are available.
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

from . import http
from .models import Job
from .text import parse_date, strip_html

log = logging.getLogger("jobfeed")

# Adzuna country codes covered, mapped to ISO 3166 codes.
ADZUNA_COUNTRIES = {
    "gb": "GB", "us": "US", "nl": "NL", "pl": "PL", "es": "ES", "ie": "IE", "de": "DE", "fr": "FR",
    "be": "BE", "at": "AT", "ch": "CH", "it": "IT",
}

# Extra keyword searches so the feed covers every domain, not only tech.
DOMAIN_QUERIES = [
    "visa sponsorship",
    "skilled worker visa",
    "sponsorship available engineer",
    "sponsorship available manager",
    "sponsorship available scientist",
    "sponsorship available nurse",
    "sponsorship available teacher",
    "sponsorship available lecturer",
    "sponsorship available analyst",
]

# One search per job family on the board (see classify.ROLES), each combined with "sponsorship".
ROLE_QUERIES = [
    "data analyst", "business analyst", "it support", "application support", "biomedical scientist",
    "logistics", "data scientist", "devops", "software developer", "engineer", "accountant", "hr",
    "digital marketing", "aviation", "project manager",
]
# Early-career searches for UK Graduate visa (PSW) and US OPT holders.
EARLY_CAREER_QUERIES = {"gb": ["graduate visa", "graduate scheme sponsorship"],
                        "us": ["opt", "h1b sponsorship", "new grad visa sponsorship"]}
ADZUNA_MAX_CALLS = int(os.environ.get("ADZUNA_MAX_CALLS", "200"))
ADZUNA_PAUSE = float(os.environ.get("ADZUNA_PAUSE", "2.5"))  # free tier allows ~25 calls a minute


class SkipSource(Exception):
    """Raised when a source is not configured (e.g. missing API key)."""


def _cutoff(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# --------------------------------------------------------------------------- Adzuna
def _adzuna_searches() -> Iterator[tuple[str, dict, int]]:
    """(country code, search params, max pages) in priority order, so the call budget covers the essentials first."""
    for code in ADZUNA_COUNTRIES:
        yield code, {"what_phrase": "visa sponsorship"}, 5 if code in ("gb", "us") else 2
    yield "gb", {"what_phrase": "visa sponsorship", "where": "Scotland"}, 3
    for code in ("gb", "us"):
        for words in EARLY_CAREER_QUERIES[code]:
            yield code, {"what_and": words}, 2
        for role in ROLE_QUERIES:
            yield code, {"what_and": f"sponsorship {role}"}, 2
    for query in DOMAIN_QUERIES[1:]:
        yield "gb", {"what_and": query}, 2
    for code in ("nl", "pl", "es"):
        yield code, {"what_and": "relocation english"}, 1


def adzuna(days: int) -> Iterator[Job]:
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        raise SkipSource("ADZUNA_APP_ID / ADZUNA_APP_KEY not set")
    cutoff = _cutoff(days)
    calls = 0
    for code, query, pages in _adzuna_searches():
        iso = ADZUNA_COUNTRIES[code]
        for page in range(1, pages + 1):
            if calls >= ADZUNA_MAX_CALLS:
                log.info("Adzuna call budget (%s) reached", ADZUNA_MAX_CALLS)
                return
            if calls:
                time.sleep(ADZUNA_PAUSE)
            calls += 1
            data = http.get_json(
                f"https://api.adzuna.com/v1/api/jobs/{code}/search/{page}",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                        "max_days_old": days, "sort_by": "date", **query},
            )
            results = data.get("results", [])
            for r in results:
                posted = parse_date(r.get("created"))
                if not posted or posted < cutoff:
                    continue
                lo, hi = r.get("salary_min"), r.get("salary_max")
                yield Job(
                    source="Adzuna", source_id=str(r.get("id")),
                    title=strip_html(r.get("title")),
                    company=(r.get("company") or {}).get("display_name", ""),
                    location=(r.get("location") or {}).get("display_name", ""),
                    country=iso, url=r.get("redirect_url", ""), posted_at=posted,
                    description=strip_html(r.get("description")),
                    salary=_salary(lo, hi), contract=r.get("contract_time") or "",
                )
            if len(results) < 50:
                break


# --------------------------------------------------------------------------- Reed (UK)
def reed(days: int) -> Iterator[Job]:
    key = os.environ.get("REED_API_KEY")
    if not key:
        raise SkipSource("REED_API_KEY not set")
    cutoff = _cutoff(days)
    queries = [(q, 500) for q in DOMAIN_QUERIES]
    queries += [(f"sponsorship {role}", 200) for role in ROLE_QUERIES]
    queries += [(q, 200) for q in EARLY_CAREER_QUERIES["gb"]]
    for query, limit in queries:
        for skip in range(0, limit, 100):
            data = http.get_json("https://www.reed.co.uk/api/1.0/search",
                                 params={"keywords": query, "resultsToTake": 100, "resultsToSkip": skip,
                                         "postedByDirectEmployer": "true"},
                                 basic_auth=(key, ""))
            results = data.get("results", [])
            for r in results:
                posted = parse_date(r.get("date"))
                if not posted or posted < cutoff:
                    continue
                yield Job(
                    source="Reed", source_id=str(r.get("jobId")),
                    title=r.get("jobTitle", ""), company=r.get("employerName", ""),
                    location=r.get("locationName", ""), country="GB",
                    url=r.get("jobUrl", ""), posted_at=posted,
                    description=strip_html(r.get("jobDescription")),
                    salary=_salary(r.get("minimumSalary"), r.get("maximumSalary")),
                )
            if len(results) < 100:
                break


# --------------------------------------------------------------------------- NHS Jobs
def nhs_jobs(days: int) -> Iterator[Job]:
    """NHS Jobs public XML search (England & Wales NHS employers)."""
    cutoff = _cutoff(days)
    for keyword in ("sponsorship", "skilled worker", "visa"):
        for page in range(1, 11):
            raw = http.get("https://www.jobs.nhs.uk/api/v1/search_xml",
                           params={"keyword": keyword, "page": page, "sort": "publicationDateDesc"})
            root = ET.fromstring(raw)
            # The feed calls each job <vacancyDetails> (older versions: <vacancy>).
            vacancies = [el for el in root.iter() if _local(el.tag) in ("vacancyDetails", "vacancy")]
            for v in vacancies:
                f = {_local(c.tag): (c.text or "").strip() for c in v}
                posted = parse_date(f.get("postDate") or f.get("postdate"))
                if not posted or posted < cutoff:
                    continue
                locations = [(el.text or "").strip() for el in v.iter() if _local(el.tag) == "location"]
                yield Job(
                    source="NHS Jobs", channel="official", source_id=f.get("id") or f.get("reference", ""),
                    title=f.get("title", ""), company=f.get("employer", ""),
                    location=", ".join(filter(None, locations)) or f.get("location", ""),
                    country="GB", url=f.get("url", ""), posted_at=posted,
                    description=strip_html(f.get("description")), salary=f.get("salary", ""),
                    contract=f.get("type", ""),
                )
            if not vacancies:
                break


# --------------------------------------------------------------------------- Teaching Vacancies (DfE)
def teaching_vacancies(days: int) -> Iterator[Job]:
    """DfE Teaching Vacancies open API (schools in England). Returns schema.org JobPostings."""
    cutoff = _cutoff(days)
    url = "https://teaching-vacancies.service.gov.uk/api/v1/jobs.json"
    for _ in range(50):
        data = http.get_json(url)
        postings = data.get("data", data if isinstance(data, list) else [])
        for p in postings:
            posted = parse_date(p.get("datePosted"))
            if not posted or posted < cutoff:
                continue
            org = p.get("hiringOrganization") or {}
            loc = p.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            flagged = any("visa" in k.lower() and v is True for k, v in p.items())
            yield Job(
                source="Teaching Vacancies", channel="official", source_id=str(p.get("identifier") or p.get("url")),
                title=p.get("title", ""), company=org.get("name", ""),
                location=", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion")])),
                country="GB", url=p.get("url", ""), posted_at=posted,
                description=strip_html(p.get("description")),
                salary=_schema_salary(p.get("baseSalary")),
                contract=", ".join(t.replace("_", " ").title() for t in _as_list(p.get("employmentType"))),
                source_says_sponsorship=flagged,
            )
        next_url = (data.get("links") or {}).get("next") if isinstance(data, dict) else None
        if not next_url or not postings:
            break
        url = next_url


# --------------------------------------------------------------------------- Arbeitnow (Europe)
def arbeitnow(days: int) -> Iterator[Job]:
    """Arbeitnow job board API (mostly Germany/EU); supports a visa sponsorship filter."""
    cutoff = _cutoff(days)
    for page in range(1, 11):
        data = http.get_json("https://www.arbeitnow.com/api/job-board-api",
                             params={"page": page, "visa_sponsorship": "true"})
        results = data.get("data", [])
        for r in results:
            posted = parse_date(r.get("created_at"))
            if not posted or posted < cutoff:
                continue
            location = r.get("location", "")
            yield Job(
                source="Arbeitnow", source_id=r.get("slug", ""),
                title=r.get("title", ""), company=r.get("company_name", ""),
                location=location, country=_guess_country(location, default="DE"),
                url=r.get("url", ""), posted_at=posted,
                description=strip_html(r.get("description")),
                contract=", ".join(r.get("job_types") or []),
                source_says_sponsorship=bool(r.get("visa_sponsorship", True)),
            )
        if not results or not (data.get("links") or {}).get("next"):
            break


# --------------------------------------------------------------------------- Platsbanken / JobTech (Sweden)
JOBTECH_QUERIES = ["visa sponsorship", "work permit", "relocation", "english speaking", "blue card"]


def jobtech_sweden(days: int) -> Iterator[Job]:
    """Arbetsförmedlingen's open JobSearch API: every advert on Platsbanken, the Swedish public employment
    service, including universities, regions and municipalities. Adverts carry the employer's own contacts."""
    cutoff = _cutoff(days)
    published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
    for query in JOBTECH_QUERIES:
        for offset in range(0, 500, 100):
            data = http.get_json("https://jobsearch.api.jobtechdev.se/search",
                                 params={"q": query, "published-after": published_after,
                                         "limit": 100, "offset": offset})
            hits = data.get("hits", [])
            for h in hits:
                posted = parse_date(h.get("publication_date"))
                if not posted or posted < cutoff:
                    continue
                employer = h.get("employer") or {}
                addr = h.get("workplace_address") or {}
                apply = h.get("application_details") or {}
                contacts = [{"name": c.get("name") or "", "role": c.get("description") or "",
                             "email": (c.get("email") or "").strip(), "phone": c.get("telephone") or ""}
                            for c in h.get("application_contacts") or []]
                if apply.get("email"):
                    contacts.append({"email": apply["email"].strip(), "role": "Applications"})
                yield Job(
                    source="Platsbanken", channel="official", source_id=str(h.get("id", "")),
                    title=h.get("headline", ""), company=employer.get("name") or employer.get("workplace") or "",
                    location=", ".join(filter(None, [addr.get("municipality"), addr.get("region")])) or "Sweden",
                    country="SE", url=h.get("webpage_url") or apply.get("url") or "", posted_at=posted,
                    description=strip_html((h.get("description") or {}).get("text")),
                    salary=h.get("salary_description") or "",
                    contract=(h.get("employment_type") or {}).get("label") or "",
                    advert_contacts=[c for c in contacts if c.get("email") or c.get("phone")],
                )
            if len(hits) < 100:
                break


# --------------------------------------------------------------------------- Generic RSS
def rss_feeds(days: int, feeds: list[dict]) -> Iterator[Job]:
    """Any RSS/Atom feed listed in config/sources.json (e.g. jobs.ac.uk, council job boards)."""
    if not feeds:
        raise SkipSource("no RSS feeds configured")
    cutoff = _cutoff(days)
    for feed in feeds:
        try:
            root = ET.fromstring(http.get(feed["url"]))
        except Exception as err:  # noqa: BLE001 - one broken feed must not hide the others
            log.warning("RSS feed %s failed: %s", feed.get("name", feed["url"]), err)
            continue
        for item in (el for el in root.iter() if _local(el.tag) in ("item", "entry")):
            f = {}
            for c in item:
                tag = _local(c.tag)
                f.setdefault(tag, (c.text or "").strip() or c.attrib.get("href", ""))
            posted = parse_date(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))
            if not posted or posted < cutoff:
                continue
            title = f.get("title", "")
            company = f.get("author") or f.get("creator") or feed.get("employer", "")
            # jobs.ac.uk style titles: "Role - Employer"
            if not company and " - " in title:
                title, company = title.rsplit(" - ", 1)
            description = strip_html(f.get("description") or f.get("summary") or f.get("content"))
            yield Job(
                source=feed.get("name", "RSS"), channel=feed.get("channel", "official"), source_id=f.get("guid") or f.get("id") or f.get("link", ""),
                title=title, company=company, location=feed.get("location", ""),
                country=_guess_country(f"{title} {description[:300]}", default=feed.get("country", "GB")),
                url=f.get("link", ""), posted_at=posted, description=description,
            )


# --------------------------------------------------------------------------- helpers
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _as_list(value) -> list[str]:
    if not value:
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _schema_salary(base) -> str:
    """schema.org MonetaryAmount: {"currency": "GBP", "value": {"minValue": .., "maxValue": .., "unitText": "YEAR"}}."""
    if not isinstance(base, dict):
        return str(base or "")
    value = base.get("value")
    if not isinstance(value, dict):
        return str(value or "")
    if value.get("value") and isinstance(value["value"], str) and not value.get("minValue"):
        return value["value"].split("\n")[0].strip()
    amount = _salary(value.get("minValue"), value.get("maxValue")) or _salary(value.get("value"), None)
    if not amount:
        return ""
    symbol = {"GBP": "£", "EUR": "€", "USD": "$"}.get(base.get("currency", ""), "")
    unit = {"YEAR": " a year", "MONTH": " a month", "HOUR": " an hour", "DAY": " a day"}.get(value.get("unitText", ""), "")
    return f"{symbol}{amount}{unit}"


def _salary(lo, hi) -> str:
    def fmt(v):
        return f"{int(float(v)):,}"
    try:
        if lo and hi and float(lo) != float(hi):
            return f"{fmt(lo)} – {fmt(hi)}"
        if lo or hi:
            return fmt(lo or hi)
    except (TypeError, ValueError):
        pass
    return ""


_COUNTRY_WORDS = {
    "germany": "DE", "deutschland": "DE", "berlin": "DE", "munich": "DE", "münchen": "DE",
    "hamburg": "DE", "frankfurt": "DE", "cologne": "DE", "köln": "DE", "stuttgart": "DE",
    "netherlands": "NL", "amsterdam": "NL", "rotterdam": "NL", "utrecht": "NL", "eindhoven": "NL",
    "france": "FR", "paris": "FR", "lyon": "FR", "spain": "ES", "madrid": "ES", "barcelona": "ES",
    "ireland": "IE", "dublin": "IE", "austria": "AT", "vienna": "AT", "wien": "AT",
    "switzerland": "CH", "zurich": "CH", "zürich": "CH", "geneva": "CH", "belgium": "BE",
    "brussels": "BE", "italy": "IT", "milan": "IT", "rome": "IT", "poland": "PL", "warsaw": "PL",
    "sweden": "SE", "stockholm": "SE", "denmark": "DK", "copenhagen": "DK", "portugal": "PT",
    "lisbon": "PT", "finland": "FI", "helsinki": "FI", "norway": "NO", "oslo": "NO",
    "luxembourg": "LU", "czech": "CZ", "prague": "CZ", "estonia": "EE", "tallinn": "EE",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB", "london": "GB", "manchester": "GB", "birmingham": "GB",
    "leeds": "GB", "glasgow": "GB", "edinburgh": "GB", "bristol": "GB", "cambridge": "GB", "oxford": "GB",
    "liverpool": "GB", "sheffield": "GB", "newcastle": "GB", "nottingham": "GB", "cardiff": "GB",
    "belfast": "GB", "leicester": "GB", "southampton": "GB", "reading": "GB", "brighton": "GB",
    "york": "GB", "coventry": "GB", "milton keynes": "GB", "aberdeen": "GB", "dundee": "GB",
    "exeter": "GB", "bath": "GB", "norwich": "GB", "plymouth": "GB", "swansea": "GB", "hull": "GB",
    "düsseldorf": "DE", "dusseldorf": "DE", "leipzig": "DE", "dresden": "DE", "hannover": "DE",
    "nuremberg": "DE", "nürnberg": "DE", "heidelberg": "DE", "karlsruhe": "DE", "bonn": "DE",
    "the hague": "NL", "den haag": "NL", "delft": "NL", "leiden": "NL", "groningen": "NL",
    "antwerp": "BE", "ghent": "BE", "leuven": "BE", "toulouse": "FR", "marseille": "FR", "grenoble": "FR",
    "valencia": "ES", "seville": "ES", "malaga": "ES", "turin": "IT", "bologna": "IT", "florence": "IT",
    "krakow": "PL", "kraków": "PL", "wroclaw": "PL", "wrocław": "PL", "gdansk": "PL", "porto": "PT",
    "gothenburg": "SE", "malmö": "SE", "malmo": "SE", "aarhus": "DK", "bucharest": "RO", "budapest": "HU",
    "athens": "GR", "vilnius": "LT", "riga": "LV", "cork": "IE", "galway": "IE", "limerick": "IE",
    "basel": "CH", "lausanne": "CH", "bern": "CH", "graz": "AT", "salzburg": "AT",
    # Sweden, Finland, Poland, Spain, Netherlands, Luxembourg (target countries): more cities.
    "uppsala": "SE", "lund": "SE", "linköping": "SE", "linkoping": "SE", "västerås": "SE", "örebro": "SE",
    "umeå": "SE", "umea": "SE", "luleå": "SE", "jönköping": "SE", "solna": "SE", "kista": "SE", "sverige": "SE",
    "espoo": "FI", "tampere": "FI", "oulu": "FI", "turku": "FI", "vantaa": "FI", "jyväskylä": "FI", "suomi": "FI",
    "poznan": "PL", "poznań": "PL", "łódź": "PL", "lodz": "PL", "katowice": "PL", "gdynia": "PL", "lublin": "PL",
    "szczecin": "PL", "bydgoszcz": "PL", "polska": "PL",
    "bilbao": "ES", "zaragoza": "ES", "palma": "ES", "alicante": "ES", "san sebastián": "ES", "españa": "ES",
    "amstelveen": "NL", "haarlem": "NL", "hoofddorp": "NL", "nijmegen": "NL", "maastricht": "NL", "tilburg": "NL",
    "breda": "NL", "arnhem": "NL", "almere": "NL", "enschede": "NL", "schiphol": "NL", "veldhoven": "NL",
    "nederland": "NL", "esch-sur-alzette": "LU", "belval": "LU", "kirchberg": "LU",
    "inverness": "GB", "stirling": "GB", "st andrews": "GB", "paisley": "GB", "livingston": "GB",
    # United Arab Emirates
    "dubai": "AE", "abu dhabi": "AE", "sharjah": "AE", "ajman": "AE", "uae": "AE", "united arab emirates": "AE",
    "difc": "AE", "jebel ali": "AE",
    # United States
    "san francisco": "US", "seattle": "US", "austin": "US", "boston": "US", "chicago": "US", "los angeles": "US",
    "san jose": "US", "palo alto": "US", "mountain view": "US", "menlo park": "US", "sunnyvale": "US",
    "redmond": "US", "denver": "US", "atlanta": "US", "dallas": "US", "houston": "US", "washington, dc": "US",
    "washington dc": "US", "philadelphia": "US", "pittsburgh": "US", "miami": "US", "phoenix": "US",
    "san diego": "US", "salt lake city": "US", "minneapolis": "US", "detroit": "US", "nashville": "US",
    "raleigh": "US", "charlotte": "US", "portland, or": "US", "baltimore": "US", "columbus, oh": "US",
    "brooklyn": "US", "jersey city": "US", "san mateo": "US", "south san francisco": "US", "irvine, ca": "US",
    "california": "US", "texas": "US", "massachusetts": "US", "new jersey": "US", "virginia": "US",
    "illinois": "US", "colorado": "US", "north carolina": "US", "pennsylvania": "US",
    "michigan": "US", "minnesota": "US", "florida": "US", "ohio": "US", "arizona": "US", "maryland": "US",
    "us remote": "US", "remote - us": "US", "remote, us": "US", "remote (us)": "US",
    # Same-named places outside Europe; longer names are tried first, so these win.
    "new york": "US", "cambridge, ma": "US", "cambridge, massachusetts": "US", "birmingham, al": "US",
    "london, on": "CA", "london, ontario": "CA", "new england": "US", "united states": "US", "usa": "US",
    "perth, wa": "AU", "perth, western australia": "AU", "hamilton, on": "CA", "hamilton, ontario": "CA",
    "hamilton, new zealand": "NZ", "canada": "CA", "toronto": "CA", "india": "IN", "bengaluru": "IN",
    "bangalore": "IN", "singapore": "SG", "australia": "AU", "sydney": "AU", "melbourne": "AU", "japan": "JP",
    "tokyo": "JP", "brazil": "BR", "são paulo": "BR", "mexico": "MX", "china": "CN", "hong kong": "HK",
}


_COUNTRY_RE = re.compile(
    r"\b(" + "|".join(map(re.escape, sorted(_COUNTRY_WORDS, key=len, reverse=True))) + r")\b", re.I)


def _guess_country(text: str, default: str) -> str:
    match = _COUNTRY_RE.search(text)
    return _COUNTRY_WORDS[match.group(1).lower()] if match else default


SOURCES: dict[str, Callable[..., Iterator[Job]]] = {
    "adzuna": adzuna,
    "reed": reed,
    "nhs_jobs": nhs_jobs,
    "teaching_vacancies": teaching_vacancies,
    "arbeitnow": arbeitnow,
    "jobtech_sweden": jobtech_sweden,
}
