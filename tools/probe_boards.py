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
    "Google DeepMind": (["deepmind", "googledeepmind", "google-deepmind"], ["https://deepmind.google/about/careers/"]),
    "Thought Machine": (["thoughtmachine", "thought-machine"], ["https://www.thoughtmachine.net/careers"]),
    "Plaid": (["plaid", "plaidinc"], ["https://plaid.com/careers/"]),
    "Mollie": (["mollie", "molliepayments"], ["https://jobs.mollie.com/", "https://www.mollie.com/careers"]),
    "bunq": (["bunq"], ["https://www.bunq.com/careers"]),
    "Checkout.com": (["checkout", "checkoutcom", "checkout-com", "checkoutltd"], ["https://www.checkout.com/careers"]),
    "Skyscanner": (["skyscanner", "skyscannerltd"], ["https://www.skyscanner.net/jobs", "https://www.skyscannerjobs.net/"]),
    "Wayve": (["wayve", "wayvetechnologies", "wayve-technologies"], ["https://wayve.ai/careers/"]),
    "Cleo": (["cleo", "cleoai", "meetcleo", "cleo-ai"], ["https://web.meetcleo.com/careers"]),
    "Aiven": (["aiven", "aivenio", "aiven-io"], ["https://aiven.io/careers"]),
    "Supercell": (["supercell"], ["https://supercell.com/en/careers/"]),
    "RELEX Solutions": (["relex", "relexsolutions", "relex-solutions"], ["https://www.relexsolutions.com/careers/"]),
    "Einride": (["einride"], ["https://www.einride.tech/careers"]),
    "Voi Technology": (["voi", "voiscooters", "voitechnology", "voi-technology"], ["https://www.voi.com/careers"]),
    "Kry": (["kry", "livi", "kryinternational"], ["https://www.kry.se/en/careers/", "https://careers.kry.se/"]),
    "Docplanner": (["docplanner", "docplannergroup", "docplanner-group"], ["https://docplanner.tech/careers", "https://www.docplanner.com/careers"]),
    "Brainly": (["brainly"], ["https://careers.brainly.com/"]),
    "TravelPerk": (["travelperk", "perk"], ["https://www.perk.com/careers/", "https://www.travelperk.com/careers/"]),
    "Glovo": (["glovo", "glovoapp"], ["https://jobs.glovoapp.com/", "https://about.glovoapp.com/careers/"]),
    "Factorial": (["factorial", "factorialhr", "factorial-hr"], ["https://factorialhr.com/careers"]),
    "Kitopi": (["kitopi"], ["https://www.kitopi.com/careers"]),
    "Tabby": (["tabby", "tabbyai", "tabby-ai"], ["https://tabby.ai/en-AE/careers"]),
}

ATS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{id}/jobs", lambda d: len(d.get("jobs", []))),
    "lever": ("https://api.lever.co/v0/postings/{id}?mode=json", lambda d: len(d) if isinstance(d, list) else 0),
    "lever-eu": ("https://api.eu.lever.co/v0/postings/{id}?mode=json", lambda d: len(d) if isinstance(d, list) else 0),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{id}", lambda d: len(d.get("jobs", []))),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=1", lambda d: d.get("totalFound", 0)),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{id}", lambda d: len(d.get("jobs", []))),
    "recruitee": ("https://{id}.recruitee.com/api/offers/", lambda d: len(d.get("offers", []))),
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
                    n = "?"
                out.append(f"API {ats}:{i} -> {n} jobs")
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
