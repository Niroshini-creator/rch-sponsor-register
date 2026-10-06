"""Find which job system each requested employer / airport uses (temporary)."""

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
HINTS = re.compile(
    r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[A-Za-z0-9_/-]*|boards(?:-api)?\.greenhouse\.io/[a-z0-9_-]+|"
    r"jobs\.lever\.co/[a-z0-9_-]+|jobs\.smartrecruiters\.com/[A-Za-z0-9_-]+|careers\.smartrecruiters\.com/[A-Za-z0-9_-]+|"
    r"jobs\.ashbyhq\.com/[a-z0-9_-]+|[a-z0-9-]+\.recruitee\.com|[a-z0-9-]+\.teamtailor\.com|apply\.workable\.com/[a-z0-9_-]+|"
    r"[a-z0-9.-]*successfactors\.(?:eu|com)[^\"' ]{0,80}|rmkcdn\.successfactors\.com|[a-z0-9-]+\.taleo\.net[^\"' ]{0,60}|"
    r"[a-z0-9.-]+\.oraclecloud\.com[^\"' ]{0,100}|eightfold\.ai|phenompeople|cdn\.phenompeople\.com|"
    r"[a-z0-9-]+\.icims\.com|[a-z0-9-]+\.avature\.net|[a-z0-9-]+\.jobs\.personio\.(?:de|com)|"
    r"[a-z0-9-]+\.csod\.com|[a-z0-9-]+\.pageuppeople\.com|[a-z0-9-]+\.tal\.net|[a-z0-9-]+\.webitrent\.com|"
    r"[a-z0-9-]+\.hirehive\.com|[a-z0-9-]+\.zohorecruit\.[a-z]+|jobs\.jobvite\.com/[a-z0-9_-]+|"
    r"[a-z0-9-]+\.bamboohr\.com|[a-z0-9-]+\.applytojob\.com|[a-z0-9-]+\.dayforcehcm\.com[^\"' ]{0,60}|"
    r"/services/rss/job|beapplied\.com|join\.com/companies/[a-z0-9_-]+", re.I)


def get(url: str, data: bytes | None = None, ctype: str = ""):
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-GB,en;q=0.9"}
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read(3_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80], url


def page(name_url):
    name, url = name_url
    status, body, final = get(url)
    hints = sorted(set(h.lower().rstrip("/") for h in HINTS.findall(body)))[:12]
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    return f"PAGE {name}: [{status}] {final} len={len(body)} title={(title.group(1).strip()[:60] if title else '')!r}\n   hints={hints}"


def workday(arg):
    host, site = arg
    tenant = host.split(".")[0]
    status, body, _ = get(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                          json.dumps({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).encode(),
                          "application/json")
    total = ""
    if status == 200:
        try:
            total = json.loads(body).get("total")
        except ValueError:
            pass
    return f"WD {host}/{site}: [{status}] total={total}" if status == 200 else ""


def simple(arg):
    label, url = arg
    status, body, final = get(url)
    sample = re.sub(r"\s+", " ", body[:160])
    return f"API {label}: [{status}] len={len(body)} sample={sample!r}"


PAGES = {
    "eBay": "https://jobs.ebayinc.com/us/en", "eBay2": "https://careers.ebayinc.com/",
    "Vertiv": "https://www.vertiv.com/en-us/about/careers/", "Vertiv2": "https://careers.vertiv.com/",
    "KPMG UK": "https://www.kpmgcareers.co.uk/", "KPMG UK jobs": "https://www.kpmgcareers.co.uk/experienced-professionals/search-jobs/",
    "KPMG IE": "https://kpmg.com/ie/en/home/careers.html", "KPMG IE jobs": "https://careers.kpmg.ie/",
    "Optum": "https://www.optum.com/en/careers.html", "UHG": "https://careers.unitedhealthgroup.com/",
    "Optum UK": "https://www.optum.co.uk/careers.html", "Optum IE": "https://www.optum.ie/careers.html",
    "Informa": "https://careers.informa.com/", "Informa2": "https://www.informa.com/careers/",
    "Veolia UK": "https://www.veolia.co.uk/careers", "Veolia UK jobs": "https://careers.veolia.co.uk/",
    "Veolia group": "https://www.veolia.com/en/careers", "Veolia jobs": "https://jobs.veolia.com/",
    "Heathrow": "https://careers.heathrow.com/", "Gatwick": "https://www.gatwickairport.com/careers/",
    "MAG": "https://careers.magairports.com/", "Edinburgh Airport": "https://careers.edinburghairport.com/",
    "Bristol Airport": "https://www.bristolairport.co.uk/about-us/careers", "Birmingham Airport": "https://careers.birminghamairport.co.uk/",
    "daa": "https://careers.daa.ie/", "Shannon": "https://www.shannongroup.ie/careers/",
    "Schiphol": "https://www.werkenbijschiphol.nl/", "Schiphol en": "https://www.schiphol.nl/en/jobs/",
    "Fraport": "https://www.fraport.com/en/career.html", "Munich Airport": "https://www.munich-airport.com/careers",
    "Swissport": "https://jobs.swissport.com/", "Menzies": "https://careers.menziesaviation.com/",
    "Emirates Group": "https://www.emiratesgroupcareers.com/", "Dubai Airports": "https://www.dubaiairports.ae/corporate/careers",
    "KLM": "https://careers.klm.com/", "Lufthansa": "https://www.be-lufthansa.com/en/",
    "easyJet": "https://careers.easyjet.com/", "Ryanair": "https://careers.ryanair.com/",
    "Aer Lingus": "https://careers.aerlingus.com/", "Virgin Atlantic": "https://careersuk.virgin-atlantic.com/",
    "British Airways": "https://careers.ba.com/", "NATS": "https://www.nats.aero/careers/",
    "Rolls-Royce": "https://careers.rolls-royce.com/", "BAE": "https://www.baesystems.com/en/careers",
    "Jet2": "https://www.jet2careers.com/", "Wizz": "https://careers.wizzair.com/",
    "RTX": "https://careers.rtx.com/", "GKN": "https://www.gknaerospace.com/careers/",
    "Leonardo UK": "https://uk.leonardo.com/en/careers", "Safran": "https://www.safran-group.com/jobs",
    "Brussels Airport": "https://jobs.brusselsairport.be/", "Copenhagen Airport": "https://www.cph.dk/en/about-cph/job",
    "Zurich Airport": "https://www.flughafen-zuerich.ch/en/company/working-at-zurich-airport", "Vienna Airport": "https://www.viennaairport.com/en/company/jobs__career",
    "Aena": "https://www.aena.es/en/corporative/work-with-us.html", "Groupe ADP": "https://www.parisaeroport.fr/en/group/careers",
    "Swedavia": "https://www.swedavia.com/about-swedavia/careers/", "Finavia": "https://www.finavia.fi/en/about-finavia/careers",
    "Avolon": "https://www.avolon.aero/careers", "AerCap": "https://www.aercap.com/careers",
    "SMBC Aviation": "https://www.smbc.aero/careers", "Eurocontrol": "https://www.eurocontrol.int/careers",
    "EASA": "https://www.easa.europa.eu/en/the-agency/careers", "Collins": "https://www.collinsaerospace.com/careers",
    "Visa": "https://corporate.visa.com/en/jobs/", "American Express": "https://aexp.eightfold.ai/careers",
    "PayPal": "https://careers.pypl.com/", "Deloitte UK": "https://apply.deloitte.com/careers",
    "EY": "https://careers.ey.com/", "PwC UK": "https://jobs.pwc.co.uk/",
}
WD = []
for host in ["ebay.wd5", "ebay.wd1", "vertiv.wd1", "vertiv.wd5", "kpmg.wd1", "kpmguk.wd3", "kpmg.wd3", "optum.wd5",
             "uhg.wd1", "informa.wd3", "informa.wd1", "veolia.wd3", "heathrow.wd3", "menzies.wd3", "swissport.wd3",
             "rollsroyce.wd3", "baesystems.wd3", "paypal.wd1", "visa.wd5", "aercap.wd3", "fraport.wd3", "klm.wd3",
             "rtx.wd1", "gkn.wd3", "leonardo.wd3", "smbcaviation.wd3", "avolon.wd3", "easyjet.wd3", "deloitte.wd3"]:
    for site in ["External", "Careers", "careers", "External_Careers", "ExternalCareers", "apply", "jobs", "Search",
                 "en-US", host.split(".")[0], host.split(".")[0].upper(), "Global", "Experienced", "CareerSite"]:
        WD.append((f"{host}.myworkdayjobs.com", site))
APIS = [(f"greenhouse {s}", f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs") for s in
        ["ebay", "informa", "vertiv", "kpmg", "veolia", "heathrow", "easyjet", "wizzair", "aerlingus", "skyports"]]
APIS += [(f"smartrecruiters {s}", f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1") for s in
         ["eBay", "Informa", "Vertiv", "KPMG", "Veolia", "VeoliaUK", "Heathrow", "Swissport", "Menzies", "Fraport",
          "Lufthansa", "LufthansaGroup", "dnata", "Emirates", "DubaiAirports", "Visa", "BoschGroup", "Daa", "Ryanair"]]
APIS += [(f"lever {s}", f"https://api.lever.co/v0/postings/{s}?limit=1&mode=json") for s in
         ["ebay", "informa", "kpmg", "veolia", "heathrow", "ryanair", "wizzair"]]

with ThreadPoolExecutor(16) as ex:
    for line in ex.map(page, PAGES.items()):
        print(line, flush=True)
    print("\n---- workday guesses")
    for line in ex.map(workday, WD):
        if line:
            print(line, flush=True)
    print("\n---- api guesses")
    for line in ex.map(simple, APIS):
        if "[200]" in line:
            print(line, flush=True)
