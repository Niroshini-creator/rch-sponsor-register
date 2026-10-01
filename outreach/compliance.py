"""The compliance gate. Every message and every call-sheet entry has to pass `can_contact` first.

Rules encoded (summary; see docs/OUTREACH.md for the reasoning and sources):

Employers (B2B)
  email     Allowed without consent only to a *business* address (not Gmail/Outlook/etc., which count as an
            individual subscriber), in a country listed in compliance.b2b_cold_email_countries (default GB, IE:
            PECR reg. 22 corporate subscribers; Irish S.I. 336/2011 reg. 13). Where you got the address
            (`source`) must be recorded. Elsewhere (e.g. Germany, Austria) prior consent is needed even for B2B.
  sms/whatsapp  Consent only.
  call      Consent, or a number screened against CTPS (UK) / the NDD opt-out register (IE) within
            compliance.screen_max_age_days and found clear. Irish mobiles need consent.

Candidates (individuals)
  email/sms/whatsapp  Consent for that channel (with date and source), or soft opt-in: they enquired about or
            used your service within compliance.soft_opt_in_months (and you offered an opt-out then).
            Scraped or bought lists of individuals are never allowed.
  call      Consent, or (UK landline/mobile) a clear TPS screen within the max age. Irish mobiles need consent.

Everyone: nothing goes to an address or number on the suppression list. Automated (recorded/robo) calls are not
supported at all: they need explicit prior consent and are best avoided.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .contacts import Contact, is_mobile
from .ledger import Suppression

WEBMAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "hotmail.com", "hotmail.co.uk",
           "outlook.com", "live.com", "live.co.uk", "msn.com", "icloud.com", "me.com", "aol.com", "proton.me",
           "protonmail.com", "gmx.com", "gmx.de", "gmx.net", "mail.com", "yandex.com", "zoho.com", "eircom.net",
           "btinternet.com", "sky.com", "virginmedia.com", "talktalk.net", "web.de", "free.fr", "orange.fr"}


@dataclass
class Decision:
    ok: bool
    basis: str = ""
    reason: str = ""


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def _has_consent(c: Contact, channel: str) -> bool:
    return channel in c.consent and c.consent_date is not None and bool(c.consent_source)


def _soft_opt_in(c: Contact, today: date, rules: dict) -> bool:
    months = rules.get("soft_opt_in_months", {}).get(c.country, rules.get("soft_opt_in_months", {}).get("default", 12))
    return (c.relationship in ("enquired", "client") and c.relationship_date is not None
            and _months_between(c.relationship_date, today) <= months)


def _screen_clear(c: Contact, today: date, rules: dict) -> bool:
    return (c.tps_status == "clear" and c.tps_checked_on is not None
            and (today - c.tps_checked_on).days <= rules.get("screen_max_age_days", 28))


def can_contact(c: Contact, channel: str, today: date, suppression: Suppression, rules: dict) -> Decision:
    if c.errors:
        return Decision(False, reason="contact row has errors: " + "; ".join(c.errors))
    address = c.address(channel)
    if not address:
        return Decision(False, reason=f"no {'email' if channel == 'email' else 'phone number'}")
    if why := suppression.blocks(address, channel):
        return Decision(False, reason=f"suppressed ({why})")
    if c.visa_expiry and c.visa_expiry < today:
        return Decision(False, reason="visa expired: do not contact about UK/IE roles")

    if _has_consent(c, channel):
        return Decision(True, basis=f"consent ({c.consent_source}, {c.consent_date})")

    if c.audience == "employer":
        if channel == "email":
            domain = c.email.split("@", 1)[1]
            if domain in WEBMAIL:
                return Decision(False, reason=f"{domain} is a personal mailbox: needs consent")
            if c.country not in rules.get("b2b_cold_email_countries", ["GB", "IE"]):
                return Decision(False, reason=f"B2B cold email to {c.country or 'unknown country'} needs consent "
                                              "(add the country to b2b_cold_email_countries only after checking local law)")
            if not c.source:
                return Decision(False, reason="record where you got this address (source column)")
            return Decision(True, basis=f"legitimate interest, corporate subscriber ({c.source})")
        if channel == "call":
            return _call_decision(c, today, rules, register="CTPS" if c.country == "GB" else "NDD")
        return Decision(False, reason=f"{channel} marketing needs consent")

    # candidates are individuals
    if channel == "call":
        return _call_decision(c, today, rules, register="TPS" if c.country == "GB" else "NDD")
    if _soft_opt_in(c, today, rules):
        return Decision(True, basis=f"soft opt-in ({c.relationship} on {c.relationship_date})")
    return Decision(False, reason=f"no {channel} consent: candidates must opt in (see docs/OUTREACH.md)")


def _call_decision(c: Contact, today: date, rules: dict, register: str) -> Decision:
    if c.country == "IE" and is_mobile(c.phone):
        return Decision(False, reason="Irish mobile: marketing calls need prior consent")
    if c.country not in ("GB", "IE"):
        return Decision(False, reason=f"calls to {c.country or 'unknown country'} need consent")
    if c.tps_status == "registered":
        return Decision(False, reason=f"registered on {register}")
    if not _screen_clear(c, today, rules):
        return Decision(False, reason=f"screen against {register} first (tps_status / tps_checked_on, max "
                                      f"{rules.get('screen_max_age_days', 28)} days old)")
    return Decision(True, basis=f"{register} screened clear on {c.tps_checked_on}")
