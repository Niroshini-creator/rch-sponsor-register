"""Where did Mistral AI's job board move? (temporary)"""
import json, re, urllib.error, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(3_000_000).decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:80], url


for slug in ["mistral", "mistralai", "mistral-ai"]:
    for url in [f"https://api.lever.co/v0/postings/{slug}?mode=json", f"https://api.eu.lever.co/v0/postings/{slug}?mode=json",
                f"https://api.ashbyhq.com/posting-api/job-board/{slug}", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                f"https://apply.workable.com/api/v1/widget/accounts/{slug}"]:
        st, body, _ = get(url)
        n = ""
        if st == 200:
            try:
                d = json.loads(body)
                n = len(d) if isinstance(d, list) else len(d.get("jobs", []))
            except ValueError:
                n = "non-json"
        print(f"{st} {url} jobs={n}")
for url in ["https://mistral.ai/careers", "https://jobs.lever.co/mistral", "https://jobs.ashbyhq.com/mistral"]:
    st, body, final = get(url)
    hints = sorted(set(re.findall(r"(?:jobs\.(?:eu\.)?lever\.co|jobs\.ashbyhq\.com|boards\.greenhouse\.io|job-boards\.greenhouse\.io|apply\.workable\.com|[a-z0-9-]+\.teamtailor\.com|[a-z0-9-]+\.jobs\.personio\.(?:de|com)|[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/?[A-Za-z0-9_\-]*", body)))[:10]
    print(f"PAGE {url}: [{st}] final={final} len={len(body)} hints={hints}")
