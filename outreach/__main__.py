"""CLI: python -m outreach <command>

  check             validate config, templates and contacts; show who each campaign can and can't reach
  import-employers  add recruitment inboxes published in job adverts (data/jobs.json) as employer prospects
  plan              show what today's run would send (nothing is sent)
  send [--live]     run today's sequences; without --live, messages go to outreach_data/outbox.jsonl
  scan-inbox        record email replies, opt-outs and bounces from the sending mailbox
  log-calls FILE    import outcomes from a filled-in call sheet
  mark              record an event by hand (reply, opt-out, interested, …)
  report            per-campaign funnel
  run [--live]      scan-inbox (if configured) then send: the command to schedule
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import calls, engine, inbox, templates
from .compliance import can_contact
from .config import ROOT, data_dir, load_config
from .contacts import import_employers_from_jobs, load_contacts
from .channels import make_senders
from .ledger import Ledger, Suppression


def _state():
    d = data_dir()
    return d, load_contacts(d / "contacts"), Ledger(d / "ledger.jsonl"), Suppression(d / "suppression.csv")


_EU = {"IE", "NL", "DE", "FR", "BE", "LU", "SE", "FI", "DK", "ES", "PT", "PL", "IT", "AT", "CZ", "GR", "RO", "HU",
       "SK", "SI", "HR", "BG", "LT", "LV", "EE", "CY", "MT"}


def _setup_warnings(cfg) -> list[str]:
    """Things the law expects of a sender, most of all one established outside the UK / EU (docs/OUTREACH.md)."""
    sender = cfg["sender"]
    countries = {c for camp in cfg.get("campaigns", {}).values() for c in (camp.get("filter") or {}).get("country", [])}
    out = []
    if not sender.get("privacy_url"):
        out.append("sender.privacy_url: publish a privacy notice (UK GDPR / GDPR art. 13-14) and link it")
    if not sender.get("registration"):
        out.append("sender.registration: say where the company is registered, e.g. 'Registered in India, CIN …'")
    if "GB" in countries and not sender.get("uk_representative"):
        out.append("sender.uk_representative: a company outside the UK targeting UK residents needs a UK "
                   "representative (UK GDPR art. 27)")
    if countries & _EU and not sender.get("eu_representative"):
        out.append("sender.eu_representative: a company outside the EU targeting EU residents needs an EU "
                   "representative (GDPR art. 27)")
    return out


def cmd_check(cfg, args) -> int:
    d, contacts, ledger, suppression = _state()
    problems = []
    for name, camp in cfg.get("campaigns", {}).items():
        for step in camp["steps"]:
            try:
                tpl = templates.load(step["template"])
            except FileNotFoundError:
                problems.append(f"{name}: template {step['template']!r} not found in templates/outreach/")
                continue
            problems += [f"{name}: {p}" for p in templates.lint(tpl, camp["audience"], step["channel"])]
    for c in contacts:
        problems += c.errors
    print(f"{len(contacts)} contacts in {d / 'contacts'}")
    today = datetime.now(timezone.utc).date()
    rules = cfg.get("compliance", {})
    for name, camp in cfg.get("campaigns", {}).items():
        members = [c for c in contacts if engine.matches(c, camp)]
        first = camp["steps"][0]["channel"]
        reasons = Counter()
        ok = 0
        for c in members:
            dec = can_contact(c, first, today, suppression, rules)
            ok += dec.ok
            if not dec.ok:
                reasons[dec.reason.split(":")[0]] += 1
        print(f"\n{name} ({camp['audience']}, starts with {first}): {len(members)} match, {ok} reachable")
        for reason, n in reasons.most_common():
            print(f"    {n:>4}  blocked: {reason}")
    warnings = _setup_warnings(cfg)
    if warnings:
        print("\nBefore going live:")
        for w in warnings:
            print(f"  - {w}")
    if problems:
        print("\nProblems:")
        for p in problems:
            print(f"  - {p}")
    return 1 if problems else 0


def _plan(cfg, args):
    d, contacts, ledger, suppression = _state()
    actions, skips = engine.plan(contacts, cfg, ledger, suppression, datetime.now(timezone.utc), args.campaign)
    return d, contacts, ledger, suppression, actions, skips


def _print_plan(actions, skips, verbose: bool) -> None:
    by = Counter((a.campaign, a.channel) for a in actions)
    for (camp, ch), n in sorted(by.items()):
        print(f"  {camp:<28} {ch:<9} {n}")
    if not actions:
        print("  nothing due")
    why = Counter(s.reason.split(":")[0] for s in skips)
    if why:
        print("  skipped: " + ", ".join(f"{n} {r}" for r, n in why.most_common()))
    if verbose:
        for a in actions:
            print(f"\n--- {a.campaign} step {a.step_index + 1} → {a.contact.address(a.channel)} [{a.decision.basis}]")
            if a.subject:
                print(f"Subject: {a.subject}")
            print(a.body)


def cmd_plan(cfg, args) -> int:
    *_, actions, skips = _plan(cfg, args)
    _print_plan(actions, skips, args.verbose)
    return 0


def cmd_send(cfg, args) -> int:
    d, contacts, ledger, suppression, actions, skips = _plan(cfg, args)
    _print_plan(actions, skips, args.verbose)
    senders = make_senders(args.live, d / "outbox.jsonl", {a.channel for a in actions if a.channel != "call"})
    stats = engine.execute(actions, senders, ledger, cfg, args.live)
    today = datetime.now(timezone.utc).date().isoformat()
    sheet = d / "calls" / f"{today}{'' if args.live else '-preview'}.csv"
    n_calls = calls.write_sheet(actions, sheet)
    mode = "LIVE" if args.live else "dry run (outreach_data/outbox.jsonl; add --live to send)"
    verb = "sent" if args.live else "previewed"
    print(f"{mode}: {verb} {stats['sent']}, failed {stats['failed']}" + (f", {n_calls} calls → {sheet}" if n_calls else ""))
    return 1 if stats["failed"] else 0


def cmd_scan(cfg, args) -> int:
    _, contacts, ledger, suppression = _state()
    stats = inbox.scan(contacts, ledger, suppression, args.days)
    print(", ".join(f"{v} {k}" for k, v in stats.items()))
    return 0


def cmd_log_calls(cfg, args) -> int:
    _, _, ledger, suppression = _state()
    n, problems = calls.import_outcomes(Path(args.file), ledger, suppression)
    print(f"logged {n} call outcomes")
    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


def cmd_mark(cfg, args) -> int:
    _, contacts, ledger, suppression = _state()
    key = (args.email or args.phone or "").lower()
    contact = next((c for c in contacts if key and key in (c.email, c.phone.lower())), None)
    if args.event in ("unsubscribed", "do_not_call", "complaint") or contact is None:
        if key:
            suppression.add(key, "call" if args.event == "do_not_call" else "*", args.event)
    if contact:
        ledger.append(args.event, contact.id, channel="manual", notes=args.note or "")
    print(f"{args.event} recorded for {key}" + ("" if contact else " (not in contacts: added to suppression list only)"))
    return 0


def cmd_report(cfg, args) -> int:
    _, contacts, ledger, _ = _state()
    rows = defaultdict(Counter)
    camp_of = {}
    for e in ledger.events:
        if e.get("campaign"):
            camp_of.setdefault(e["contact_id"], e["campaign"])
    for e in ledger.events:
        camp = e.get("campaign") or camp_of.get(e["contact_id"], "(none)")
        if e["event"] in ("sent", "call_queued"):
            rows[camp][f"step{e.get('step', 0) + 1}"] += 1
            if e.get("step", 0) == 0:
                rows[camp]["started"] += 1
        else:
            rows[camp][e["event"]] += 1
    print(f"{'campaign':<28} {'started':>7} {'replied':>7} {'interest':>8} {'opt-out':>7} {'bounced':>7} {'failed':>6}")
    for camp, c in sorted(rows.items()):
        replies = c["replied"] + c["interested"]
        rate = f" ({replies / c['started']:.0%})" if c["started"] else ""
        print(f"{camp:<28} {c['started']:>7} {c['replied']:>7}{rate} {c['interested']:>8} "
              f"{c['unsubscribed'] + c['do_not_call']:>7} {c['bounced']:>7} {c['failed']:>6}")
    return 0


def cmd_import(cfg, args) -> int:
    n = import_employers_from_jobs(Path(args.jobs), data_dir() / "contacts" / "employers_from_adverts.csv")
    print(f"added {n} employer inboxes → {data_dir() / 'contacts' / 'employers_from_adverts.csv'}")
    return 0


def cmd_run(cfg, args) -> int:
    if os.environ.get("OUTREACH_IMAP_HOST"):
        cmd_scan(cfg, argparse.Namespace(days=14))
    return cmd_send(cfg, args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m outreach", description="Compliant outreach automation.")
    parser.add_argument("--config", type=Path, help="default config/outreach.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    for name in ("plan", "send", "run"):
        p = sub.add_parser(name)
        p.add_argument("--campaign", help="only this campaign")
        p.add_argument("-v", "--verbose", action="store_true", help="print every message")
        if name != "plan":
            p.add_argument("--live", action="store_true", help="really send")
    p = sub.add_parser("scan-inbox")
    p.add_argument("--days", type=int, default=14)
    p = sub.add_parser("log-calls")
    p.add_argument("file")
    p = sub.add_parser("mark")
    p.add_argument("event", choices=["replied", "interested", "not_interested", "unsubscribed", "bounced",
                                     "do_not_call", "complaint"])
    p.add_argument("--email")
    p.add_argument("--phone")
    p.add_argument("--note")
    sub.add_parser("report")
    p = sub.add_parser("import-employers")
    p.add_argument("--jobs", default=str(ROOT / "data" / "jobs.json"))
    args = parser.parse_args(argv)
    if args.cmd == "mark" and not (args.email or args.phone):
        parser.error("mark needs --email or --phone")
    cfg = load_config(args.config)
    handler = {"check": cmd_check, "plan": cmd_plan, "send": cmd_send, "run": cmd_run, "scan-inbox": cmd_scan,
               "log-calls": cmd_log_calls, "mark": cmd_mark, "report": cmd_report, "import-employers": cmd_import}
    return handler[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
