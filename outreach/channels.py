"""Delivery channels: SMTP email, Twilio SMS and WhatsApp, and a dry-run outbox.

Credentials come from environment variables only (never commit them):

  email     OUTREACH_SMTP_HOST, OUTREACH_SMTP_PORT (587), OUTREACH_SMTP_USER, OUTREACH_SMTP_PASSWORD
  sms       TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_SMS_FROM (e.g. +447… or an alphanumeric sender id)
  whatsapp  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM (your WhatsApp Business number)

WhatsApp: a business may only open a conversation with a template approved by Meta. Give the step a
"content_sid" (Twilio Content API id) and "content_variables" (placeholder names, in order); the text template
is then only used for the preview and the ledger.
"""

from __future__ import annotations

import base64
import json
import os
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from .contacts import Contact
from .templates import fields


class SendError(RuntimeError):
    pass


class DryRunSender:
    """Writes what would have been sent to outreach_data/outbox.jsonl instead of sending it."""

    def __init__(self, path: Path):
        self.path = path

    def send(self, channel: str, c: Contact, subject: str, body: str, sender: dict, step: dict | None = None) -> str:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"channel": channel, "to": c.address(channel), "subject": subject, "body": body},
                                ensure_ascii=False) + "\n")
        return "dry-run"


class SmtpSender:
    def __init__(self):
        self.host = os.environ.get("OUTREACH_SMTP_HOST")
        self.port = int(os.environ.get("OUTREACH_SMTP_PORT", "587"))
        self.user = os.environ.get("OUTREACH_SMTP_USER")
        self.password = os.environ.get("OUTREACH_SMTP_PASSWORD")
        if not (self.host and self.user and self.password):
            raise SendError("set OUTREACH_SMTP_HOST, OUTREACH_SMTP_USER and OUTREACH_SMTP_PASSWORD to send email")
        self._conn: smtplib.SMTP | None = None

    def _connection(self) -> smtplib.SMTP:
        if self._conn is None:
            conn = smtplib.SMTP_SSL(self.host, self.port, timeout=30) if self.port == 465 else smtplib.SMTP(self.host, self.port, timeout=30)
            if self.port != 465:
                conn.starttls()
            conn.login(self.user, self.password)
            self._conn = conn
        return self._conn

    def send(self, channel: str, c: Contact, subject: str, body: str, sender: dict, step: dict | None = None) -> str:
        msg = EmailMessage()
        msg["From"] = formataddr((f"{sender['name']} | {sender['company']}", sender["email"]))
        msg["To"] = formataddr((c.name, c.email)) if c.name else c.email
        msg["Subject"] = subject
        msg["Reply-To"] = sender.get("reply_to") or sender["email"]
        unsub = sender.get("unsubscribe_email") or sender["email"]
        msg["List-Unsubscribe"] = f"<mailto:{unsub}?subject=unsubscribe>"
        msg["Message-ID"] = make_msgid(domain=sender["email"].split("@", 1)[1])
        msg.set_content(body)
        try:
            self._connection().send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            self._conn = None
            raise SendError(f"SMTP: {exc}") from exc
        return msg["Message-ID"]


class TwilioSender:
    def __init__(self, kind: str):
        self.kind = kind
        self.sid = os.environ.get("TWILIO_ACCOUNT_SID")
        self.token = os.environ.get("TWILIO_AUTH_TOKEN")
        self.sender = os.environ.get("TWILIO_WHATSAPP_FROM" if kind == "whatsapp" else "TWILIO_SMS_FROM")
        if not (self.sid and self.token and self.sender):
            raise SendError(f"set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and "
                            f"{'TWILIO_WHATSAPP_FROM' if kind == 'whatsapp' else 'TWILIO_SMS_FROM'} to send {kind}")

    def send(self, channel: str, c: Contact, subject: str, body: str, sender: dict, step: dict | None = None) -> str:
        prefix = "whatsapp:" if self.kind == "whatsapp" else ""
        params = {"From": prefix + self.sender, "To": prefix + c.phone, "Body": body}
        if step and step.get("content_sid"):
            # WhatsApp only lets a business start a conversation with a Meta-approved template.
            values = fields(c, sender)
            params = {"From": params["From"], "To": params["To"], "ContentSid": step["content_sid"],
                      "ContentVariables": json.dumps({str(i): values.get(name, "")
                                                      for i, name in enumerate(step.get("content_variables", []), 1)})}
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json", data=data)
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{self.sid}:{self.token}".encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())["sid"]
        except urllib.error.HTTPError as exc:
            raise SendError(f"Twilio {exc.code}: {exc.read().decode(errors='replace')[:300]}") from exc
        except OSError as exc:
            raise SendError(f"Twilio: {exc}") from exc


def make_senders(live: bool, outbox: Path, channels: set[str]) -> dict:
    if not live:
        dry = DryRunSender(outbox)
        return {ch: dry for ch in channels}
    senders = {}
    if "email" in channels:
        senders["email"] = SmtpSender()
    for kind in ("sms", "whatsapp"):
        if kind in channels:
            senders[kind] = TwilioSender(kind)
    return senders
