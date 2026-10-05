"""CLI: python -m mugilan.jobmatch [--days 7] [--out mugilan/data/jobs.json]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .pipeline import DEFAULT_OUT, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the candidate's matched-jobs feed.")
    parser.add_argument("--days", type=int, default=0, help="maximum job age in days (default: profile window, 7)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    payload = run(args.days, args.out)
    for name, st in payload["sources"].items():
        print(f"  {name:<22} {st['status']:<8} {st.get('count', st.get('reason') or st.get('error') or '')}")
    c = payload["counts"]
    print(f"fetched {c['fetched']} → {c['clearance_removed']} need clearance, {c['no_sponsorship_removed']} refuse sponsorship, "
          f"{c['below_threshold']} below threshold ({c.get('full_advert_fetched', 0)} full adverts read) → published {c['published']} → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
