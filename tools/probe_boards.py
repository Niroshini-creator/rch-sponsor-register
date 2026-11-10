"""Where did Mistral AI's job board move? (temporary, round 2)"""
import json, re, urllib.error, urllib.parse, urllib.request

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


st, body, _ = get("https://mistral.ai/careers")
links = sorted(set(re.findall(r"https?://jobs\.ashbyhq\.com/[^\"'\s<>\\)]+", body)))
print("links", links[:10])
slugs = {urllib.parse.unquote(l.split("jobs.ashbyhq.com/")[1].split("/")[0].split("?")[0]) for l in links} | {"mistral.ai", "Mistral AI", "mistralai"}
for slug in slugs:
    url = "https://api.ashbyhq.com/posting-api/job-board/" + urllib.parse.quote(slug)
    st2, body2, _ = get(url)
    n = ""
    if st2 == 200:
        d = json.loads(body2)
        jobs = d.get("jobs", [])
        n = f"{len(jobs)} sample={[ (j.get('title'), j.get('location')) for j in jobs[:3]]}"
    print(st2, repr(slug), n)
