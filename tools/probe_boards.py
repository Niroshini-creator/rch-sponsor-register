"""Find which applicant-tracking system and board id each employer uses.

Tries likely ids on each public ATS API and scans the employer's careers page for ATS links.
Run from GitHub Actions (Probe employer boards); prints one line per hit.
"""

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)"

EMPLOYERS = {
    "Plaid": (["plaid", "plaid-inc", "plaidtechnologies"], ["https://plaid.com/careers/openings/"]),
    "Checkout.com": (["checkout", "checkoutcom", "checkout-com", "checkoutcomltd", "cko"],
                     ["https://www.checkout.com/careers/open-roles", "https://checkout.com/careers/jobs"]),
    "Skyscanner": (["skyscanner", "skyscannerltd", "skyscanner-ltd"],
                   ["https://www.skyscanner.net/jobs/current-jobs", "https://www.skyscanner.net/jobs/open-roles"]),
    "Cleo": (["cleo-2", "cleo"], []),
    "Aiven": (["aiven", "aivenio", "aiven-oy", "aivencareers"], ["https://aiven.io/careers/open-positions", "https://aiven.io/careers/jobs"]),
    "Einride": (["einride", "einride-ab"], ["https://www.einride.tech/career", "https://einride.tech/careers/"]),
    "Voi Technology": (["voi", "voitechnology", "voi-technology", "voiscooters"], ["https://www.voi.com/career", "https://voi.com/careers/"]),
    "Kry": (["kry", "livi", "kry-livi", "kryinternational"], ["https://www.kry.se/karriar/", "https://www.livi.co.uk/careers/"]),
    "TravelPerk": (["travelperk", "perk", "perk-1", "travelperk-1"], ["https://www.perk.com/careers/open-positions/"]),
    "Glovo": (["glovo", "glovoapp", "glovo-1"], ["https://careers.glovoapp.com/jobs-at-glovo/"]),
    "Factorial": (["factorial", "factorialhr", "factorial-hr", "everyday-software"], ["https://factorialhr.com/jobs"]),
    "Kitopi": (["kitopi", "kitopi-1"], ["https://jobs.lever.co/kitopi"]),
    "Tabby": (["tabby", "tabbyai", "tabby-ai", "tabby-fintech"], ["https://tabby.ai/careers", "https://tabby.ai/en-AE/careers/jobs"]),
}

ATS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{id}/jobs", lambda d: len(d.get("jobs", []))),
    "lever": ("https://api.lever.co/v0/postings/{id}?mode=json", lambda d: len(d) if isinstance(d, list) else 0),
    "lever-eu": ("https://api.eu.lever.co/v0/postings/{id}?mode=json", lambda d: len(d) if isinstance(d, list) else 0),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{id}", lambda d: len(d.get("jobs", []))),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=1", lambda d: d.get("totalFound", 0)),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{id}", lambda d: len(d.get("jobs", []))),
    "recruitee": ("https://{id}.recruitee.com/api/offers/", lambda d: len(d.get("offers", []))),
    "greenhouse-eu": ("https://boards-api.eu.greenhouse.io/v1/boards/{id}/jobs", lambda d: len(d.get("jobs", []))),
}
EXTRA = {  # XML/RSS boards: count items
    "personio-de": "https://{id}.jobs.personio.de/xml",
    "personio-com": "https://{id}.jobs.personio.com/xml",
    "teamtailor": "https://{id}.teamtailor.com/jobs.rss",
    "pinpoint": "https://{id}.pinpointhq.com/postings.json",
}
LINK_RE = re.compile(
    r"(boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?[\w-]+|job-boards(?:\.eu)?\.greenhouse\.io/[\w-]+|"
    r"jobs(?:\.eu)?\.lever\.co/[\w-]+|jobs\.ashbyhq\.com/[\w.-]+|jobs\.smartrecruiters\.com/[\w-]+|"
    r"apply\.workable\.com/[\w-]+|[\w-]+\.recruitee\.com|[\w-]+\.jobs\.personio\.(?:de|com)|[\w-]+\.teamtailor\.com|"
    r"[\w-]+\.wd\d+\.myworkdayjobs\.com/[\w-]+|careers\.[\w-]+\.com/[\w/-]*|[\w-]+\.bamboohr\.com|"
    r"jobs\.jobvite\.com/[\w-]+|[\w-]+\.breezy\.hr|careers\.smartrecruiters\.com/[\w-]+|"
    r"greenhouse\.io/embed/job_board\?for=[\w-]+|ats\.rippling\.com/[\w-]+|[\w-]+\.pinpointhq\.com)", re.I)


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(1_500_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80], url


def check(name: str) -> list[str]:
    ids, pages = EMPLOYERS[name]
    out = []
    for ats, (tmpl, count) in ATS.items():
        for i in ids:
            status, body, _ = get(tmpl.format(id=i))
            if status == 200:
                try:
                    n = count(json.loads(body))
                except Exception:  # noqa: BLE001
                    n = "? " + body[:150].replace("\n", " ")
                if n != 0:
                    out.append(f"API {ats}:{i} -> {n} jobs")
    for kind, tmpl in EXTRA.items():
        for i in ids:
            status, body, final = get(tmpl.format(id=i))
            items = body.count("<item") + body.count("<position") + body.count('"title"')
            if status == 200 and items:
                out.append(f"FEED {kind}:{i} -> {items} items final={final}")
    for page in pages:
        status, body, final = get(page)
        links = sorted(set(m.lower() for m in LINK_RE.findall(body)))
        out.append(f"PAGE {page} [{status}] final={final} links={links[:12]}")
    return out


with ThreadPoolExecutor(max_workers=6) as pool:
    for name, lines in zip(EMPLOYERS, pool.map(check, EMPLOYERS)):
        print(f"=== {name}")
        for line in lines:
            print(f"   {line}")
