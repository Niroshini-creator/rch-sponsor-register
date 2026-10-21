"""Find which large UK sponsors' careers sites the board can read (temporary)."""
import collections
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
NAMES = json.load(open("tools/candidates.json"))


def get(url, data=None):
    headers = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9", "Accept-Language": "en-GB"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(40_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:60], url


def slugs(name):
    base = re.sub(r"\(.*?\)", "", name).lower().replace("&", "and")
    words = re.findall(r"[a-z0-9]+", base)
    drop = {"plc", "ltd", "limited", "group", "the", "uk", "and", "llp", "inc"}
    core = [w for w in words if w not in drop] or words
    out = ["".join(core), "-".join(core), core[0], "".join(words)]
    return list(dict.fromkeys(s for s in out if len(s) > 1))


def places(items):
    c = collections.Counter(items)
    return [k for k, _ in c.most_common(3)]


def probe(name):
    try:
        return _probe(name)
    except Exception as e:  # noqa: BLE001
        return name, [f"probe error {str(e)[:60]}"]


def _probe(name):
    found = []
    for s in slugs(name):
        st, body, _ = get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs")
        if st == 200 and '"jobs"' in body:
            jobs = json.loads(body).get("jobs", [])
            if jobs:
                found.append(f"greenhouse id={s} n={len(jobs)} {places((j.get('location') or {}).get('name', '') for j in jobs)}")
        st, body, _ = get(f"https://api.lever.co/v0/postings/{s}?mode=json")
        if st == 200 and body.startswith("["):
            jobs = json.loads(body)
            if jobs:
                found.append(f"lever id={s} n={len(jobs)} {places((j.get('categories') or {}).get('location', '') for j in jobs)}")
        st, body, _ = get(f"https://api.ashbyhq.com/posting-api/job-board/{s}")
        if st == 200 and '"jobs"' in body:
            jobs = json.loads(body).get("jobs", [])
            if jobs:
                found.append(f"ashby id={s} n={len(jobs)} {places(j.get('location', '') for j in jobs)}")
        for sid in dict.fromkeys([s, s.capitalize(), name.replace(" ", "")]):
            st, body, _ = get(f"https://api.smartrecruiters.com/v1/companies/{sid}/postings?limit=100")
            if st == 200:
                d = json.loads(body)
                if d.get("totalFound"):
                    c = (d.get("content") or [{}])[0].get("company", {}).get("name", "")
                    found.append(f"smartrecruiters id={sid} n={d['totalFound']} company={c!r} "
                                 f"{places((p.get('location') or {}).get('country', '') for p in d.get('content', []))}")
                    break
        st, body, _ = get(f"https://apply.workable.com/api/v1/widget/accounts/{s}")
        if st == 200 and '"jobs"' in body:
            d = json.loads(body)
            if d.get("jobs"):
                found.append(f"workable id={s} n={len(d['jobs'])} name={d.get('name')!r} {places(j.get('country', '') for j in d['jobs'])}")
        for wd in ("wd3", "wd1", "wd5", "wd103", "wd12"):
            st, body, final = get(f"https://{s}.{wd}.myworkdayjobs.com/")
            m = re.search(r"myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_\-]+)", final)
            if st == 200 and m and m.group(1) not in ("wday",):
                site = m.group(1)
                st2, body2, _ = get(f"https://{s}.{wd}.myworkdayjobs.com/wday/cxs/{s}/{site}/jobs",
                                    json.dumps({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).encode())
                total = json.loads(body2).get("total") if st2 == 200 else None
                found.append(f"workday host={s}.{wd}.myworkdayjobs.com site={site} total={total}")
                break
    return name, found


with ThreadPoolExecutor(12) as ex:
    for name, found in ex.map(probe, NAMES):
        print(f"{name}: " + (" || ".join(found) if found else "-"), flush=True)
