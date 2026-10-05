"""Print the fields of one Pinpoint posting and one Teamtailor RSS item (temporary probe)."""

import json
import re
import urllib.request

UA = "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


data = json.loads(get("https://tabby.pinpointhq.com/postings.json"))["data"]
print("pinpoint postings:", len(data))
first = data[0]
for k, v in first.items():
    if k not in ("description", "benefits", "key_responsibilities", "skills_knowledge_expertise"):
        print(f"  {k}: {json.dumps(v)[:200]}")
print("  links:", data[0].get("url"), data[1].get("url"))

rss = get("https://careers.voi.com/jobs.rss")
item = re.search(r"<item>(.*?)</item>", rss, re.S).group(1)
print("teamtailor tags:", sorted(set(re.findall(r"<([\w:]+)[ >]", item))))
print(re.sub(r"<description>.*?</description>", "<description/>", item, flags=re.S)[:1500])
head = rss[:rss.find("<item")]
print("channel head:", re.sub(r"\s+", " ", head)[:600])
