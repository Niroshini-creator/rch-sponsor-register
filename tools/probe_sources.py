"""Print what candidate job sources return: robots.txt rules and the page structure around listings.

Run from GitHub Actions (Probe job sources) when a source returns nothing, to see the real response.
"""

import re
import urllib.error
import urllib.request

UA = "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)"


def get(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return f"{r.status} {r.headers.get('Content-Type', '')}", r.read(600_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", ""
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}", ""


def show(title: str, text: str, n: int = 1500) -> None:
    print(f"--- {title}\n{re.sub(r'[ \t]+', ' ', text[:n])}\n", flush=True)


for host in ("www.jobs.nhs.uk", "beta.jobs.nhs.uk", "www.jobs.ac.uk", "euraxess.ec.europa.eu",
             "www.timeshighereducation.com", "www.academictransfer.com", "apply.jobs.scot.nhs.uk", "www.higheredjobs.com"):
    status, body = get(f"https://{host}/robots.txt")
    show(f"robots {host} [{status}]", body, 1200)

# NHS Jobs: one advert page, to find the full text and the contact block.
status, xml = get("https://www.jobs.nhs.uk/api/v1/search_xml?keyword=sponsorship&page=1&sort=publicationDateDesc")
show(f"nhs xml [{status}] vacancies={xml.count('<vacancyDetails>')}", xml, 900)
m = re.search(r"<url>([^<]+)</url>", xml)
if m:
    for url in (m.group(1), m.group(1).replace("beta.jobs.nhs.uk", "www.jobs.nhs.uk")):
        status, page = get(url)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", page)))
        print(f"--- nhs advert {url} [{status}] {len(page)}B")
        for word in ("sponsor", "Skilled worker", "Contact details", "Job title", "Email address", "Telephone"):
            i = text.find(word)
            print(f"   [{word}] {text[max(0, i - 200):i + 400] if i >= 0 else '-'}")
        i = page.find("Email address")
        show("nhs advert html near Email address", page[max(0, i - 1500):i + 800] if i >= 0 else "", 2300)

# jobs.ac.uk search results
status, page = get("https://www.jobs.ac.uk/search/?keywords=visa+sponsorship")
links = re.findall(r'href="(/job/[^"]+)"', page)
print(f"--- jobs.ac.uk search [{status}] job links={len(links)} {links[:3]}")
i = page.find(links[0]) if links else -1
show("jobs.ac.uk html around first result", page[max(0, i - 1200):i + 1800] if i >= 0 else "", 3000)
if links:
    status, adv = get("https://www.jobs.ac.uk" + links[0])
    i = adv.find("ld+json")
    show(f"jobs.ac.uk advert [{status}] ld+json", adv[i:i + 2500] if i >= 0 else adv[:800], 2500)

# EURAXESS search results
status, page = get("https://euraxess.ec.europa.eu/jobs/search?keywords=visa")
i = page.find("<article")
show(f"euraxess search [{status}] articles={page.count('<article')}", page[i:i + 3500] if i >= 0 else "", 3500)

# Times Higher Education unijobs
status, page = get("https://www.timeshighereducation.com/unijobs/listings/?keywords=visa+sponsorship")
links = re.findall(r'href="(/unijobs/listing/[^"]+)"', page)
print(f"--- THE [{status}] links={len(links)} {links[:3]}")
i = page.find(links[0]) if links else -1
show("THE html around first result", page[max(0, i - 1500):i + 1500] if i >= 0 else "", 3000)
for feed in ("https://www.timeshighereducation.com/unijobs/listings/rss/?keywords=visa",
             "https://www.timeshighereducation.com/unijobs/jobsrss/?keywords=visa"):
    status, body = get(feed)
    show(f"THE feed {feed} [{status}] items={body.count('<item')}", body, 600)

# AcademicTransfer (Dutch universities)
status, page = get("https://www.academictransfer.com/en/jobs/?q=english")
i = page.find("<article")
show(f"academictransfer [{status}]", page[i:i + 2500] if i >= 0 else "", 2500)
for api in ("https://api.academictransfer.com/vacancies/?q=english", "https://www.academictransfer.com/api/vacancies/?q=english"):
    status, body = get(api)
    show(f"academictransfer api {api} [{status}]", body, 600)

# NHS Scotland (Jobtrain)
status, page = get("https://apply.jobs.scot.nhs.uk/Home/Job")
links = re.findall(r'href="([^"]*(?:JobDetail|Job/[^"]*Detail|jobId)[^"]*)"', page)
print(f"--- nhs scotland [{status}] detail links={len(links)} {links[:3]}")
for kw in ("rss", "api/", "JobSearch", "Vacancy"):
    i = page.find(kw)
    print(f"   [{kw}] {re.sub(r'\s+', ' ', page[max(0, i - 200):i + 300]) if i >= 0 else '-'}")

# HigherEdJobs job feeds
for feed in ("https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=68",
             "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=10"):
    status, body = get(feed)
    show(f"higheredjobs {feed} [{status}] items={body.count('<item')}", body[body.find('<item'):] if '<item' in body else body, 900)
