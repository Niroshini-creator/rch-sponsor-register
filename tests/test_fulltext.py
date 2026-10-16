"""The digest of a whole advert (jobfeed.digest) lets the matcher score the full advert from the 400 characters the feed publishes."""
import json
import unittest
from datetime import datetime, timezone
from unittest import mock

from candidateboard import intake, match
from jobfeed import deepen
from jobfeed.digest import digest
from jobfeed.models import Job
from tests_fixtures import SAP_CV

FILLER = "We are a growing team that values collaboration and learning. " * 12
FULL = ("Senior Compliance Delivery Officer. " + FILLER + "You will own SAP GRC Access Control, access risk analysis, segregation of duties "
        "reviews, firefighter emergency access, authorisations and ITGC audit evidence. " + FILLER +
        "This role requires SC clearance and you must be a British citizen. A full UK driving licence is essential.")


class DigestTests(unittest.TestCase):
    def test_digest_records_keywords_signals_and_length(self):
        kw, signals, length = digest("Compliance Officer", FULL)
        self.assertIn("segregation of duties", kw)
        self.assertIn("sap grc", kw)
        self.assertIn("SC clearance", signals)
        self.assertIn("driving licence", signals)
        self.assertEqual(length, len(FULL))
        self.assertLessEqual(len(signals), 900)

    def test_short_advert_has_no_signals(self):
        self.assertEqual(digest("Analyst", "Needs SC clearance.")[1:], ("", 19))


def profile():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sap.txt").write_text(SAP_CV, encoding="utf-8")
        return intake.build_profile({"SAP Security & GRC": Path(d) / "sap.txt"}, "", name="Jane", slug="jane", location="Coventry")


class MatcherDigestTests(unittest.TestCase):
    def test_digest_gives_the_same_answer_as_the_whole_text(self):
        p = profile()
        base = {"title": "SAP GRC Consultant", "company": "X", "country": "GB", "sponsorship": "confirmed", "url": "u", "location": "Test"}
        whole = match.Matcher(p).evaluate({**base, "description": FULL[:400], "full_text": FULL})
        kw, signals, length = digest(base["title"], FULL)
        digested = match.Matcher(p).evaluate({**base, "description": FULL[:400], "kw": kw, "signals": signals, "text_len": length})
        self.assertEqual(whole["evidence"], digested["evidence"], "full")
        self.assertEqual(whole["skills_matched"], digested["skills_matched"])
        self.assertEqual(whole["match"], digested["match"])
        self.assertEqual((whole["clearance"]["level"], whole["clearance"]["blocks"]), (digested["clearance"]["level"], digested["clearance"]["blocks"]))
        self.assertEqual(whole["driving_licence"]["status"], digested["driving_licence"]["status"])
        extract = match.Matcher(p).evaluate({**base, "description": FULL[:400]})       # no digest: only the extract is known
        self.assertEqual(extract["evidence"], "extract")
        self.assertGreater(digested["match"], extract["match"])


class ReadFullAdvertTests(unittest.TestCase):
    def job(self, sid, text="snippet"):
        return Job(source="Reed", source_id=sid, title="Analyst", company="X", location="Leeds", country="GB", url="u",
                   posted_at=datetime.now(timezone.utc), description=text)

    def test_reed_snippets_are_replaced_once_and_capped(self):
        jobs = [self.job(str(i)) for i in range(5)] + [Job(**{**self.job("n").__dict__, "source": "NHS Jobs"})]
        reed = mock.Mock(return_value="the whole advert " * 20)
        with mock.patch.object(deepen, "REED_DEEP_MAX", 3), mock.patch.object(deepen, "PAUSE", 0):
            read = deepen.read_full_adverts(jobs, {jobs[0].id: ([], "", 900)}, reed)
        self.assertEqual(read, 3)                                        # capped; job 0 is known from the last feed; NHS untouched
        self.assertEqual(reed.call_args_list[0].args, ("1",))
        self.assertTrue(jobs[1].description.startswith("the whole advert"))
        self.assertEqual(jobs[5].description, "snippet")

    def test_digest_from_the_last_feed_is_reused(self):
        job = self.job("9")
        job.kw, job.signals, job.text_len = ["sap"], "", 7
        deepen.reuse_digest(job, {job.id: (["sap", "grc"], "SC clearance", 2400)})
        self.assertEqual((job.kw, job.signals, job.text_len), (["sap", "grc"], "SC clearance", 2400))


if __name__ == "__main__":
    unittest.main()


class FetchAllTests(unittest.TestCase):
    def job(self, n):
        return Job(source="S", source_id=str(n), title="T", company="C", location="L", country="GB", url="u", posted_at=datetime.now(timezone.utc))

    def test_sources_run_together_and_a_slow_one_is_cut_off_at_the_time_budget(self):
        from jobfeed import pipeline, sources
        import itertools

        def endless(days):
            for n in itertools.count():
                yield self.job(n)

        fake = {"quick": lambda d: iter([self.job(1), self.job(2)]), "endless": endless,
                "skipped": lambda d: (_ for _ in ()).throw(sources.SkipSource("no key")), "broken": lambda d: (_ for _ in ()).throw(RuntimeError("down"))}
        status = {}
        with mock.patch.object(sources, "SOURCES", fake), mock.patch.object(pipeline, "FEED_BUDGET_MINUTES", 0.0005), \
                mock.patch.object(pipeline.careers, "career_sites", lambda d, e, r: iter(())), mock.patch.object(sources, "rss_feeds", lambda d, f: iter(())):
            jobs = pipeline.fetch_all(7, {}, status)
        self.assertEqual(status["quick"], {"status": "ok", "count": 2})
        self.assertEqual(status["endless"]["status"], "partial")
        self.assertIn("time budget", status["endless"]["error"])
        self.assertEqual(status["skipped"]["status"], "skipped")
        self.assertEqual(status["broken"]["status"], "error")
        self.assertGreaterEqual(len(jobs), 3)
        self.assertEqual([j.source_id for j in jobs[:2]], ["1", "2"])        # results keep the sources' order


@unittest.skipUnless(__import__("shutil").which("node"), "node is needed")
class UndatedAdvertTests(unittest.TestCase):
    def test_browser_keeps_undated_adverts_inside_the_window_only_for_seven_days(self):
        import subprocess
        out = json.loads(subprocess.run(["node", "-e", """
const fs = require('fs'); const R = process.env.ROOT;
const I = require(R + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(R + '/candidateboard/roles.json', 'utf8')));
const M = require(R + '/candidates/match.js');
const p = JSON.parse(process.env.PROFILE);
const base = { title: 'SAP GRC Consultant', company: 'X', country: 'GB', sponsorship: 'confirmed', url: 'u', location: 'Test', description: 'SAP GRC Access Control, segregation of duties, firefighter' };
const now = Date.parse('2026-10-16T12:00:00Z');
const jobs = [
  { ...base, company: 'Fresh', posted_at: '2026-10-16T08:00:00Z' },
  { ...base, company: 'Old', posted_at: '2026-10-01T08:00:00Z' },
  { ...base, company: 'NoDate', posted_at: '2026-10-16T09:00:00Z', date_known: false },
];
console.log(JSON.stringify(M.liveJobs(jobs, p, { now }).map(j => [j.company, j.date_known ?? true])));
""" ], check=True, capture_output=True, text=True, env={"ROOT": str(ROOT), "PROFILE": json.dumps(profile()), "PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout)
        self.assertEqual(sorted(c for c, _ in out), ["Fresh", "NoDate"])
        self.assertEqual(dict(out)["NoDate"], False)


ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
