"""Irish public-sector and EU-institution vacancies.

* publicjobs.ie: the Irish public service's recruiter (civil service, local authorities, state boards, and other bodies
  that recruit through it as "External Recruiter"). Its job board (publicjobs.tal.net) lists 50 vacancies a page.
* localgovernmentjobs.ie: the newest council vacancies, with salary scales. Older ones are also on publicjobs.ie.
* educationposts.ie: school, college and further-education posts, by level. The listing gives no posting date.
* eu-careers.europa.eu: vacancies at EU institutions and agencies. Each vacancy page links to the agency's own
  application page.

HSE, An Post and the universities' CoreHR portals are not read: HSE's search only serves its first page to a script
(mostly internal competitions), An Post sits behind a bot check, and CoreHR needs a form session. The site links to
them instead, and Irish university posts also reach the feed through jobs.ac.uk.
"""

from __future__ import annotations

import html
import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterator

from . import http
from .models import UNDATED, Job
from .text import parse_date, strip_html

log = logging.getLogger("jobfeed")

PUBLICJOBS_BOARD = ("https://publicjobs.tal.net/vx/lang-en-GB/mobile-0/appcentre-ext/brand-4/xf-423dd989250d/"
                    "candidate/jobboard/vacancy/3/adv/")
PUBLICJOBS_MAX_PAGES = 12
EDUCATION_LEVELS = ("second_level", "primary_level", "third_level", "other_posts")
EU_MAX_PAGES = 10
EU_PAUSE = 0.3

# EU Careers gives "City, Country"; the country is read from the last part.
EU_COUNTRIES = {
    "austria": "AT", "belgium": "BE", "bulgaria": "BG", "croatia": "HR", "cyprus": "CY", "czechia": "CZ",
    "czech republic": "CZ", "denmark": "DK", "estonia": "EE", "finland": "FI", "france": "FR", "germany": "DE",
    "greece": "GR", "hungary": "HU", "ireland": "IE", "italy": "IT", "latvia": "LV", "lithuania": "LT",
    "luxembourg": "LU", "malta": "MT", "netherlands": "NL", "poland": "PL", "portugal": "PT", "romania": "RO",
    "slovakia": "SK", "slovenia": "SI", "spain": "ES", "sweden": "SE", "norway": "NO", "iceland": "IS",
    "switzerland": "CH", "united kingdom": "GB",
}


def _text(fragment: str) -> str:
    return strip_html(fragment or "")


def _field(block: str, label: str) -> str:
    """The value after a "<label>:" caption in a listing tile or card."""
    m = re.search(rf"{re.escape(label)}:\s*</span>\s*(.*?)</(?:div|p|li)>", block, re.S | re.I)
    return _text(m.group(1)) if m else ""


def _first_date(value: str) -> datetime | None:
    """"17/12/2026, 15:00" or "20 Nov 2026, 11:59 PM" -> the date."""
    return parse_date(value.split(",")[0].strip()) if value else None


def _iso(value: str) -> str:
    when = _first_date(value)
    return when.date().isoformat() if when else ""


# --------------------------------------------------------------------------- publicjobs.ie
def parse_publicjobs(page: str) -> tuple[list[Job], int]:
    """Vacancy tiles from one publicjobs.ie job-board page, and the total number of results."""
    total = re.search(r"(\d+)\s+results match", page)
    jobs = []
    for tile in page.split('class="col-md-6 opp-container"')[1:]:
        link = re.search(r'<a class="subject" href="([^"]+)"', tile)
        title = re.search(r'data-title="([^"]*)"', tile)
        oppid = re.search(r'data-oppid="(\d+)"', tile)
        if not link or not title:
            continue
        org = _field(tile, "Department/Organisation")
        where = _field(tile, "Location")
        kind = _field(tile, "Vacancy type")
        closes = _field(tile, "Closing Date")
        name = html.unescape(title.group(1)).strip()
        jobs.append(Job(
            source="publicjobs.ie", channel="official", source_id=oppid.group(1) if oppid else link.group(1),
            title=name, company=org or "publicjobs.ie", location=where, country="IE",
            url=html.unescape(link.group(1)), posted_at=_first_date(_field(tile, "Advertising Date")) or UNDATED,
            closes_at=_iso(closes),
            description=" ".join(filter(None, [
                f"{name}.", f"Organisation: {org}." if org else "", f"Vacancy type: {kind}." if kind else "",
                f"Location: {where}." if where else "", f"Closing date: {closes}." if closes else "",
                "Irish public service post: see the candidate information booklet on publicjobs.ie for eligibility."])),
        ))
    return jobs, int(total.group(1)) if total else len(jobs)


def publicjobs_ie(days: int) -> Iterator[Job]:
    seen = 0
    for n in range(PUBLICJOBS_MAX_PAGES):
        page = http.get_text(PUBLICJOBS_BOARD + (f"?start={n * 50}" if n else ""), retries=2)
        jobs, total = parse_publicjobs(page)
        yield from jobs
        seen += len(jobs)
        if not jobs or seen >= total:
            break


# --------------------------------------------------------------------------- localgovernmentjobs.ie
def parse_local_government(page: str) -> list[Job]:
    jobs = []
    for card in page.split('<div class="job-cards-item">')[1:]:
        link = re.search(r'<a href="(/jobs/[^"]+)"', card)
        title = re.search(r"<h2>(.*?)</h2>", card, re.S)
        council = re.search(r"</h2>\s*<p>(.*?)</p>", card, re.S)
        if not link or not title:
            continue
        name, org = _text(title.group(1)), _text(council.group(1)) if council else ""
        salary, where = _field(card, "Salary Scale"), _field(card, "Location")
        closes, grade = _field(card, "Closing Date"), _field(card, "Grade")
        ref = re.search(r'<p class="reference">(.*?)</p>', card, re.S)
        jobs.append(Job(
            source="Local Government Jobs", channel="official", source_id=link.group(1),
            title=name, company=org, location=where, country="IE",
            url="https://www.localgovernmentjobs.ie" + html.unescape(link.group(1)),
            posted_at=_first_date(_field(card, "Advertised Date")) or UNDATED, salary=salary, closes_at=_iso(closes),
            description=" ".join(filter(None, [
                f"{name}, {org}." if org else f"{name}.", f"Grade: {grade}." if grade else "",
                f"Salary: {salary}." if salary else "", f"Location: {where}." if where else "",
                f"Closing date: {closes}." if closes else "", f"Reference: {_text(ref.group(1))}." if ref else "",
                "Irish local authority post: see the advert for eligibility."])),
        ))
    return jobs


def local_government_ie(days: int) -> Iterator[Job]:
    yield from parse_local_government(http.get_text("https://www.localgovernmentjobs.ie/Search/Vacancies", retries=2))


# --------------------------------------------------------------------------- educationposts.ie
def parse_education_posts(page: str, level: str) -> list[Job]:
    jobs = []
    for row in re.findall(r'<tr data-href="(/post/view/\d+)"[^>]*>(.*?)</tr>', page, re.S):
        path, cells = row
        tds = [_text(re.sub(r"<br\s*/?>", ", ", c)) for c in re.findall(r"<td[^>]*>(.*?)</td>", cells, re.S)]
        if len(tds) < 7:
            continue
        _, school, kind, subjects, status, county, deadline = tds[:7]
        if re.search(r"\bon behalf of\b", school, re.I):
            continue  # recruiters for schools abroad
        title = f"{kind} ({subjects.rstrip(', ')})" if subjects.strip(", ") else kind
        deadline = deadline.split(" ")[0]
        jobs.append(Job(
            source="EducationPosts.ie", channel="official", source_id=path.rsplit("/", 1)[-1], title=title,
            company=school, location=county, country="IE", url="https://www.educationposts.ie" + path,
            posted_at=UNDATED, contract=status, closes_at=_iso(deadline),
            description=" ".join(filter(None, [
                f"{kind} at {school}, {county}.", f"Subjects: {subjects.rstrip(', ')}." if subjects.strip(', ') else "",
                f"Status of post: {status}." if status else "", f"Application deadline: {deadline}." if deadline else "",
                f"Level: {level.replace('_', ' ')}."])),
        ))
    return jobs


def education_posts_ie(days: int) -> Iterator[Job]:
    for level in EDUCATION_LEVELS:
        try:
            page = http.get_text(f"https://www.educationposts.ie/posts/{level}", retries=2)
        except Exception as err:  # noqa: BLE001 - keep the other levels
            log.warning("EducationPosts %s unavailable: %s", level, err)
            continue
        yield from parse_education_posts(page, level)


# --------------------------------------------------------------------------- EU Careers
def parse_eu_list(page: str) -> list[dict]:
    items = []
    for block in page.split('<div class="eujmp-vacancy-result">')[1:]:
        link = re.search(r'href="(/jobs/[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        top = [_text(x) for x in re.findall(r"<li>(.*?)</li>", block.split("__top-meta", 1)[-1].split("</ul>", 1)[0], re.S)]
        bottom = [_text(x) for x in re.findall(r"<li>(.*?)</li>", block.split("__bottom-meta", 1)[-1].split("</ul>", 1)[0], re.S)]
        deadline = re.search(r'<time datetime="([^"]+)"', block)
        items.append({"path": link.group(1), "title": _text(link.group(2)), "institution": top[0] if top else "",
                      "deadline": deadline.group(1)[:10] if deadline else "", "contract": bottom[0] if bottom else "",
                      "grade": bottom[1] if len(bottom) > 1 else "", "location": bottom[-1] if len(bottom) > 2 else ""})
    return items


def parse_eu_detail(page: str) -> dict:
    """Fields from an EU Careers vacancy page: the agency's application link and the vacancy notice's date."""
    out = {}
    for label in ("Reference", "Institution", "Location", "Domain", "Contract type", "Grade"):
        m = re.search(rf"<strong>{label}:</strong>\s*(.*?)</p>", page, re.S)
        if m:
            out[label.lower()] = _text(m.group(1))
    apply = re.search(r'<a href="([^"]+)"[^>]*>\s*Vacancy link\s*</a>', page)
    if apply:
        out["apply"] = html.unescape(apply.group(1))
    notice = re.search(r'class="ecl-file__primary-meta-item">([^<]+)<', page)
    if notice:
        out["published"] = notice.group(1).strip()
    return out


def eu_country(location: str) -> str:
    last = location.rsplit(",", 1)[-1].strip().lower()
    return EU_COUNTRIES.get(last, "")


def eu_careers(days: int) -> Iterator[Job]:
    items: list[dict] = []
    for n in range(EU_MAX_PAGES):
        found = parse_eu_list(http.get_text("https://eu-careers.europa.eu/jobs_en" + (f"?page={n}" if n else ""), retries=2))
        items += found
        if not found:
            break
    for i, it in enumerate(items):
        if i:
            time.sleep(EU_PAUSE)
        url = "https://eu-careers.europa.eu" + it["path"]
        try:
            info = parse_eu_detail(http.get_text(url, retries=1))
        except Exception as err:  # noqa: BLE001 - the listing alone is enough to show the vacancy
            log.debug("EU Careers vacancy %s unavailable: %s", url, err)
            info = {}
        where = info.get("location") or it["location"]
        country = eu_country(where)
        if not country:
            continue
        published = parse_date(info.get("published")) if info.get("published") else None
        yield Job(
            source="EU Careers", channel="official", source_id=info.get("reference") or it["path"], title=it["title"],
            company=info.get("institution") or it["institution"], location=where, country=country, url=url,
            posted_at=published or UNDATED, contract=info.get("contract type") or it["contract"],
            closes_at=it["deadline"],
            description=" ".join(filter(None, [
                f"{it['title']} at {info.get('institution') or it['institution']}.",
                f"Contract type: {info.get('contract type') or it['contract']}.", f"Grade: {info.get('grade') or it['grade']}.",
                f"Domain: {info['domain']}." if info.get("domain") else "",
                f"Application deadline: {it['deadline']}." if it["deadline"] else "",
                f"Apply via: {info['apply']}" if info.get("apply") else "",
                "EU institution post: staff are normally citizens of an EU member state; check the vacancy notice."])),
        )
