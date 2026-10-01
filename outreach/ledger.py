"""Append-only event log (who was contacted, when, how it went) and the suppression list.

The ledger is your audit trail: every send, failure, reply, opt-out and call outcome is one JSON line in
outreach_data/ledger.jsonl. Sequences read it to decide the next step; nothing is ever rewritten.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path

# Events that end every sequence for the contact: a human takes over or the person said no.
STOP_EVENTS = {"replied", "interested", "not_interested", "unsubscribed", "bounced", "do_not_call", "complaint"}
# Events that count as a completed sequence step.
STEP_EVENTS = {"sent", "call_queued"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.events: list[dict] = []
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                self.events = [json.loads(line) for line in fh if line.strip()]

    def append(self, event: str, contact_id: str = "", **fields) -> dict:
        record = {"ts": fields.pop("ts", None) or utcnow().isoformat(timespec="seconds"), "event": event,
                  "contact_id": contact_id, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.events.append(record)
        return record

    def for_contact(self, contact_id: str) -> list[dict]:
        return [e for e in self.events if e.get("contact_id") == contact_id]

    def steps_done(self, contact_id: str, campaign: str) -> list[dict]:
        return [e for e in self.for_contact(contact_id) if e.get("campaign") == campaign and e["event"] in STEP_EVENTS]

    def stop_reason(self, contact_id: str) -> str:
        for e in self.for_contact(contact_id):
            if e["event"] in STOP_EVENTS:
                return e["event"]
        return ""

    def last_touch(self, contact_id: str) -> datetime | None:
        times = [datetime.fromisoformat(e["ts"]) for e in self.for_contact(contact_id) if e["event"] in STEP_EVENTS]
        return max(times) if times else None

    def count_on(self, day: date, channel: str) -> int:
        return sum(1 for e in self.events if e["event"] in STEP_EVENTS and e.get("channel") == channel
                   and datetime.fromisoformat(e["ts"]).date() == day)

    def seen(self, key: str, value: str) -> bool:
        return any(e.get(key) == value for e in self.events)


class Suppression:
    """Addresses and numbers that must never be contacted again (per channel, or '*' for all).
    Kept forever, even after you delete the contact, so a re-imported list can't undo an opt-out."""

    HEADER = ["value", "channel", "reason", "added_on"]

    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[tuple[str, str], dict] = {}
        if path.exists():
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    self.rows[(row["value"].strip().lower(), row["channel"] or "*")] = row

    def blocks(self, value: str, channel: str) -> str:
        value = (value or "").strip().lower()
        if not value:
            return ""
        domain = value.split("@", 1)[1] if "@" in value else None
        for key in ((value, channel), (value, "*"), (f"@{domain}", "*"), (f"@{domain}", channel)):
            if key in self.rows:
                return self.rows[key]["reason"]
        return ""

    def add(self, value: str, channel: str = "*", reason: str = "opt-out") -> None:
        value = value.strip().lower()
        if not value or (value, channel) in self.rows:
            return
        row = {"value": value, "channel": channel, "reason": reason, "added_on": date.today().isoformat()}
        new_file = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.HEADER)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        self.rows[(value, channel)] = row
