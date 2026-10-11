"""How many jobs Adzuna and Reed return per curated graduate employer (temporary)."""

import base64
import collections
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
from jobfeed.text import normalise_company  # noqa: E402

AZ = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"]}
REED = os.environ.get("REED_API_KEY", "")


def get(url, auth=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth}:".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:80]}


def summary(name, companies):
    key = normalise_company(name)
    same = sum(c for n, c in companies.items() if normalise_company(n) == key or normalise_company(n).startswith(key + " "))
    return same, companies.most_common(4)


emps = [e for e in json.load(open("config/early_career_employers.json"))["employers"] if e.get("country", "GB") == "GB"]
for e in emps:
    name = e["name"]
    out = [name]
    for label, extra in (("company", {"company": name}), ("what_and", {"what_and": name})):
        q = urllib.parse.urlencode({**AZ, "results_per_page": 50, "max_days_old": 7, "sort_by": "date", **extra})
        status, data = get(f"https://api.adzuna.com/v1/api/jobs/gb/search/1?{q}")
        comps = collections.Counter((r.get("company") or {}).get("display_name", "") for r in data.get("results", []))
        same, top = summary(name, comps)
        out.append(f"AZ-{label}[{status}] total={data.get('count')} page_same={same}/{sum(comps.values())} top={top}")
        time.sleep(2.6)
    if REED:
        q = urllib.parse.urlencode({"keywords": name, "resultsToTake": 100})
        status, data = get(f"https://www.reed.co.uk/api/1.0/search?{q}", auth=REED)
        comps = collections.Counter(r.get("employerName", "") for r in data.get("results", []))
        same, top = summary(name, comps)
        out.append(f"REED[{status}] total={data.get('totalResults')} same={same}/{sum(comps.values())} top={top}")
    print("\n   ".join(out), flush=True)
