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


# Oracle Recruiting Cloud
oracle("Vertiv", "egup.fa.us2.oraclecloud.com", "CX")
oracle("Heathrow", "encd.fa.em3.oraclecloud.com", "CX_3001")
for site in ["CX_1", "CX", "CX_1001", "CX_2001", "CX_3001"]:
    oracle("IAG", "iagime.fa.ocs.oraclecloud.com", site)
status, body, _ = get("https://careers.virginatlantic.com/")
print("VA oracle hints:", sorted(set(re.findall(r"iagime[^\"'<> ]{0,200}", body)))[:5])
status, body, _ = get("https://careers.ba.com/")
print("BA hints:", sorted(set(re.findall(r"https?://[a-z0-9.-]+/[^\"'<> ]{0,120}(?:job|vacanc|search)[^\"'<> ]{0,80}", body, re.I)))[:15])

# SuccessFactors Recruiting Marketing RSS
for host in ["careers.magairports.com", "jobs.swissport.com", "careers.wizzair.com", "jobs.brusselsairport.be",
             "careers.ey.com", "careers.edinburghairport.com", "jobs.ryanair.com"]:
    show(f"SF RSS {host}", f"https://{host}/services/rss/job/?locale=en_GB&keywords=", 900)

# Avature (Emirates)
show("Avature Emirates", "https://emiratesjobs.avature.net/en_US/careers/SearchJobs/?jobRecordsPerPage=6", 400)
show("Avature Emirates feed", "https://emiratesjobs.avature.net/en_US/careers/SearchJobs/feed/?jobRecordsPerPage=6", 900)
links("Emirates", "https://www.emiratesgroupcareers.com/")

# Veolia UK / Ireland Workday
for site in ["vescareers", "veoliairelandcareers", "VESCareers", "VeoliaIrelandCareers"]:
    wd("veoliauki.wd3.myworkdayjobs.com", site)

# Pages without a recognised ATS: list job links
for label, url in [("KPMG UK", "https://www.kpmgcareers.co.uk/"), ("KPMG IE", "https://kpmg.com/ie/en/careers.html"),
                   ("Optum IE", "https://www.optum.ie/careers.html"), ("Optum", "https://www.optum.com/en/careers.html"),
                   ("Gatwick", "https://www.gatwickairport.com/company/careers.html"), ("NATS", "https://www.nats.aero/careers/"),
                   ("Rolls-Royce", "https://careers.rolls-royce.com/en"), ("Jet2", "https://jet2careers.com/"),
                   ("Edinburgh", "https://careers.edinburghairport.com/"), ("Bristol", "https://www.bristolairport.co.uk/corporate/careers/"),
                   ("Munich", "https://www.munich-airport.com/careers-263141"), ("Schiphol", "https://www.schipholcareers.nl/"),
                   ("Avolon", "https://www.avolon.aero/careers"), ("AerCap", "https://www.aercap.com/careers/life-at-aercap"),
                   ("SMBC", "https://www.smbc.aero/WorkingWithUs"), ("Eurocontrol", "https://www.eurocontrol.int/careers"),
                   ("Leonardo", "https://uk.leonardo.com/en/people"), ("eBay", "https://careers.ebayinc.com/"),
                   ("Vertiv", "https://www.vertiv.com/en-us/about/career-center/")]:
        links(label, url)
show("UHG search", "https://careers.unitedhealthgroup.com/search-jobs/results?ActiveFacetID=0&CurrentPage=1&RecordsPerPage=3&Keywords=&Location=Ireland&SearchResultsModuleName=Search+Results&SearchFiltersModuleName=Search+Filters&SortCriteria=0&SortDirection=0&SearchType=5", 900)
