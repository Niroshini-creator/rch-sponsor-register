"""Irish public-sector job feeds: HSE careerhub, publicjobs.ie search, CoreHR university feeds (temporary)."""

import re
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; rch-sponsor-register/1.0; +https://github.com/niroshini-creator/rch-sponsor-register)"


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:100], url


def show(url: str, n: int = 1500, find: str = "") -> None:
    status, body, final = get(url)
    i = body.find(find) if find else -1
    sample = body[max(0, i - 300):i + n] if i >= 0 else body[:n]
    print(f"=== {url} [{status}] final={final} len={len(body)} items={body.count('<item')}")
    print("  " + re.sub(r"\s+", " ", sample)[:n] + "\n", flush=True)


show("https://careerhub.hse.ie/feed/", 1500, "<item")
show("https://careerhub.hse.ie/?s=&post_type=job_listing", 1200, "job_listing")
show("https://careerhub.hse.ie/jobs/", 1500, "job")
show("https://careerhub.hse.ie/wp-json/wp/v2/job_listing?per_page=2", 1500)
show("https://careerhub.hse.ie/job-feed/", 1200)
show("https://careerhub.hse.ie/?feed=job_feed", 1500, "<item")
show("https://www.publicjobs.ie/en/search-jobs", 1500, "job")
show("https://www.publicjobs.ie/en/jobs", 1500, "job")
show("https://www.publicjobs.ie/robots.txt", 800)
show("https://careerhub.hse.ie/robots.txt", 800)
show("https://www.universityofgalway.ie/about-us/jobs/", 1500, "rss")
show("https://www.universityofgalway.ie/about-us/jobs/rss/", 1500, "<item")
show("https://my.corehr.com/robots.txt", 600)
show("https://www.jobs.ac.uk/search/?location=Ireland&sortOrder=1", 1200, "j-search-result__result")
