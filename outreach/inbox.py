"""Read the sending mailbox over IMAP and record replies, opt-outs and bounces, so sequences stop by themselves.

  OUTREACH_IMAP_HOST, OUTREACH_IMAP_USER, OUTREACH_IMAP_PASSWORD (defaults to the SMTP user/password),
  OUTREACH_IMAP_FOLDER (INBOX)

Messages are read with BODY.PEEK, so they stay unread for you to answer.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import date, timedelta
from email.message import Message
from email.utils import parseaddr

from .contacts import Contact
from .ledger import Ledger, Suppression

_UNSUB = re.compile(r"\b(unsubscribe|remove me|opt[\s-]?out|stop (?:emailing|contacting)|do not (?:contact|email)|"
                    r"don'?t (?:contact|email)|take me off)\b", re.I)
_BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster|mail delivery (?:system|subsystem)", re.I)
_AUTO = re.compile(r"out of (?:the )?office|automatic reply|auto(?:matic)?[- ]?reply|on (?:annual )?leave", re.I)


def _text(msg: Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    out = []
    for part in parts:
        if part.get_content_type() in ("text/plain", "message/delivery-status"):
            payload = part.get_payload(decode=True)
            if payload:
                out.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
            elif part.get_content_type() == "message/delivery-status":
                out.append(str(part))
    return "\n".join(out)


def classify(msg: Message, by_email: dict[str, Contact]) -> tuple[Contact | None, str]:
    """→ (contact, event) where event is replied | unsubscribed | bounced | auto_reply | ''."""
    sender = parseaddr(msg.get("From", ""))[1].lower()
    subject = msg.get("Subject", "")
    body = _text(msg)
    if _BOUNCE_FROM.search(msg.get("From", "")) or msg.get_content_type() == "multipart/report":
        for addr in re.findall(r"[\w.%+'-]+@[\w.-]+\.\w+", body):
            if addr.lower() in by_email:
                return by_email[addr.lower()], "bounced"
        return None, ""
    contact = by_email.get(sender)
    if not contact:
        return None, ""
    # only the new text, not the quoted original that contains our own footer
    fresh = re.split(r"\n\s*(?:On .+wrote:|-----Original Message-----|From: )|\n>", body, maxsplit=1)[0]
    if _UNSUB.search(subject) or _UNSUB.search(fresh):
        return contact, "unsubscribed"
    if _AUTO.search(subject) or msg.get("Auto-Submitted", "no").lower() != "no":
        return contact, "auto_reply"
    return contact, "replied"


def scan(contacts: list[Contact], ledger: Ledger, suppression: Suppression, days: int = 14) -> dict:
    host = os.environ.get("OUTREACH_IMAP_HOST")
    user = os.environ.get("OUTREACH_IMAP_USER") or os.environ.get("OUTREACH_SMTP_USER")
    password = os.environ.get("OUTREACH_IMAP_PASSWORD") or os.environ.get("OUTREACH_SMTP_PASSWORD")
    if not (host and user and password):
        raise RuntimeError("set OUTREACH_IMAP_HOST, OUTREACH_IMAP_USER and OUTREACH_IMAP_PASSWORD to scan replies")
    by_email = {c.email: c for c in contacts if c.email}
    stats = {"replied": 0, "unsubscribed": 0, "bounced": 0, "auto_reply": 0}
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select(os.environ.get("OUTREACH_IMAP_FOLDER", "INBOX"), readonly=True)
        _, data = imap.search(None, f'(SINCE "{since}")')
        for num in data[0].split():
            _, parts = imap.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parts[0][1])
            msg_id = msg.get("Message-ID", f"imap-{num.decode()}")
            if ledger.seen("message_id", msg_id):
                continue
            contact, event = classify(msg, by_email)
            if not contact or not event:
                continue
            if event != "auto_reply":
                ledger.append(event, contact.id, channel="email", message_id=msg_id, subject=msg.get("Subject", "")[:200])
            if event in ("unsubscribed", "bounced"):
                suppression.add(contact.email, "email", event)
            stats[event] += 1
    return stats
