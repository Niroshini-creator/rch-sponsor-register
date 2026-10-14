"""Add an employer's career site to config/employers.json from any live job link on it.

    python -m jobfeed.addemployer "Comcast" "https://comcast.wd5.myworkdayjobs.com/en-US/Comcast_Careers/job/London/Analyst_R123" --country US

The link is read, not fetched: the applicant-tracking system's address pattern says which system it is and which board
(tenant, site, id) to read, so this works offline. Supported: Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable,
Recruitee and Oracle Recruiting. Companies on their own career platform (Amazon, Google, Microsoft ...) have no such pattern
and cannot be added this way. Check the entry after the next feed run: a board that cannot be read is listed under
"Where these vacancies come from" (or the board's Data sources) instead of stopping the feed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

EMPLOYERS_FILE = Path(__file__).resolve().parent.parent / "config" / "employers.json"
SUPPORTED = "Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Oracle Recruiting"
_LOCALE = re.compile(r"^[a-z]{2}(?:-[A-Za-z]{2})?$")


def entry_from_url(name: str, url: str, country: str = "GB", register_name: str = "") -> dict:
    """The employers.json entry for the career site behind `url`; ValueError when the system is not recognised."""
    parts = urlparse(url if "//" in url else f"https://{url}")
    host, segs = (parts.hostname or "").lower(), [s for s in parts.path.split("/") if s]
    base = {"name": name, "country": country.upper()}
    if register_name:
        base["register_name"] = register_name

    if host.endswith(".myworkdayjobs.com"):
        site = next((s for s in segs if not _LOCALE.match(s) and s != "job"), "")
        if not site:
            raise ValueError("Workday link needs the site name, e.g. https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers/job/...")
        return {**base, "ats": "workday", "host": host, "site": site}
    if host.endswith("greenhouse.io") and segs:
        return {**base, "ats": "greenhouse", "id": segs[0]}
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and segs:
        return {**base, "ats": "lever", "id": segs[0], **({"region": "eu"} if host == "jobs.eu.lever.co" else {})}
    if host == "jobs.ashbyhq.com" and segs:
        return {**base, "ats": "ashby", "id": segs[0]}
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com") and segs:
        return {**base, "ats": "smartrecruiters", "id": segs[0]}
    if host == "apply.workable.com" and segs:
        return {**base, "ats": "workable", "id": segs[0]}
    if host.endswith(".recruitee.com"):
        return {**base, "ats": "recruitee", "id": host.split(".")[0]}
    if host.endswith(".oraclecloud.com") and "sites" in segs and segs.index("sites") + 1 < len(segs):
        return {**base, "ats": "oracle", "host": host, "site": segs[segs.index("sites") + 1]}
    raise ValueError(f"{host or url!r} is not a career-site system this feed can read ({SUPPORTED}). "
                     "Employers on their own platform (Amazon, Google, Microsoft ...) cannot be added this way.")


def _row(entry: dict) -> str:
    """One employer as the config file writes it: `    { "name": "Monzo", "ats": "greenhouse", ... }`."""
    return "    { " + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in entry.items()) + " }"


def add(entry: dict, path: Path = EMPLOYERS_FILE) -> str:
    """Add or replace the employer (matched by name) and return "added" or "replaced".

    The file is edited line by line so the rest of it keeps its formatting and a commit shows only the new row."""
    lines = path.read_text(encoding="utf-8").split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip().startswith('"employers"')) + 1
    end = next(i for i in range(len(lines) - 1, start - 1, -1) if lines[i].strip() == "]")
    for i in range(start, end):
        text = lines[i].strip().rstrip(",")
        if text.startswith("{") and json.loads(text)["name"].lower() == entry["name"].lower():
            lines[i] = _row({**json.loads(text), **entry}) + ("," if lines[i].rstrip().endswith(",") else "")
            path.write_text("\n".join(lines), encoding="utf-8")
            return "replaced"
    last = max(i for i in range(start, end) if lines[i].strip().startswith("{"))
    lines[last] = lines[last].rstrip() + ","
    lines.insert(last + 1, _row(entry))
    path.write_text("\n".join(lines), encoding="utf-8")
    return "added"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", help="employer name as it should appear")
    ap.add_argument("url", help="any live job (or careers search) link on its career site")
    ap.add_argument("--country", default="GB", help="home country, ISO-2 (default GB)")
    ap.add_argument("--register-name", default="", help="legal name on the UK sponsor register, if different")
    ap.add_argument("--max-jobs", type=int, default=0, help="cap on adverts read per run (very large employers)")
    ap.add_argument("--unverified", action="store_true", help="mark the address as a best guess, to be checked after the next feed run")
    ap.add_argument("--file", type=Path, default=EMPLOYERS_FILE)
    args = ap.parse_args(argv)
    try:
        entry = entry_from_url(args.name, args.url, args.country, args.register_name)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if args.max_jobs:
        entry["max_jobs"] = args.max_jobs
    if args.unverified:
        entry["verify"] = True
    print(f"{add(entry, args.file)} {args.name}: {json.dumps(entry)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
