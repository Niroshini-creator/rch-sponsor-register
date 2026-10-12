"""Check each directory employer's careers address opens (temporary)."""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


def check(item):
    country, name, url = item
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en-GB,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return f"{r.status} {country} {name}: {url} -> {r.geturl()}"
    except urllib.error.HTTPError as e:
        return f"{e.code} {country} {name}: {url}"
    except Exception as e:  # noqa: BLE001
        return f"ERR {country} {name}: {url} {str(e)[:60]}"


urls = json.load(open("tools/careers_urls.json"))
items = [(c, n, u) for c, rows in urls.items() for n, u in rows.items()]
with ThreadPoolExecutor(12) as ex:
    for line in ex.map(check, items):
        print(line, flush=True)
