"""Cold-call sheets. Calls are made by a person, never dialled automatically: the framework picks who to call
today (screened against TPS/CTPS/NDD), writes a sheet with the script, and imports the outcomes you fill in."""

from __future__ import annotations

import csv
from pathlib import Path

from .engine import Action
from .ledger import Ledger, Suppression

SHEET_FIELDS = ["contact_id", "name", "company", "phone", "country", "campaign", "basis", "script", "outcome", "notes"]
OUTCOMES = {
    "no_answer": None, "voicemail": None, "callback": None,
    "interested": "interested", "not_interested": "not_interested",
    "do_not_call": "do_not_call", "wrong_number": "do_not_call",
}


def write_sheet(actions: list[Action], path: Path) -> int:
    calls = [a for a in actions if a.channel == "call"]
    if not calls:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_FIELDS)
        writer.writeheader()
        for a in calls:
            writer.writerow({"contact_id": a.contact.id, "name": a.contact.name, "company": a.contact.company,
                             "phone": a.contact.phone, "country": a.contact.country, "campaign": a.campaign,
                             "basis": a.decision.basis, "script": a.body, "outcome": "", "notes": ""})
    return len(calls)


def import_outcomes(path: Path, ledger: Ledger, suppression: Suppression) -> tuple[int, list[str]]:
    """Read a filled-in call sheet. Valid outcomes: no_answer, voicemail, callback, interested,
    not_interested, do_not_call, wrong_number. 'do_not_call' also suppresses the number for calls;
    'wrong_number' suppresses it everywhere."""
    logged, problems = 0, []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            outcome = (row.get("outcome") or "").strip().lower().replace(" ", "_")
            if not outcome:
                continue
            if outcome not in OUTCOMES:
                problems.append(f"line {line}: unknown outcome {outcome!r} (use {', '.join(OUTCOMES)})")
                continue
            sheet_key = f"{path.name}:{line}"
            if ledger.seen("sheet_row", sheet_key):
                continue
            ledger.append(OUTCOMES[outcome] or "call_outcome", row["contact_id"], channel="call", outcome=outcome,
                          campaign=row.get("campaign", ""), notes=row.get("notes", ""), sheet_row=sheet_key)
            if outcome == "do_not_call":
                suppression.add(row["phone"], "call", "asked not to be called")
            elif outcome == "wrong_number":
                suppression.add(row["phone"], "*", "wrong number")
            logged += 1
    return logged, problems
