"""Sequencing: decide who gets which step of which campaign today, then send it.

A campaign (config/outreach.json → campaigns) targets one audience, optionally filtered by country / visa / any
contact field, and runs a list of steps: {"day": 0, "channel": "email", "template": "employer_intro"}. `day` counts
from the first step. A contact gets at most one touch per run, never two touches closer than
limits.min_hours_between_touches, and every sequence stops for good on a reply, opt-out, bounce or call outcome.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import templates
from .compliance import Decision, can_contact
from .contacts import Contact
from .ledger import Ledger, Suppression

TIMEZONES = {"GB": "Europe/London", "IE": "Europe/Dublin", "PT": "Europe/Lisbon", "FI": "Europe/Helsinki",
             "GR": "Europe/Athens", "RO": "Europe/Bucharest", "BG": "Europe/Sofia", "EE": "Europe/Tallinn",
             "LV": "Europe/Riga", "LT": "Europe/Vilnius", "CY": "Asia/Nicosia"}


@dataclass
class Action:
    contact: Contact
    campaign: str
    step_index: int
    step: dict
    subject: str
    body: str
    decision: Decision

    @property
    def channel(self) -> str:
        return self.step["channel"]


@dataclass
class Skip:
    contact: Contact
    campaign: str
    step_index: int
    reason: str


def matches(c: Contact, campaign: dict) -> bool:
    if c.audience != campaign["audience"]:
        return False
    for key, allowed in (campaign.get("filter") or {}).items():
        value = getattr(c, key, "")
        if [a.lower() for a in allowed] and str(value).lower() not in [a.lower() for a in allowed]:
            return False
    return True


def within_hours(c: Contact, audience: str, now: datetime, cfg: dict) -> bool:
    window = cfg.get("sending_hours", {}).get(audience)
    if not window:
        return True
    local = now.astimezone(ZoneInfo(TIMEZONES.get(c.country, "Europe/Paris")))
    start, end = (datetime.strptime(window[k], "%H:%M").time() for k in ("start", "end"))
    return local.weekday() in window.get("days", range(7)) and start <= local.time() <= end


def plan(contacts: list[Contact], cfg: dict, ledger: Ledger, suppression: Suppression, now: datetime,
         only: str | None = None) -> tuple[list[Action], list[Skip]]:
    actions: list[Action] = []
    skips: list[Skip] = []
    touched: set[str] = set()
    limits = cfg.get("limits", {})
    used = {ch: ledger.count_on(now.date(), ch) for ch in ("email", "sms", "whatsapp", "call")}
    min_gap = timedelta(hours=limits.get("min_hours_between_touches", 48))
    rules = cfg.get("compliance", {})

    for name, campaign in cfg.get("campaigns", {}).items():
        if (only and name != only) or not campaign.get("active", True):
            continue
        steps = campaign["steps"]
        for c in contacts:
            if c.id in touched or not matches(c, campaign):
                continue
            if ledger.stop_reason(c.id):
                continue
            done = ledger.steps_done(c.id, name)
            idx = len(done)
            if idx >= len(steps):
                continue
            step = steps[idx]
            if idx and now < datetime.fromisoformat(done[0]["ts"]) + timedelta(days=step["day"]):
                continue
            last = ledger.last_touch(c.id)
            if last and now - last < min_gap:
                skips.append(Skip(c, name, idx, "touched recently"))
                continue
            channel = step["channel"]
            decision = can_contact(c, channel, now.date(), suppression, rules)
            if not decision.ok:
                skips.append(Skip(c, name, idx, decision.reason))
                continue
            if channel != "call" and not within_hours(c, c.audience, now, cfg):
                skips.append(Skip(c, name, idx, "outside sending hours"))
                continue
            if used[channel] >= limits.get(f"{channel}_per_day", 50):
                skips.append(Skip(c, name, idx, f"daily {channel} limit reached"))
                continue
            tpl = templates.load(step["template"])
            subject, body = templates.render(tpl, c, cfg["sender"])
            tail = templates.footer(channel, c, cfg["sender"], decision.basis)
            actions.append(Action(c, name, idx, step, subject, f"{body}\n\n{tail}".strip(), decision))
            used[channel] += 1
            touched.add(c.id)
    return actions, skips


def execute(actions: list[Action], senders: dict, ledger: Ledger, cfg: dict, live: bool, sleep=time.sleep,
            now: datetime | None = None) -> dict:
    """Send every non-call action and log it. Call actions are only logged as queued; the caller
    writes them to the day's call sheet."""
    stats = {"sent": 0, "failed": 0, "call_queued": 0}
    pause = cfg.get("limits", {}).get("seconds_between_messages", 30) if live else 0
    for a in actions:
        ts = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        base = dict(ts=ts, campaign=a.campaign, step=a.step_index, channel=a.channel, template=a.step["template"],
                    basis=a.decision.basis, to=a.contact.address(a.channel), live=live)
        if a.channel == "call":
            if live:
                ledger.append("call_queued", a.contact.id, **base)
            stats["call_queued"] += 1
            continue
        try:
            ref = senders[a.channel].send(a.channel, a.contact, a.subject, a.body, cfg["sender"], a.step)
        except Exception as exc:  # noqa: BLE001 – one failure must not stop the batch
            ledger.append("failed", a.contact.id, error=str(exc)[:300], **base)
            stats["failed"] += 1
            continue
        if live:
            ledger.append("sent", a.contact.id, ref=ref, subject=a.subject, **base)
        stats["sent"] += 1
        if pause:
            sleep(pause)
    return stats
