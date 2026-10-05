import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobfeed.models import Job
from mugilan.jobmatch import pipeline
from mugilan.jobmatch.score import parse_salary, requires_clearance, score_job

NOW = datetime.now(timezone.utc)
PROFILE = pipeline.load_profile()


def job(**kw) -> Job:
    base = dict(source="Reed", source_id="1", title="OSS/BSS Solution Architect", company="Acme Telecom Ltd",
                location="London", country="GB", url="https://example.org/1", posted_at=NOW - timedelta(days=1),
                description="Design NetCracker network inventory and order management for GPON and DOCSIS.",
                salary="70,000 – 85,000")
    base.update(kw)
    return Job(**base)


class ScoreTests(unittest.TestCase):
    def test_perfect_fit_scores_high(self):
        r = score_job("Senior OSS/BSS Solution Architect", "NetCracker inventory, order management, GPON, GCP, TM Forum",
                      "75,000", 60000, "confirmed")
        self.assertGreaterEqual(r.score, 85)

    def test_unrelated_role_scores_low(self):
        self.assertLess(score_job("Site Manager", "Construction site, bricks", "", 60000).score, 20)

    def test_generic_architect_without_telecom_is_middling(self):
        r = score_job("Solution Architect", "Retail e-commerce platform on AWS", "", 60000, "confirmed")
        self.assertTrue(20 <= r.score < 45, r.score)

    def test_junior_and_low_pay_are_penalised(self):
        hi = score_job("OSS Architect", "OSS BSS", "70,000", 60000, "confirmed").score
        lo = score_job("Junior OSS Architect", "OSS BSS", "30,000", 60000, "confirmed").score
        self.assertLess(lo, hi - 20)

    def test_unverified_sponsorship_costs_points(self):
        a = score_job("OSS Architect", "OSS", "", 60000, "confirmed").score
        b = score_job("OSS Architect", "OSS", "", 60000, "unverified").score
        self.assertEqual(a - b, 5)

    def test_immediate_start_is_flagged(self):
        r = score_job("OSS Architect", "Immediate start required", "", 60000)
        self.assertTrue(any("notice" in f for f in r.flags))

    def test_parse_salary(self):
        self.assertEqual(parse_salary("£60,000 - £75,000 per annum"), (60000, 75000))
        self.assertEqual(parse_salary("65k"), (65000, 65000))
        self.assertEqual(parse_salary("£450 per day"), (None, None))
        self.assertEqual(parse_salary(""), (None, None))


class ClearanceTests(unittest.TestCase):
    def test_detects_clearance(self):
        for text in ("Active SC clearance required", "must hold DV clearance", "SC/DV cleared",
                     "Eligible for SC", "security clearance needed", "Developed Vetting"):
            self.assertTrue(requires_clearance(text), text)

    def test_ignores_non_clearance(self):
        for text in ("Baseline BPSS checks", "We use SCRUM and discovery workshops", "sc in lowercase prose"):
            self.assertFalse(requires_clearance(text), text)


class PipelineTests(unittest.TestCase):
    def build(self, jobs, **kw):
        stats = {"clearance_removed": 0, "no_sponsorship_removed": 0, "below_threshold": 0}
        return pipeline.build(jobs, PROFILE, 7, None, None, stats), stats

    def test_keeps_good_drops_clearance_old_and_refusals(self):
        jobs = [job(),
                job(source_id="2", title="OSS Architect", description="OSS BSS. Active SC clearance required."),
                job(source_id="3", description="OSS BSS NetCracker. We are unable to offer sponsorship."),
                job(source_id="4", posted_at=NOW - timedelta(days=9)),
                job(source_id="5", title="Site Manager", description="bricks")]
        out, stats = self.build(jobs)
        self.assertEqual([r["source_id"] for r in out], ["1"])
        self.assertEqual((stats["clearance_removed"], stats["no_sponsorship_removed"]), (1, 1))
        self.assertEqual(out[0]["sponsorship"], "unverified")
        self.assertTrue(out[0]["match"] >= PROFILE["min_match"])

    def test_non_uk_dropped_and_duplicates_merged(self):
        out, _ = self.build([job(country="US"), job(source="Adzuna", source_id="9"), job()])
        self.assertEqual(len(out), 1)

    def test_france_keeps_english_adverts_and_drops_french_only(self):
        english = job(source="Adzuna", source_id="f1", country="FR", location="Paris", salary="75,000 – 90,000",
                      title="OSS/BSS Solution Architect",
                      description="Design NetCracker network inventory and order management for GPON. You will work with our telecom teams in Paris.")
        french = job(source="Adzuna", source_id="f2", country="FR", location="Lyon", title="Architecte OSS BSS",
                     description="Nous recherchons un architecte pour concevoir des solutions OSS BSS pour notre client. Maîtrise du français exigée, le candidat doit avoir une expérience dans les télécommunications.")
        out, stats = self.build([english, french])
        self.assertEqual([r["source_id"] for r in out], ["f1"])
        self.assertEqual(out[0]["currency"], "€")
        self.assertEqual(out[0]["sponsorship"], "permit_check")
        self.assertEqual(stats["language_removed"], 1)

    def test_salary_threshold_is_per_country(self):
        self.assertEqual(pipeline.min_salary_for(PROFILE, "GB"), 60000)
        self.assertEqual(pipeline.min_salary_for(PROFILE, "FR"), 70000)

    def test_near_misses_are_collected_but_not_published(self):
        mid = job(source_id="30", title="Solution Architect", description="Retail platform", salary="70,000")
        stats = {"clearance_removed": 0, "no_sponsorship_removed": 0, "below_threshold": 0}
        near: dict = {}
        out = pipeline.build([mid, job(source_id="31", title="Site Manager", description="bricks")],
                             PROFILE, 7, None, None, stats, near)
        self.assertEqual(out, [])
        self.assertEqual([r["source_id"] for r in near.values()], ["30"])   # the irrelevant one is not listed

    def test_deepen_reads_full_advert_and_rescues_buried_keywords(self):
        snippet = job(source_id="77", title="Solution Architect", description="Exciting architect role at a telco.", salary="70,000")
        boring = job(source_id="78", title="Site Manager", description="bricks")
        calls = []
        full = ("Solution architecture for OSS BSS: NetCracker network inventory, order management, "
                "service fulfilment, GPON, DOCSIS, GCP, TM Forum. Visa sponsorship available.")
        stats = {"clearance_removed": 0, "no_sponsorship_removed": 0, "below_threshold": 0}

        def fake(job_id):
            calls.append(job_id)
            return full

        before, _ = self.build([snippet])
        pipeline.deepen([snippet, boring], PROFILE, stats, fetch_full=fake)
        after, _ = self.build([snippet])
        self.assertEqual(calls, ["77"])               # the irrelevant advert is never fetched
        self.assertEqual(stats["full_advert_fetched"], 1)
        self.assertEqual(before, [])                  # snippet alone was below threshold
        self.assertEqual(len(after), 1)
        self.assertGreater(after[0]["match"], 70)

    def test_deepen_survives_a_failed_fetch(self):
        j = job(title="OSS Architect", description="short")
        stats = {}
        def boom(_):
            raise OSError("down")
        pipeline.deepen([j], PROFILE, stats, fetch_full=boom)
        self.assertEqual(j.description, "short")
        self.assertEqual(stats["full_advert_fetched"], 0)

    def test_merge_keeps_recent_previous_and_drops_expired(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "jobs.json"
            keep = {"id": "keep", "match": 80, "posted_at": (NOW - timedelta(days=3)).isoformat()}
            gone = {"id": "gone", "match": 90, "posted_at": (NOW - timedelta(days=10)).isoformat()}
            path.write_text(json.dumps({"jobs": [keep, gone]}))
            fresh = [{"id": "new", "match": 70, "posted_at": NOW.isoformat()}]
            merged = pipeline.merge_previous(fresh, path, 7, NOW)
            self.assertEqual([r["id"] for r in merged], ["keep", "new"])
            self.assertTrue(all(r["first_seen"] for r in merged))


if __name__ == "__main__":
    unittest.main()
