"""Print what candidate job sources return: feed items, paging behaviour and listing structure.

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
            return f"{r.status}", r.read(800_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", ""
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}", ""


def show(title: str, text: str, n: int = 1500) -> None:
    print(f"--- {title}\n{re.sub(r'\s+', ' ', text[:n])}\n", flush=True)


# Times Higher Education RSS: item format and country filters
for q in ("keywords=visa", "keywords=visa+sponsorship&countrycode=US", "keywords=visa&countrycode=AE",
          "keywords=sponsorship&countrycode=NL", "keywords=visa&countrycode=ALL", "keywords=sponsorship"):
    status, body = get(f"https://www.timeshighereducation.com/unijobs/jobsrss/?{q}")
    total = re.search(r"totalResults>(\d+)", body)
    i = body.find("<item")
    show(f"THE {q} [{status}] items={body.count('<item')} total={total and total.group(1)}", body[i:i + 1800] if i >= 0 else body, 1800)

# jobs.ac.uk: paging and sorting parameters
base = "https://www.jobs.ac.uk/search/?keywords=visa+sponsorship"
for extra in ("", "&pageSize=100", "&startIndex=26", "&sortOrder=1", "&sortOrder=0", "&activeFacet=sortOrder&sortOrder=1"):
    status, page = get(base + extra)
    links = re.findall(r'href="(/job/[^"]+)"', page)
    dates = re.findall(r"Date Placed: </strong>([^<]+)<", page)
    total = re.search(r"([\d,]+)\s+(?:jobs|results) found", page)
    print(f"--- jobs.ac.uk{extra} [{status}] links={len(links)} first={links[:2]} dates={[d.strip() for d in dates[:6]]} total={total and total.group(1)}")
status, adv = get("https://www.jobs.ac.uk" + links[0]) if links else ("", "")
m = re.search(r'ld\+json">(\{.*?\})</script>', adv, re.S)
if m:
    js = m.group(1)
    for key in ("datePosted", "hiringOrganization", "jobLocation", "baseSalary", "employmentType", "validThrough"):
        i = js.find(f'"{key}"')
        print(f"   [{key}] {js[i:i + 300] if i >= 0 else '-'}")
for word in ("enquiries", "contact", "@"):
    i = adv.find(word)
    print(f"   advert [{word}] {re.sub(r'<[^>]+>|\s+', ' ', adv[max(0, i - 200):i + 300]) if i >= 0 else '-'}")

# EURAXESS: the job result blocks
status, page = get("https://euraxess.ec.europa.eu/jobs/search?keywords=visa")
links = re.findall(r'href="(/jobs/\d+)"', page)
print(f"--- euraxess [{status}] job links={len(links)} {links[:3]}")
i = page.find(links[0]) if links else -1
show("euraxess around first job", page[max(0, i - 1500):i + 2500] if i >= 0 else "", 4000)
