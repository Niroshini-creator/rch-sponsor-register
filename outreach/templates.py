"""Message templates: loading, personalisation, compliance footer and content lint.

A template is a text file in templates/outreach/. Email templates start with a `Subject:` line and a blank line;
SMS, WhatsApp and call-script templates are body only. Placeholders use ${name} (see `fields`).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

from .config import TEMPLATE_DIR
from .contacts import Contact

# Claims that mislead job seekers (CPUTR / Consumer Protection Act 2007) or that the UK Employment Agencies
# Act 1973 s.6 and Ireland's Employment Agency Act 1971 restrict (charging work-seekers for finding work).
_BANNED = [
    (r"guarantee\w*\s+(?:a\s+|you\s+a\s+)?(?:job|placement|visa|sponsorship|offer|interview)", "do not guarantee jobs, interviews or visas"),
    (r"(?:job|placement|visa|sponsorship)\s+guarantee", "do not guarantee jobs or visas"),
    (r"100\s*%\s*(?:placement|success|job)", "do not promise placement rates"),
    (r"\b(?:visa|sponsorship)\s+(?:is\s+)?assured", "do not promise sponsorship"),
]
_CANDIDATE_FEES = re.compile(r"(?:registration|placement|joining|upfront|finder'?s?)\s+fee|pay\s+(?:us\s+)?to\s+(?:get|find)", re.I)

VISA_LABELS = {"psw": "Graduate visa (PSW)", "dependant": "Dependant visa", "stamp1g": "Stamp 1G",
               "stamp4": "Stamp 4", "skilled_worker": "Skilled Worker visa", "other": "your current visa", "": "your visa"}


@dataclass
class Template:
    name: str
    subject: str
    body: str


def load(name: str, folder: Path = TEMPLATE_DIR) -> Template:
    path = folder / f"{name}.txt"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    subject = ""
    if text.startswith("Subject:"):
        first, _, text = text.partition("\n")
        subject = first[len("Subject:"):].strip()
    return Template(name, subject, text.strip("\n"))


def fields(c: Contact, sender: dict) -> dict:
    return {
        "first_name": c.first_name or "there", "name": c.name, "company": c.company or "your team",
        "role": c.role, "city": c.city or ("the UK" if c.country == "GB" else "Ireland" if c.country == "IE" else "Europe"),
        "visa": VISA_LABELS.get(c.visa, c.visa), "target_role": c.target_role or "your target role",
        "notes": c.notes, **{f"sender_{k}": v for k, v in sender.items()},
    }


_PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def render(t: Template, c: Contact, sender: dict) -> tuple[str, str]:
    values = fields(c, sender)
    subject = string.Template(t.subject).safe_substitute(values)
    body = string.Template(t.body).safe_substitute(values)
    left = _PLACEHOLDER.findall(subject + body)
    if left:
        raise ValueError(f"template {t.name}: unknown placeholder(s) {sorted(set(left))}")
    return subject, body


def footer(channel: str, c: Contact, sender: dict, basis: str) -> str:
    """Identity + opt-out on every message (PECR reg. 23, S.I. 336/2011 reg. 13(12))."""
    if channel in ("sms", "whatsapp"):
        return f"{sender['company']}. Reply STOP to opt out."
    if channel == "call":
        return ""
    if c.audience == "employer":
        why = "we believe our candidate placement service is relevant to your recruitment"
    elif basis.startswith("soft opt-in"):
        why = "you contacted us about our job search services"
    else:
        why = "you asked us to keep you updated about job opportunities"
    unsub = sender.get("unsubscribe_email") or sender["email"]
    return (f"--\n{sender['name']}, {sender['company']}, {sender['address']}\n"
            f"You received this because {why}. Not interested? Reply \"unsubscribe\" or email {unsub} "
            "and we will not contact you again.")


def lint(t: Template, audience: str, channel: str) -> list[str]:
    problems = []
    text = f"{t.subject}\n{t.body}"
    for pattern, why in _BANNED:
        if re.search(pattern, text, re.I):
            problems.append(f"{t.name}: {why}")
    if audience == "candidate" and _CANDIDATE_FEES.search(text):
        problems.append(f"{t.name}: do not ask candidates for a fee to find them work "
                        "(Employment Agencies Act 1973 s.6 / Employment Agency Act 1971)")
    if channel == "email" and not t.subject:
        problems.append(f"{t.name}: email templates need a 'Subject:' first line")
    if channel in ("sms", "whatsapp") and len(t.body) > 450:
        problems.append(f"{t.name}: {len(t.body)} characters is more than 3 SMS segments; shorten it")
    known = set(fields(Contact(id="x", audience=audience), {}).keys())
    for name in set(_PLACEHOLDER.findall(text)):
        if name not in known and not name.startswith("sender_"):
            problems.append(f"{t.name}: unknown placeholder ${{{name}}}")
    return problems
