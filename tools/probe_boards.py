"""Find which applicant-tracking system aviation employers use (temporary probe).

Scans each careers page for ATS links and tries likely ids on the public ATS APIs.
"""

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (compatible; rch-sponsor-register/1.0; +https://github.com/niroshini-creator/rch-sponsor-register)"

EMPLOYERS = {
    "AerCap": (["aercap"], ["https://www.aercap.com/careers"]),
    "SMBC Aviation Capital": (["smbcaviationcapital", "smbc-aviation-capital", "smbcac"], ["https://www.smbc.aero/careers"]),
    "Avolon": (["avolon"], ["https://www.avolon.aero/careers"]),
    "Aer Lingus": (["aerlingus"], ["https://careers.aerlingus.com/", "https://www.aerlingus.com/about-us/careers/"]),
    "Ryanair": (["ryanair"], ["https://careers.ryanair.com/"]),
    "daa (Dublin Airport)": (["daa", "dublinairport"], ["https://www.daa.ie/careers/", "https://careers.daa.ie/"]),
    "CityJet": (["cityjet"], ["https://www.cityjet.com/careers/"]),
    "easyJet": (["easyjet"], ["https://careers.easyjet.com/"]),
    "Jet2": (["jet2"], ["https://www.jet2careers.com/"]),
    "Wizz Air": (["wizzair", "wizz-air"], ["https://careers.wizzair.com/"]),
    "Virgin Atlantic": (["virginatlantic"], ["https://careersuk.virgin-atlantic.com/", "https://careers.virgin-atlantic.com/"]),
    "British Airways": (["britishairways"], ["https://careers.ba.com/"]),
    "Loganair": (["loganair"], ["https://www.loganair.co.uk/careers/"]),
    "Heathrow": (["heathrow", "heathrowairport"], ["https://careers.heathrow.com/"]),
    "Gatwick Airport": (["gatwick", "gatwickairport"], ["https://www.gatwickairport.com/careers/"]),
    "Manchester Airports Group": (["magairports", "mag"], ["https://careers.magairports.com/"]),
    "Edinburgh Airport": (["edinburghairport"], ["https://www.edinburghairport.com/about-us/careers"]),
    "NATS": (["nats"], ["https://www.nats.aero/careers/"]),
    "Swissport": (["swissport"], ["https://www.swissport.com/en/careers"]),
    "Menzies Aviation": (["menziesaviation", "menzies"], ["https://menziesaviation.com/careers/"]),
    "dnata": (["dnata"], ["https://www.emiratesgroupcareers.com/"]),
    "Emirates Group": (["emirates", "emiratesgroup"], ["https://www.emiratesgroupcareers.com/search-and-apply/"]),
    "flydubai": (["flydubai"], ["https://careers.flydubai.com/"]),
    "Etihad Airways": (["etihad", "etihadairways"], ["https://careers.etihad.com/"]),
    "Airbus": (["airbus"], ["https://www.airbus.com/en/careers"]),
    "Rolls-Royce": (["rollsroyce", "rolls-royce"], ["https://careers.rolls-royce.com/"]),
    "GE Aerospace": (["geaerospace"], ["https://careers.geaerospace.com/"]),
    "Boeing": (["boeing"], ["https://jobs.boeing.com/"]),
    "Collins Aerospace (RTX)": (["rtx", "collinsaerospace"], ["https://careers.rtx.com/"]),
    "Leonardo UK": (["leonardo", "leonardouk"], ["https://uk.leonardo.com/en/careers"]),
    "Spirit AeroSystems": (["spiritaero"], ["https://www.spiritaero.com/careers/"]),
    "CAE": (["cae"], ["https://www.cae.com/careers/"]),
    "Lufthansa Technik": (["lufthansatechnik"], ["https://www.lufthansa-technik.com/en/careers"]),
    "Aviation leasing / OAG": (["oag", "oagaviation"], ["https://www.oag.com/careers"]),
    "Cirium": (["cirium"], ["https://www.cirium.com/careers/"]),
    "Skyports": (["skyports"], ["https://skyports.net/careers/"]),
    "Vertical Aerospace": (["verticalaerospace", "vertical-aerospace"], ["https://vertical-aerospace.com/careers/"]),
    "ZeroAvia": (["zeroavia"], ["https://zeroavia.com/careers/"]),
}

ATS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{id}/jobs", "jobs"),
    "lever": ("https://api.lever.co/v0/postings/{id}?mode=json", None),
    "lever-eu": ("https://api.eu.lever.co/v0/postings/{id}?mode=json", None),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{id}", "jobs"),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{id}", "jobs"),
    "recruitee": ("https://{id}.recruitee.com/api/offers/", "offers"),
}
LINK_RE = re.compile(
    r"(boards(?:-api)?\.greenhouse\.io/[\w-]+|job-boards(?:\.eu)?\.greenhouse\.io/[\w-]+|jobs(?:\.eu)?\.lever\.co/[\w-]+|"
    r"jobs\.ashbyhq\.com/[\w.-]+|jobs\.smartrecruiters\.com/[\w-]+|careers\.smartrecruiters\.com/[\w-]+|"
    r"apply\.workable\.com/[\w-]+|[\w-]+\.recruitee\.com|[\w-]+\.jobs\.personio\.(?:de|com)|[\w-]+\.teamtailor\.com|"
    r"[\w-]+\.wd\d+\.myworkdayjobs\.com(?:/[\w-]+){0,2}|[\w-]+\.pinpointhq\.com|[\w.-]*taleo\.net[\w/.-]*|"
    r"[\w.-]*successfactors\.(?:com|eu)[\w/.-]*|[\w.-]*icims\.com|[\w.-]*jobvite\.com/[\w-]+|[\w.-]*avature\.net[\w/.-]*|"
    r"[\w.-]*oraclecloud\.com/hcmUI[\w/.-]*|[\w.-]*eightfold\.ai|[\w.-]*phenompeople\.com|[\w.-]*tal\.net[\w/.-]*|"
    r"[\w.-]*jobtrain\.co\.uk|[\w.-]*peoplehr\.net|[\w.-]*hibob\.com|[\w.-]*bamboohr\.com|[\w.-]*breezy\.hr)", re.I)


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(2_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80], url


def check(name: str) -> list[str]:
    ids, pages = EMPLOYERS[name]
    out = []
    for ats, (tmpl, key) in ATS.items():
        for i in ids:
            status, body, _ = get(tmpl.format(id=i))
            if status == 200:
                try:
                    d = json.loads(body)
                    n = len(d.get(key, [])) if key else len(d)
                except Exception:  # noqa: BLE001
                    n = "?"
                if n:
                    out.append(f"API {ats}:{i} -> {n} jobs")
    for page in pages:
        status, body, final = get(page)
        links = sorted(set(m.lower().rstrip("/.") for m in LINK_RE.findall(body)))
        out.append(f"PAGE {page} [{status}] final={final} links={links[:10]}")
    return out


with ThreadPoolExecutor(max_workers=8) as pool:
    for name, lines in zip(EMPLOYERS, pool.map(check, EMPLOYERS)):
        print(f"=== {name}")
        for line in lines:
            print(f"   {line}")
