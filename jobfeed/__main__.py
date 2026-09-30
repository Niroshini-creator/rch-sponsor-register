"""CLI: python -m jobfeed [--days 7] [--out data/jobs.json]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .pipeline import ROOT, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the sponsored-jobs feed.")
    parser.add_argument("--days", type=int, default=7, help="maximum job age in days (default 7)")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "jobs.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    payload = run(args.days, args.out)
    for name, st in payload["sources"].items():
        detail = st.get("count", st.get("reason") or st.get("error") or "")
        print(f"  {name:<24} {st['status']:<9} {detail}")
    c = payload["counts"]
    print(f"fetched {c['fetched']} → removed {c['agency_removed']} agency adverts → published {c['published']} jobs → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
