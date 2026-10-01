import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from outreach import calls, engine, inbox, templates
from outreach.compliance import can_contact
from outreach.config import CONFIG_PATH
from outreach.contacts import FIELDS, from_row, import_employers_from_jobs, load_contacts, normalise_phone
from outreach.ledger import Ledger, Suppression

TODAY = date(2026, 10, 1)
# A Tuesday, 10:00 in London: inside both audiences' sending hours.
NOW = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
RULES = {"b2b_cold_email_countries": ["GB", "IE"], "screen_max_age_days": 28,
         "soft_opt_in_months": {"GB": 24, "IE": 12, "default": 12}}


def employer(**kw):
    row = dict(audience="employer", name="Jane Doe", company="Acme Ltd", email="jane@acme.co.uk",
               phone="020 7946 0000", country="GB", source="https://acme.co.uk/careers")
    row.update(kw)
    return from_row(row)


def candidate(**kw):
    row = dict(audience="candidate", name="Priya Shah", email="priya@example.net", phone="07700 900123",
               country="GB", visa="psw", consent_channels="email;whatsapp", consent_date="2026-09-20",
               consent_source="website form")
    row.update(kw)
    return from_row(row)


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, channel, c, subject, body, sender, step=None):
        self.sent.append((channel, c.address(channel), subject, body))
        return f"ref-{len(self.sent)}"


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ledger = Ledger(self.dir / "ledger.jsonl")
        self.suppression = Suppression(self.dir / "suppression.csv")

    def tearDown(self):
        self.tmp.cleanup()


class ContactTests(unittest.TestCase):
    def test_phone_normalisation(self):
        self.assertEqual(normalise_phone("07700 900123", "GB"), "+447700900123")
        self.assertEqual(normalise_phone("083 555 0199", "IE"), "+353835550199")
        self.assertEqual(normalise_phone("0044 20 7946 0000", "NL"), "+442079460000")
        with self.assertRaises(ValueError):
            normalise_phone("06 1234 5678", "NL")

    def test_row_errors_are_collected(self):
        c = from_row({"audience": "someone", "email": "not-an-email", "consent_channels": "email;fax"})
        self.assertEqual(len(c.errors), 3)

    def test_first_name_skips_titles(self):
        self.assertEqual(employer(name="Dr Jane Doe").first_name, "Jane")

    def test_load_contacts_dedupes_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            with path.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS)
                w.writeheader()
                w.writerow({"id": "x", "audience": "employer", "email": "a@acme.co.uk"})
                w.writerow({"id": "x", "audience": "employer", "email": "b@acme.co.uk"})
            contacts = load_contacts(Path(tmp))
            self.assertEqual(len(contacts), 1)
            self.assertTrue(any("duplicate id" in e for e in contacts[0].errors))

    def test_import_employers_from_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs = Path(tmp) / "jobs.json"
            jobs.write_text(json.dumps({"jobs": [
                {"company": "Shell", "country": "GB", "location": "London", "url": "https://x/1", "title": "Analyst",
                 "contacts": [{"email": "careers@shell.com", "provenance": "advert"}]},
                {"company": "Shell", "country": "GB", "location": "London", "url": "https://x/2", "title": "Engineer",
                 "contacts": [{"email": "careers@shell.com", "provenance": "advert"}]}]}))
            out = Path(tmp) / "contacts" / "emp.csv"
            self.assertEqual(import_employers_from_jobs(jobs, out), 1)
            self.assertEqual(import_employers_from_jobs(jobs, out), 0)
            (c,) = load_contacts(out.parent)
            self.assertEqual((c.email, c.audience, c.source), ("careers@shell.com", "employer", "advert: https://x/1"))


class ComplianceTests(Workspace):
    def check(self, c, channel):
        return can_contact(c, channel, TODAY, self.suppression, RULES)

    def test_b2b_email_to_business_address_in_gb_and_ie(self):
        self.assertTrue(self.check(employer(), "email").ok)
        self.assertTrue(self.check(employer(country="IE", email="hr@acme.ie"), "email").ok)

    def test_b2b_email_blocked_for_webmail_unlisted_country_or_unknown_source(self):
        self.assertIn("personal mailbox", self.check(employer(email="jane@gmail.com"), "email").reason)
        self.assertIn("needs consent", self.check(employer(country="DE", email="hr@acme.de", phone=""), "email").reason)
        self.assertIn("source", self.check(employer(source=""), "email").reason)

    def test_b2b_sms_needs_consent(self):
        self.assertFalse(self.check(employer(), "sms").ok)

    def test_candidate_needs_consent_per_channel(self):
        self.assertTrue(self.check(candidate(), "email").ok)
        self.assertTrue(self.check(candidate(), "whatsapp").ok)
        self.assertIn("no sms consent", self.check(candidate(), "sms").reason)
        self.assertFalse(self.check(candidate(consent_channels="", consent_date="", consent_source=""), "email").ok)
        self.assertFalse(self.check(candidate(consent_source=""), "email").ok, "consent needs a recorded source")

    def test_soft_opt_in_expires(self):
        base = dict(consent_channels="", consent_date="", consent_source="", relationship="enquired")
        self.assertTrue(self.check(candidate(relationship_date="2025-06-01", **base), "email").ok)
        self.assertFalse(self.check(candidate(country="IE", phone="", relationship_date="2025-06-01", **base), "email").ok)

    def test_calls_need_fresh_clear_screen(self):
        self.assertIn("screen against CTPS", self.check(employer(), "call").reason)
        self.assertTrue(self.check(employer(tps_status="clear", tps_checked_on="2026-09-20"), "call").ok)
        self.assertFalse(self.check(employer(tps_status="clear", tps_checked_on="2026-08-01"), "call").ok)
        self.assertIn("registered on CTPS", self.check(employer(tps_status="registered"), "call").reason)

    def test_irish_mobiles_need_consent_to_call(self):
        c = candidate(country="IE", phone="083 555 0199", consent_channels="email",
                      tps_status="clear", tps_checked_on="2026-09-30")
        self.assertIn("Irish mobile", self.check(c, "call").reason)

    def test_suppression_wins_over_consent(self):
        self.suppression.add("priya@example.net", "email", "unsubscribed")
        self.assertIn("suppressed", self.check(candidate(), "email").reason)
        self.assertTrue(self.check(candidate(), "whatsapp").ok)
        self.suppression.add("@acme.co.uk", "*", "company asked")
        self.assertFalse(self.check(employer(), "email").ok)
        self.assertTrue(Suppression(self.dir / "suppression.csv").blocks("jane@acme.co.uk", "email"), "persisted")

    def test_expired_visa_is_not_contacted(self):
        self.assertFalse(self.check(candidate(visa_expiry="2026-01-01"), "email").ok)


class TemplateTests(unittest.TestCase):
    def test_shipped_templates_render_and_lint_clean(self):
        cfg = json.loads(CONFIG_PATH.read_text())
        for name, camp in cfg["campaigns"].items():
            for step in camp["steps"]:
                tpl = templates.load(step["template"])
                self.assertEqual(templates.lint(tpl, camp["audience"], step["channel"]), [], step["template"])
                c = employer() if camp["audience"] == "employer" else candidate()
                templates.render(tpl, c, cfg["sender"])

    def test_lint_catches_guarantees_and_candidate_fees(self):
        tpl = templates.Template("t", "Guaranteed job offer", "We guarantee you a job. Registration fee £99. ${foo}")
        problems = templates.lint(tpl, "candidate", "email")
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("fee" in p for p in problems))


def _cfg(steps, audience="candidate", **campaign):
    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["campaigns"] = {"c1": {"audience": audience, "steps": steps, **campaign}}
    cfg["limits"]["min_hours_between_touches"] = 48
    return cfg


class FooterTests(unittest.TestCase):
    def test_footer_shows_registration_and_privacy_notice(self):
        sender = {"name": "Asha", "company": "Acme Pvt Ltd", "registration": "Registered in India, CIN U1",
                  "address": "Pune, India", "email": "hi@acme.com", "privacy_url": "https://acme.com/privacy"}
        text = templates.footer("email", employer(), sender, "legitimate interest")
        self.assertIn("Acme Pvt Ltd, Registered in India, CIN U1, Pune, India", text)
        self.assertIn("https://acme.com/privacy", text)
        self.assertIn("contacted us", templates.footer("email", candidate(), sender, "soft opt-in (enquired)"))


class EngineTests(Workspace):
    STEPS = [{"day": 0, "channel": "email", "template": "candidate_uk_intro"},
             {"day": 3, "channel": "email", "template": "candidate_followup"}]

    def run_day(self, cfg, contacts, now):
        actions, skips = engine.plan(contacts, cfg, self.ledger, self.suppression, now)
        sender = FakeSender()
        engine.execute(actions, {"email": sender, "sms": sender, "whatsapp": sender}, self.ledger, cfg, live=True,
                       sleep=lambda s: None, now=now)
        return sender.sent, skips

    def test_sequence_waits_for_step_day_then_finishes(self):
        cfg, c = _cfg(self.STEPS), candidate()
        sent, _ = self.run_day(cfg, [c], NOW)
        self.assertEqual(len(sent), 1)
        self.assertIn("unsubscribe", sent[0][3])
        self.assertEqual(self.run_day(cfg, [c], NOW + timedelta(days=2))[0], [])
        self.assertEqual(len(self.run_day(cfg, [c], NOW + timedelta(days=3))[0]), 1)
        self.assertEqual(self.run_day(cfg, [c], NOW + timedelta(days=10))[0], [])

    def test_reply_stops_every_campaign(self):
        cfg, c = _cfg(self.STEPS), candidate()
        self.run_day(cfg, [c], NOW)
        self.ledger.append("replied", c.id, channel="email")
        self.assertEqual(self.run_day(cfg, [c], NOW + timedelta(days=7))[0], [])

    def test_filters_hours_and_daily_cap(self):
        cfg = _cfg(self.STEPS, filter={"country": ["GB"], "visa": ["psw"]})
        cfg["limits"]["email_per_day"] = 1
        people = [candidate(), candidate(email="b@example.net", phone=""), candidate(visa="stamp1g", email="c@example.net", phone="")]
        sent, skips = self.run_day(cfg, people, NOW)
        self.assertEqual(len(sent), 1)
        self.assertEqual([s.reason for s in skips], ["daily email limit reached"])
        sunday_night = datetime(2026, 10, 4, 22, 0, tzinfo=timezone.utc)
        _, skips = self.run_day(cfg, [candidate(email="d@example.net", phone="")], sunday_night)
        self.assertEqual(skips[0].reason, "outside sending hours")

    def test_dry_run_does_not_advance_the_sequence(self):
        cfg, c = _cfg(self.STEPS), candidate()
        actions, _ = engine.plan([c], cfg, self.ledger, self.suppression, NOW)
        engine.execute(actions, {"email": FakeSender()}, self.ledger, cfg, live=False)
        self.assertEqual(self.ledger.steps_done(c.id, "c1"), [])

    def test_failed_send_is_retried_next_run(self):
        class Broken:
            def send(self, *a, **k):
                raise RuntimeError("smtp down")
        cfg, c = _cfg(self.STEPS), candidate()
        actions, _ = engine.plan([c], cfg, self.ledger, self.suppression, NOW)
        stats = engine.execute(actions, {"email": Broken()}, self.ledger, cfg, live=True, sleep=lambda s: None, now=NOW)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(len(self.run_day(cfg, [c], NOW)[0]), 1)

    def test_call_steps_go_to_sheet_and_outcomes_stop_sequence(self):
        steps = [{"day": 0, "channel": "call", "template": "call_employer"},
                 {"day": 3, "channel": "email", "template": "employer_followup"}]
        cfg = _cfg(steps, audience="employer")
        c = employer(tps_status="clear", tps_checked_on="2026-09-25")
        actions, _ = engine.plan([c], cfg, self.ledger, self.suppression, NOW)
        engine.execute(actions, {}, self.ledger, cfg, live=True, now=NOW)
        sheet = self.dir / "calls.csv"
        self.assertEqual(calls.write_sheet(actions, sheet), 1)
        with sheet.open() as fh:
            rows = list(csv.DictReader(fh))
        rows[0]["outcome"] = "do_not_call"
        with sheet.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=calls.SHEET_FIELDS)
            w.writeheader()
            w.writerows(rows)
        self.assertEqual(calls.import_outcomes(sheet, self.ledger, self.suppression), (1, []))
        self.assertEqual(calls.import_outcomes(sheet, self.ledger, self.suppression), (0, []), "idempotent")
        self.assertTrue(self.suppression.blocks("+442079460000", "call"))
        self.assertEqual(self.run_day(cfg, [c], NOW + timedelta(days=5))[0], [])


class InboxTests(unittest.TestCase):
    def msg(self, sender, subject, body, **headers):
        m = EmailMessage()
        m["From"], m["Subject"] = sender, subject
        for k, v in headers.items():
            m[k.replace("_", "-")] = v
        m.set_content(body)
        return m

    def setUp(self):
        self.c = candidate()
        self.by_email = {self.c.email: self.c}

    def test_classify(self):
        cases = [
            (self.msg("Priya <priya@example.net>", "Re: hello", "Yes please, call me tomorrow."), "replied"),
            (self.msg("priya@example.net", "Re: hello", "Please remove me from your list"), "unsubscribed"),
            (self.msg("priya@example.net", "Unsubscribe", ""), "unsubscribed"),
            (self.msg("priya@example.net", "Out of office", "Back Monday"), "auto_reply"),
            (self.msg("MAILER-DAEMON@mx.example", "Undelivered", "Delivery to priya@example.net failed"), "bounced"),
        ]
        for m, expected in cases:
            self.assertEqual(inbox.classify(m, self.by_email), (self.c, expected), m["Subject"])

    def test_quoted_footer_is_not_an_unsubscribe(self):
        m = self.msg("priya@example.net", "Re: jobs", "Interested!\n\nOn Tue, Sam wrote:\n> Reply \"unsubscribe\" to stop")
        self.assertEqual(inbox.classify(m, self.by_email)[1], "replied")

    def test_unknown_sender_ignored(self):
        self.assertEqual(inbox.classify(self.msg("x@y.com", "hi", "hi"), self.by_email), (None, ""))


if __name__ == "__main__":
    unittest.main()
