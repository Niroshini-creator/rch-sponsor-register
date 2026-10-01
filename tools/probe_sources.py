"""Print what each candidate job-feed URL returns (status, type, size, item counts, a sample).

Run from GitHub Actions (Probe job sources) when a source returns nothing, to see the real response.
"""

import re
import sys
import urllib.error
import urllib.request

URLS = [
    "https://www.jobs.nhs.uk/api/v1/search_xml?keyword=sponsorship&page=1&sort=publicationDateDesc",
    "https://www.jobs.nhs.uk/api/v1/search_xml?keyword=sponsorship",
    "https://www.jobs.nhs.uk/api/v1/search?keyword=sponsorship",
    "https://www.jobs.nhs.uk/candidate/search/results?keyword=sponsorship&sort=publicationDateDesc",
    "https://www.jobs.nhs.uk/candidate/search/results?keyword=sponsorship&sort=publicationDateDesc&format=rss",
    "https://www.jobs.ac.uk/jobs/?format=rss&keywords=sponsorship",
    "https://www.jobs.ac.uk/search/?keywords=sponsorship&format=rss",
    "https://www.jobs.ac.uk/search/?keywords=visa+sponsorship",
    "https://www.jobs.ac.uk/feeds/",
    "https://www.jobs.ac.uk/jobs/computer-sciences/?format=rss",
    "https://euraxess.ec.europa.eu/jobs/feed?keywords=visa",
    "https://euraxess.ec.europa.eu/jobs/search?keywords=visa",
    "https://euraxess.ec.europa.eu/jobs/search/rss?keywords=visa",
    "https://apply.jobs.scot.nhs.uk/Home/Job",
    "https://www.myjobscotland.gov.uk/search?keywords=sponsorship",
    "https://www.timeshighereducation.com/unijobs/listings/?keywords=visa+sponsorship",
    "https://academicpositions.com/find-jobs?search=visa",
    "https://www.academictransfer.com/en/jobs/?q=english",
    "https://www.higheredjobs.com/rss/articleFeed.cfm",
]
UAS = {"bot": "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)",
       "browser": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"}


def probe(url: str, ua: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(400_000)
            status, ctype, final = r.status, r.headers.get("Content-Type", ""), r.geturl()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}: {e}"
    text = body.decode("utf-8", "replace")
    counts = {t: len(re.findall(rf"<{t}[\s>]", text)) for t in ("item", "entry", "vacancy", "job", "article")}
    sample = re.sub(r"\s+", " ", text[:700])
    return f"{status} {ctype} {len(body)}B final={final} tags={counts}\n      {sample}"


for url in URLS:
    for name, ua in UAS.items():
        print(f"[{name}] {url}\n   -> {probe(url, ua)}", flush=True)
sys.exit(0)
