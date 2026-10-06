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


def show(label, url, n=700, data=None, ctype=""):
    status, body, final = get(url, data, ctype)
    sample = re.sub(r"\s+", " ", body[:n])
    print(f"=== {label}: [{status}] {final} len={len(body)} items={body.count('<item')}\n   {sample}\n", flush=True)
    return body


def links(label, url):
    status, body, final = get(url)
    hrefs = sorted(set(h for h in re.findall(r'href=["\']([^"\'#]+)', body)
                       if re.search(r"job|vacan|career|recruit|apply|opening|position|stellen|vacature", h, re.I)))[:40]
    print(f"=== LINKS {label}: [{status}] {final}\n   " + "\n   ".join(hrefs) + "\n", flush=True)


def oracle(label, host, site):
    url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
           f"&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},limit=3,offset=0,"
           f"sortBy=POSTING_DATES_DESC")
    show(f"ORACLE {label} {site}", url, 900)


def wd(host, site):
    tenant = host.split(".")[0]
    show(f"WD {host}/{site}", f"https://{host}/wday/cxs/{tenant}/{site}/jobs", 200,
         json.dumps({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).encode(), "application/json")


def page(name_url):
    name, url = name_url
    status, body, final = get(url)
    hints = sorted(set(h.lower().rstrip("/") for h in HINTS.findall(body)))[:12]
    return f"PAGE {name}: [{status}] {final} len={len(body)} hints={hints}"


status, body, _ = get("https://careers.ey.com/services/rss/job/?locale=en_GB&keywords=&rows=1000")
print("SF EY rows=1000 items", body.count("<item"))
for label, url in [("Gatwick", "https://jobs.gatwickairport.com/jobs/home/"), ("Bristol", "https://jobs.bristolairport.co.uk/vacancies"),
                   ("NATS", "https://www.nats.aero/careers/vacancies/"), ("Rolls-Royce", "https://careers.rolls-royce.com/en/jobs"),
                   ("Leonardo", "https://careers.uk.leonardo.com/gb/en/search-results"), ("Munich", "https://www.munich-airport.de/alle-jobs-jetzt-bewerben-94732"),
                   ("Edinburgh", "https://careers.edinburghairport.com/careers"), ("Emirates", "https://www.emiratesgroupcareers.com/search-and-apply/"),
                   ("Eurocontrol", "https://jobs.eurocontrol.int/all-vacancies"), ("AerCap", "https://www.aercap.com/careers/career-opportunities"),
                   ("Jet2", "https://jet2careers.com/search-careers/"), ("Schiphol", "https://www.schipholcareers.nl/vacatures"),
                   ("eBay", "https://jobs.ebayinc.com/us/en/search-results"), ("UHG IE", "https://careers.unitedhealthgroup.com/ireland-careers-jobs")]:
    print(page((label, url)), flush=True)
    links(label, url)
