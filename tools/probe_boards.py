"""Show the response format of Pinpoint and Teamtailor job feeds (temporary probe)."""

import re
import urllib.error
import urllib.request

UA = "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)"


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(400_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80]


for url in ("https://tabby.pinpointhq.com/postings.json", "https://aiven.pinpointhq.com/postings.json",
            "https://travelperk.pinpointhq.com/postings.json",
            "https://kryhealthcare.teamtailor.com/jobs.rss", "https://einride.teamtailor.com/jobs.rss",
            "https://voi.teamtailor.com/jobs.rss", "https://careers.voi.com/jobs.rss", "https://careers.einride.tech/jobs.rss",
            "https://glovo.teamtailor.com/jobs.rss", "https://skyscanner.teamtailor.com/jobs.rss",
            "https://checkout.teamtailor.com/jobs.rss", "https://factorial.teamtailor.com/jobs.rss"):
    status, body = get(url)
    i = max(body.find("<item"), 0)
    print(f"=== {url} [{status}] len={len(body)} items={body.count('<item')}\n{re.sub(r'\s+', ' ', body[i:i + 2200] if '<item' in body else body[:2200])}\n", flush=True)
