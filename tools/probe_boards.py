"""Where can HMRC / Civil Service vacancies be read? (temporary)"""
import collections, json, os, re, time, urllib.error, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
AZ = {"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"]}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-GB"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(5_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace"), url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80], url


print("---- Adzuna")
for label, extra in [("company=HM Revenue & Customs", {"company": "HM Revenue & Customs"}),
                     ("company=HM Revenue and Customs", {"company": "HM Revenue and Customs"}),
                     ("company=HMRC", {"company": "HMRC"}),
                     ("what_and=HMRC", {"what_and": "HMRC"}),
                     ("what_phrase=HM Revenue", {"what_phrase": "HM Revenue"}),
                     ("company=Home Office", {"company": "Home Office"}),
                     ("company=Department for Work and Pensions", {"company": "Department for Work and Pensions"}),
                     ("company=Ministry of Justice", {"company": "Ministry of Justice"}),
                     ("company=Ministry of Defence", {"company": "Ministry of Defence"}),
                     ("company=Cabinet Office", {"company": "Cabinet Office"}),
                     ("what_phrase=civil service", {"what_phrase": "civil service"})]:
    q = urllib.parse.urlencode({**AZ, "results_per_page": 50, "max_days_old": 14, "sort_by": "date", **extra})
    st, body, _ = get(f"https://api.adzuna.com/v1/api/jobs/gb/search/1?{q}")
    try:
        d = json.loads(body)
    except ValueError:
        print(label, st, body[:120]); continue
    comps = collections.Counter((r.get("company") or {}).get("display_name", "") for r in d.get("results", []))
    urls = [r.get("redirect_url", "")[:60] for r in d.get("results", [])[:2]]
    print(f"{label}: [{st}] total={d.get('count')} top={comps.most_common(4)} sample={[r.get('title') for r in d.get('results', [])[:3]]}")
    time.sleep(2.6)

print("---- Find a Job (DWP)")
for u in ["https://findajob.dwp.gov.uk/search?q=HMRC&loc=86383", "https://findajob.dwp.gov.uk/search?q=HM+Revenue+and+Customs",
          "https://findajob.dwp.gov.uk/search.rss?q=HMRC", "https://findajob.dwp.gov.uk/search?q=civil+service&pp=50"]:
    st, body, final = get(u)
    titles = re.findall(r'<h3[^>]*class="govuk-heading-s"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', body)
    comp = re.findall(r'<li><strong>([^<]+)</strong>', body)[:6]
    print(f"{u}: [{st}] len={len(body)} final={final[:70]} n={len(titles)} first={titles[:3]} companies={comp}")
    if "rss" in u: print("   ", body[:300].replace("\n", " "))

print("---- Civil Service Jobs")
for u in ["https://www.civilservicejobs.service.gov.uk/csr/index.cgi", "https://www.civilservicejobs.service.gov.uk/csr/esearch.cgi"]:
    st, body, final = get(u)
    print(f"{u}: [{st}] len={len(body)} final={final[:80]} title={re.search(r'<title>(.*?)</title>', body, re.S).group(1).strip()[:80] if '<title>' in body else ''}")
