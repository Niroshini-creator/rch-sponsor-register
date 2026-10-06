"""Find Ireland's employment-permit company statistics and Irish public-sector / university job feeds (temporary)."""

import re
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; rch-sponsor-register/1.0; +https://github.com/niroshini-creator/rch-sponsor-register)"


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(3_000_000), r.geturl(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, b"", url, ""
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:100].encode(), url, ""


def links(html: str, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, html, re.I)))[:40]


# 1. DETE employment permit statistics: find the per-company files.
for page in ("https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/statistics/",
             "https://enterprise.gov.ie/en/publications/employment-permits-statistics.html"):
    status, body, final, ctype = get(page)
    html = body.decode("utf-8", "replace")
    print(f"=== {page} [{status}] final={final}")
    print("  files:", links(html, r'href="([^"]+\.(?:xlsx|xls|csv|pdf|ods))"'))
    print("  pages:", links(html, r'href="([^"]*(?:compan|employer|statistic)[^"]*)"')[:25])

# 2. Irish public sector, health, schools and universities.
for page in ("https://www.publicjobs.ie/en/", "https://www.publicjobs.ie/en/rss", "https://www.publicjobs.ie/rss.xml",
             "https://about.hse.ie/jobs/", "https://careerhub.hse.ie/", "https://www.educationposts.ie/",
             "https://www.educationposts.ie/rss", "https://www.tcd.ie/hr/vacancies/", "https://jobs.tcd.ie/",
             "https://www.ucd.ie/workatucd/jobs/", "https://www.ucc.ie/en/hr/vacancies/", "https://www.universityofgalway.ie/about-us/jobs/",
             "https://www.dcu.ie/hr/vacancies", "https://www.ul.ie/hr/vacancies", "https://www.maynoothuniversity.ie/human-resources/vacancies",
             "https://www.rcsi.com/dublin/about/jobs", "https://www.tudublin.ie/explore/working-at-tu-dublin/",
             "https://www.jobs.ac.uk/search/?keywords=&location=Ireland&sortOrder=1",
             "https://www.timeshighereducation.com/unijobs/jobsrss/?keywords=ireland",
             "https://euraxess.ec.europa.eu/jobs/search?keywords=ireland"):
    status, body, final, ctype = get(page)
    html = body.decode("utf-8", "replace")
    ats = links(html, r"(boards(?:-api)?\.greenhouse\.io/[\w-]+|jobs\.lever\.co/[\w-]+|jobs\.ashbyhq\.com/[\w.-]+|"
                      r"[\w-]+\.wd\d+\.myworkdayjobs\.com(?:/[\w-]+)?|[\w.-]*taleo\.net|[\w.-]*successfactors\.(?:com|eu)|"
                      r"[\w.-]*oraclecloud\.com|[\w.-]*jobtrain\.co\.uk|[\w.-]*coreportal\.com|[\w.-]*corehr\.com|"
                      r"[\w.-]*stonefish[\w.-]*|[\w.-]*erecruit[\w.-]*|[\w.-]*irecruit[\w.-]*|[\w.-]*smartrecruiters\.com/[\w-]+|"
                      r"[\w.-]*teamtailor\.com|[\w.-]*recruitee\.com|[\w.-]*icims\.com|[\w.-]*rss[\w./-]*|[\w.-]*feed[\w./-]*)")
    rss = body.count(b"<item")
    print(f"=== {page} [{status}] {ctype} {len(body)}B items={rss} final={final}\n  ats/feeds: {ats[:15]}")
