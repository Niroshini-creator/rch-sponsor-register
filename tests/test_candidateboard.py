import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from candidateboard import checks, cv, intake, match, pipeline, sources, taxonomy
from jobfeed.sources import SkipSource

NOW = datetime.now(timezone.utc)
TAX = taxonomy.load()

from tests_fixtures import BA_CV, ROLES, SAP_CV  # noqa: E402


def job(title, description="", **kw):
    base = {"id": title[:8], "title": title, "company": "Acme Ltd", "location": "Leeds", "country": "GB", "url": "https://x/" + title,
            "posted_at": (NOW - timedelta(days=1)).isoformat(), "description": description, "salary": "", "sponsorship": "licensed_sponsor",
            "source": "Reed", "channel": "aggregator", "sector": "Private Sector", "domain": "Management & Business", "sponsor_routes": []}
    base.update(kw)
    return base


def profile(tmp: Path | None = None, **over):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "sap.txt").write_text(SAP_CV)
        (d / "ba.txt").write_text(BA_CV)
        p = intake.build_profile({"SAP Security & GRC": d / "sap.txt", "Business Analyst": d / "ba.txt"}, ROLES, name="Jane Example",
                                 visa={"type": "graduate", "label": "Graduate visa", "expires": "2027-11", "sponsorship": "preferred", "new_entrant": True},
                                 today=date(2026, 10, 14))
    p.update(over)
    return p


class ChecksTests(unittest.TestCase):
    def test_clearance_levels_and_blocking(self):
        for text, level, blocks in [("Active SC clearance is required.", "sc", True), ("Must be eligible for SC clearance", "sc", True),
                                    ("DV cleared", "dv", True), ("SC/DV clearance", "dv", True), ("a sc clearance would help", "sc", True),
                                    ("This is a security cleared role", "unspecified", True), ("We run BPSS checks", "basic", False),
                                    ("Enhanced DBS required", "dbs", False), ("Our SC and DV are great words", "none", False)]:
            r = checks.clearance(text)
            self.assertEqual((r["level"], r["blocks"]), (level, blocks), text)
        self.assertEqual(checks.clearance("Must be eligible for SC clearance")["stance"], "obtain")
        self.assertFalse(checks.clearance("SC clearance required", held="sc")["blocks"])
        self.assertTrue(checks.clearance("DV clearance required", held="sc")["blocks"])

    def test_driving_licence_and_work_mode(self):
        self.assertEqual(checks.driving_licence("Full UK driving licence essential", None)["status"], "unknown")
        self.assertEqual(checks.driving_licence("A driving licence is desirable", False)["need"], "desirable")
        self.assertEqual(checks.driving_licence("Must hold a valid driving licence", False)["status"], "missing")
        self.assertEqual(checks.driving_licence("No travel", True)["need"], "")
        self.assertEqual((checks.work_mode("Hybrid working, 2 days in the office"), checks.work_mode("", "Remote, UK"), checks.work_mode("On site")),
                         ("hybrid", "remote", ""))


class CvTests(unittest.TestCase):
    def test_experience_months_counts_overlaps_once(self):
        text = "Jan 2020 - Dec 2020\nJun 2020 - Mar 2021\nSep 2025 - Present"
        self.assertEqual(cv.experience_months(text, date(2025, 12, 1)), 15 + 4)

    def test_role_list_parsing(self):
        titles = [r["title"] for r in cv.parse_role_list(ROLES)]
        self.assertEqual(titles, ["SAP Security Consultant", "Segregation of Duties Analyst", "Junior Business Analyst", "UAT Analyst",
                                  "UAT Coordinator", "Marketing Executive", "Marketing Coordinator", "Social Media & Content Coordinator"])

    def test_scan_finds_families_and_hides_contact_details(self):
        s = cv.scan(SAP_CV, date(2026, 10, 14))
        self.assertEqual(s["name"], "Jane Example")
        self.assertGreaterEqual(s["families"]["sap_security_grc"]["strength"], 55)
        self.assertNotIn("example.com", json.dumps(s))
        self.assertEqual(s["education"], "Master's (MBA)")


class TaxonomyTests(unittest.TestCase):
    def test_titles_map_to_the_right_family(self):
        for title, family in [("SAP Security Consultant", "sap_security_grc"), ("SAP Identity & Access Management Analyst", "sap_security_grc"),
                              ("SAP Business Analyst", "sap_functional"), ("Sales Support Analyst", "sales_support"),
                              ("IT Support Analyst", "it_support"), ("Senior Analyst", None), ("Data Analyst", "data_analyst"),
                              ("Junior Business Analyst", "business_analyst"), ("Security Analyst", "cyber_security"),
                              ("UAT Coordinator", "uat_testing"), ("Administrator", "admin_office")]:
            self.assertEqual(TAX.family_for_title(title), family, title)


class IntakeTests(unittest.TestCase):
    def test_tiers_tracks_and_roles(self):
        p = profile()
        by_title = {r["title"]: r for r in p["roles"]}
        self.assertEqual(by_title["SAP Security Consultant"]["tier"], 1)
        self.assertEqual(by_title["SAP Security Consultant"]["track"], "SAP Security & GRC")
        self.assertEqual(by_title["Junior Business Analyst"]["track"], "Business Analyst")
        # Filed under a CV that does not exist ("Marketing / Digital"): never above tier 3.
        self.assertGreaterEqual(by_title["Marketing Executive"]["tier"], 3)
        self.assertEqual(p["visa"]["sponsorship"], "preferred")
        self.assertNotIn("+44", json.dumps(p))
        self.assertTrue(all(len(t["skills"]) <= intake.SKILLS_PER_TRACK for t in p["tracks"]))
        self.assertFalse(set(t.lower() for t in intake.GENERIC_SKILLS) & {s for t in p["tracks"] for s in t["skills"]})


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.m = match.Matcher(profile(experience_years=4.5))

    def test_core_role_scores_high_with_labels(self):
        ev = self.m.evaluate(job("SAP GRC Consultant", "x" * 700 + " SAP GRC access risk analysis segregation of duties firefighter "
                                 "emergency access profile generator. £50,000 per annum", salary="£50,000"))
        self.assertEqual((ev["tier"], ev["family"], ev["track"]), (1, "sap_security_grc", "SAP Security & GRC"))
        self.assertGreaterEqual(ev["match"], 85)
        self.assertEqual((ev["evidence"], ev["sponsorship_offered"], ev["hidden_by_default"]), ("full", True, []))
        self.assertEqual(ev["visa_pay"]["status"], "meets")

    def test_extract_caps_the_match(self):
        ev = self.m.evaluate(job("SAP GRC Consultant", "SAP GRC segregation of duties"))
        self.assertEqual(ev["evidence"], "extract")
        self.assertLess(ev["match"], 85)

    def test_clearance_and_licence_and_pay_hide_a_role(self):
        ev = self.m.evaluate(job("Business Analyst", "x" * 700 + " Active SC clearance required. Full driving licence essential.", salary="£20,000"))
        self.assertTrue(ev["clearance"]["blocks"])
        self.assertEqual(ev["visa_pay"]["status"], "below")
        # The candidate's licence is not confirmed, so a required licence is flagged but does not hide the role.
        self.assertEqual(set(ev["hidden_by_default"]), {"clearance", "pay_below_visa"})
        self.assertEqual(ev["driving_licence"]["status"], "unknown")

    def test_sponsorship_labels(self):
        no = self.m.evaluate(job("Business Analyst", sponsorship="not_sponsored"))
        self.assertEqual((no["sponsorship_label"], no["hidden_by_default"]), ("Sponsorship not offered", ["no_sponsorship"]))
        yes = self.m.evaluate(job("Business Analyst", sponsorship="confirmed"))
        self.assertEqual(yes["sponsorship_rank"], 0)
        route = self.m.evaluate(job("Business Analyst", sponsor_routes=["Temporary Worker: Creative Worker"]))
        self.assertIn("no_skilled_worker_route", route["hidden_by_default"])

    def test_level_and_relevance(self):
        self.assertIn("More senior than the CV", self.m.evaluate(job("Head of Business Analysis", "Business Analyst"))["flags"])
        self.assertIsNone(self.m.evaluate(job("Registered Nurse")))
        self.assertIsNone(self.m.evaluate(job("Senior Analyst")))
        self.assertEqual(self.m.evaluate(job("Marketing Executive"))["sponsorability"], "rare")

    def test_other_roles_tier(self):
        p = profile(also_consider=["it_support"])
        ev = match.Matcher(p).evaluate(job("IT Support Analyst", "x" * 700 + " service desk servicenow incident"))
        self.assertEqual(ev["tier"], 4)

    def test_not_needing_sponsorship_skips_pay_and_sponsor_hiding(self):
        p = profile()
        p["visa"] = {"type": "citizen", "sponsorship": "not_needed"}
        ev = match.Matcher(p).evaluate(job("Business Analyst", sponsorship="not_sponsored", salary="£15,000"))
        self.assertEqual((ev["visa_pay"]["status"], ev["hidden_by_default"]), ("", []))


class PipelineTests(unittest.TestCase):
    def test_classify_sponsorship(self):
        from jobfeed.models import Job
        j = Job(source="Reed", source_id="1", title="BA", company="Acme", location="", country="GB", url="u", posted_at=NOW)
        self.assertEqual(pipeline.classify_sponsorship("We cannot offer visa sponsorship.", j, None, False)[0], "not_sponsored")
        self.assertEqual(pipeline.classify_sponsorship("Visa sponsorship is available.", j, None, False)[0], "confirmed")
        self.assertEqual(pipeline.classify_sponsorship("Nothing said", j, None, True)[0], "agency")
        self.assertEqual(pipeline.classify_sponsorship("Nothing said", j, None, False)[0], "unverified")

    def test_search_terms_put_core_roles_first(self):
        terms = pipeline.search_terms(profile())
        self.assertEqual(terms[0], [r for r in sorted(profile()["roles"], key=lambda r: r["tier"])][0]["title"])
        self.assertLessEqual(len(terms), 28)

    def test_build_dedupes_filters_and_counts(self):
        p = profile()
        m = match.Matcher(p)
        old = job("Business Analyst", posted_at=(NOW - timedelta(days=9)).isoformat(), url="https://x/old")
        dup_a = job("Business Analyst", "x" * 700, id="a", source="Adzuna", url="https://x/a")
        dup_b = job("Business Analyst", "x" * 700, id="b", source="Reed", url="https://x/b", sponsorship="confirmed")
        nurse = job("Registered Nurse", id="n", url="https://x/n")
        stats = {"not_relevant": 0, "below_threshold": 0, "other_roles_without_sponsor": 0}
        out = pipeline.build([old, dup_a, dup_b, nurse], m, p, 7, stats)
        self.assertEqual([r["id"] for r in out], ["b"])          # confirmed copy wins; old and irrelevant dropped
        self.assertEqual(stats["not_relevant"], 1)
        self.assertNotIn("full_text", out[0])

    def test_deepen_reads_full_advert_and_applies_refusal(self):
        p = profile()
        m = match.Matcher(p)
        rec = job("Business Analyst", "short", source="Reed", source_id="42", full_text="short", sponsorship="licensed_sponsor")
        with mock.patch.object(pipeline.time, "sleep"):
            stats = {}
            pipeline.deepen([rec], m, stats, reed_full=lambda i: "We are unable to offer visa sponsorship. " + "requirements " * 5)
        self.assertEqual((stats["full_advert_read"], rec["sponsorship"]), (1, "not_sponsored"))

    def test_merge_previous_keeps_recent_unless_rules_changed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            old = {"id": "old", "tier": 1, "match": 80, "sponsorship_rank": 0, "posted_at": (NOW - timedelta(days=2)).isoformat()}
            stale = {**old, "id": "stale", "posted_at": (NOW - timedelta(days=9)).isoformat()}
            path.write_text(json.dumps({"rules_version": "v1", "jobs": [old, stale]}))
            fresh = [{"id": "new", "tier": 1, "match": 70, "sponsorship_rank": 0, "posted_at": NOW.isoformat()}]
            kept = pipeline.merge_previous([dict(f) for f in fresh], path, 7, NOW, "v1")
            self.assertEqual({r["id"] for r in kept}, {"old", "new"})
            changed = pipeline.merge_previous([dict(f) for f in fresh], path, 7, NOW, "v2")
            self.assertEqual({r["id"] for r in changed}, {"new"})

    def test_fetch_fresh_reports_missing_keys_without_failing(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            status = {}
            with mock.patch.object(sources.shared, "nhs_jobs", side_effect=SkipSource("off")), \
                 mock.patch.object(sources.shared, "jobs_ac_uk", side_effect=SkipSource("off")):
                self.assertEqual(pipeline.fetch_fresh(profile(), 7, status), [])
        self.assertEqual({k: v["status"] for k, v in status.items()}, {"Reed": "skipped", "Adzuna": "skipped", "NHS Jobs": "skipped", "jobs.ac.uk": "skipped"})

    def test_end_to_end_offline_run_writes_board_and_index(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            prof = profile()
            prof["slug"] = "demo"
            (d / "profiles").mkdir()
            (d / "profiles" / "demo.json").write_text(json.dumps(prof))
            feed = d / "jobs.json"
            feed.write_text(json.dumps({"generated_at": NOW.isoformat(), "jobs": [
                job("Business Analyst", "x" * 700 + " requirements stakeholder uat", id="j1"),
                job("SAP Security Consultant", "SAP GRC Active SC clearance", id="j2"),
                job("Business Analyst", id="j3", country="IE")]}))
            payload = pipeline.run(d / "profiles" / "demo.json", 7, feed, d / "data", offline=True)
            self.assertEqual(payload["counts"]["published"], 2)
            self.assertEqual(payload["sources"]["Shared sponsor feed"]["count"], 2)   # the IE job is outside the candidate's countries
            by_id = {j["id"]: j for j in payload["jobs"]}
            self.assertTrue(by_id["j2"]["clearance"]["blocks"])
            self.assertTrue((d / "data" / "demo.json").exists())
            index = json.loads((d / "data" / "index.json").read_text())
            self.assertEqual(index["candidates"][0]["slug"], "demo")
            self.assertNotIn("full_text", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
