"""CLI.

  python -m candidateboard intake --slug jane-doe --cv "SAP Security & GRC=sap.pdf" --cv "Business Analyst=ba.pdf" \\
        --roles-file suitable_roles.pdf --visa graduate --visa-label "Graduate visa (PSW)" --visa-expires 2027-11 --new-entrant
  python -m candidateboard build [--slug jane-doe] [--days 7] [--offline]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import cv, intake, pipeline


def _yes_no(value: str) -> bool | None:
    return {"yes": True, "no": False}.get(value.lower())


def cmd_intake(a) -> int:
    cvs = {}
    for item in a.cv:
        track, _, path = item.partition("=")
        if not path:
            sys.exit(f'--cv must be "Track name=path/to/cv.pdf", got {item!r}')
        cvs[track.strip()] = Path(path)
    roles_text = cv.read_text(Path(a.roles_file)) if a.roles_file else ""
    visa = {"type": a.visa, "label": a.visa_label or a.visa, "expires": a.visa_expires,
            "sponsorship": a.sponsorship, "new_entrant": a.new_entrant}
    profile = intake.build_profile(cvs, roles_text, name=a.name, slug=a.slug, location=a.location, visa=visa,
                                   clearance=a.clearance, driving_licence=_yes_no(a.driving_licence),
                                   current_status=a.status, notes=a.notes, regions=[r.strip().upper() for r in a.regions.split(",") if r.strip()], english_only=not a.any_language)
    out = Path(a.out) if a.out else pipeline.PROFILES / f"{profile['slug']}.json"
    intake.write_profile(profile, out)
    by_tier = {t: [r["title"] for r in profile["roles"] if r["tier"] == t] for t in (1, 2, 3)}
    print(f"{profile['name']}: {profile['experience_years']} years, {profile['education']}. Wrote {out}")
    for t, titles in by_tier.items():
        print(f"  Tier {t}: {len(titles)} roles" + (f"  e.g. {', '.join(titles[:4])}" if titles else ""))
    print("  Other roles to consider:", ", ".join(profile["also_consider"]) or "none")
    return 0


def cmd_build(a) -> int:
    paths = ([pipeline.PROFILES / f"{a.slug}.json"] if a.slug else sorted(pipeline.PROFILES.glob("*.json")))
    if not paths:
        sys.exit(f"no profiles in {pipeline.PROFILES}")
    for path in paths:
        payload = pipeline.run(path, a.days, Path(a.feed), Path(a.out_dir), a.offline)
        c = payload["counts"]
        print(f"{payload['candidate']['name']}: considered {c['considered']} → published {c['published']} "
              f"(tier 1: {c['by_tier']['1']}, 2: {c['by_tier']['2']}, 3: {c['by_tier']['3']}, other: {c['by_tier']['4']})")
        for name, st in payload["sources"].items():
            print(f"  {name:<22} {st['status']:<8} {st.get('count', st.get('reason') or st.get('error') or '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="candidateboard", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    i = sub.add_parser("intake", help="scan CVs and write a candidate profile")
    i.add_argument("--cv", action="append", required=True, help='"Track name=path" (repeat per CV)')
    i.add_argument("--roles-file", help="recruiter's suitable-roles list (PDF or text)")
    i.add_argument("--name", default="")
    i.add_argument("--slug", default="")
    i.add_argument("--location", default="")
    i.add_argument("--visa", default="", help="e.g. graduate, skilled_worker, global_business_mobility, dependant")
    i.add_argument("--visa-label", default="")
    i.add_argument("--visa-expires", default="", help="YYYY-MM or YYYY-MM-DD")
    i.add_argument("--sponsorship", choices=["required", "preferred", "not_needed"], default="preferred",
                   help="preferred = can work now but wants a sponsor before the visa ends")
    i.add_argument("--new-entrant", action="store_true", help="eligible for the Skilled Worker new-entrant salary rate")
    i.add_argument("--clearance", choices=["none", "basic", "sc", "dv"], default="none")
    i.add_argument("--driving-licence", choices=["yes", "no", "unknown"], default="unknown")
    i.add_argument("--regions", default="GB", help="where they would work, comma-separated: GB, IE, EU, AU, ME (default GB)")
    i.add_argument("--any-language", action="store_true", help="also show roles outside the English-speaking countries that need another language")
    i.add_argument("--status", default="", help="current work situation, shown on the board")
    i.add_argument("--notes", default="")
    i.add_argument("--out", help="profile path (default candidates/profiles/<slug>.json)")
    i.set_defaults(fn=cmd_intake)

    b = sub.add_parser("build", help="build candidates/data/<slug>.json for one or all profiles")
    b.add_argument("--slug")
    b.add_argument("--days", type=int, default=0)
    b.add_argument("--feed", default=str(pipeline.FEED))
    b.add_argument("--out-dir", default=str(pipeline.DATA))
    b.add_argument("--offline", action="store_true", help="score the shared feed only; no candidate searches")
    b.set_defaults(fn=cmd_build)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
