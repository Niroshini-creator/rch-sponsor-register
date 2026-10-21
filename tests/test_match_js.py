"""The browser matcher (candidates/match.js) must give the same scores and labels as candidateboard.match on the real feed."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from candidateboard import match

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "jobs.json"
PROFILE = ROOT / "candidates" / "profiles" / "sample-candidate.json"
RUNNER = """
const fs = require('fs'); const [dir] = process.argv.slice(1); const R = process.env.ROOT;
const I = require(R + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(R + '/candidateboard/roles.json', 'utf8')));
const M = require(R + '/candidates/match.js');
const jobs = JSON.parse(fs.readFileSync(dir + '/jobs.json', 'utf8'));
const out = JSON.parse(fs.readFileSync(dir + '/profiles.json', 'utf8')).map(p => { const m = M.Matcher(p); return jobs.map(j => m.evaluate(j)); });
fs.writeFileSync(dir + '/js.json', JSON.stringify(out));
"""


def variants():
    base = json.loads(PROFILE.read_text())
    a = copy.deepcopy(base)
    b = copy.deepcopy(base); b["driving_licence"] = False; b["clearance"] = {"held": "sc"}; b["experience_years"] = 9
    c = copy.deepcopy(base); c["driving_licence"] = True; c["visa"] = {"type": "citizen", "sponsorship": "not_needed"}
    d = copy.deepcopy(base); d["visa"]["new_entrant"] = False; d["experience_years"] = 2
    e = copy.deepcopy(base); e["english_only"] = False
    f = copy.deepcopy(base); f["visa"]["work_rights"] = ["us_opt", "ie_stamp_1g"]
    return [a, b, c, d, e, f]


def rights_jobs(jobs):
    """Copies of a real advert as US / Irish roles with the sponsorship labels OPT and Stamp 1G holders care about."""
    out = []
    for country, status in (("US", "graduate_route"), ("US", "not_sponsored"), ("US", "confirmed"), ("IE", "stamp_1g"), ("IE", "confirmed"), ("GB", "not_sponsored")):
        j = copy.deepcopy(next(x for x in jobs if x.get("title")))
        j.update(country=country, sponsorship=status, location="Test")
        out.append(j)
    kw = copy.deepcopy(next(x for x in jobs if x.get("title")))
    kw.update(country="GB", sponsorship="confirmed", title="Compliance Delivery Officer", location="Test",
              description="Own SAP GRC Access Control, access risk analysis, segregation of duties reviews, firefighter emergency access, "
                          "authorisations, ITGC audit evidence and remediation.", full_text="")
    out.append(kw)
    dg = copy.deepcopy(kw)
    dg.update(title="SAP GRC Consultant", description=dg["description"], kw=["sap grc", "grc access control", "segregation of duties", "firefighter", "itgc"],
              signals="This role requires SC clearance and you must be a British citizen.", text_len=2600)
    out.append(dg)
    return out


@unittest.skipUnless(shutil.which("node") and FEED.exists() and PROFILE.exists(), "needs node, the shared feed and the sample profile")
class MatchParityTests(unittest.TestCase):
    def test_same_scores_and_labels_on_the_real_feed(self):
        jobs = json.loads(FEED.read_text())["jobs"]          # every country: the language rule only applies outside the English-speaking ones
        jobs = jobs + rights_jobs(jobs)
        profiles = variants()
        py = [[match.Matcher(p).evaluate(j) for j in jobs] for p in profiles]
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "jobs.json").write_text(json.dumps(jobs))
            (d / "profiles.json").write_text(json.dumps(profiles))
            subprocess.run(["node", "-e", RUNNER, str(d)], check=True, env={"ROOT": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"})
            js = json.loads((d / "js.json").read_text())
        scored = 0
        for pi, (a, b) in enumerate(zip(py, js)):
            for job, x, y in zip(jobs, a, b):
                self.assertEqual(json.loads(json.dumps(x)), y, f"profile {pi}: {job['title']} @ {job['company']}")
                scored += x is not None
        self.assertGreater(scored, 100)       # the comparison covered real matches, not just rejections
        language = [(pi, j["title"]) for pi, rows in enumerate(py) for j, ev in zip(jobs, rows) if ev and "language" in ev["hidden_by_default"]]
        self.assertTrue(any(pi != 4 for pi, _ in language) and not any(pi == 4 for pi, _ in language))   # the rule fires, and not when switched off


if __name__ == "__main__":
    unittest.main()


class WorkRightsTests(unittest.TestCase):
    def setUp(self):
        base = json.loads(PROFILE.read_text())
        self.job = {"title": base["roles"][0]["title"], "company": "X", "description": "", "location": "Test", "country": "US",
                    "sponsorship": "graduate_route", "url": "u"}
        self.base = base

    def run_for(self, rights, country, status):
        p = copy.deepcopy(self.base); p["visa"]["sponsorship"] = "required"; p["visa"]["work_rights"] = rights
        return match.Matcher(p).evaluate({**self.job, "country": country, "sponsorship": status})

    def test_opt_and_stamp_1g_holders_keep_roles_that_need_no_sponsor(self):
        r = self.run_for(["us_opt"], "US", "graduate_route")
        self.assertTrue(r["sponsorship_offered"])
        self.assertNotIn("no_sponsorship", r["hidden_by_default"])
        self.assertIn("OPT", r["sponsorship_label"])
        r = self.run_for(["ie_stamp_1g"], "IE", "stamp_1g")
        self.assertNotIn("no_sponsorship", r["hidden_by_default"])
        self.assertIn("Stamp 1G", r["sponsorship_label"])

    def test_rights_only_apply_in_their_own_country(self):
        self.assertIn("no_sponsorship", self.run_for(["us_opt"], "IE", "stamp_1g")["hidden_by_default"])
        self.assertIn("no_sponsorship", self.run_for(["ie_stamp_1g"], "US", "graduate_route")["hidden_by_default"])
        self.assertIn("no_sponsorship", self.run_for([], "US", "graduate_route")["hidden_by_default"])
        self.assertIn("no_sponsorship", self.run_for(["us_opt"], "GB", "not_sponsored")["hidden_by_default"])


class IndiaTests(unittest.TestCase):
    CASES = [("12-18 lakhs", 8, "meets"), ("6 LPA", 8, "below"), ("6 - 10 LPA", 8, "partial"), ("1,200,000 – 1,800,000", 8, "meets"),
             ("₹ 9,50,000", 8, "meets"), ("45,000 per month", 8, "unstated"), ("", 8, "unstated"), ("10 LPA", 12, "below")]

    def setUp(self):
        self.base = json.loads(PROFILE.read_text())

    def evaluate(self, salary, lpa):
        p = copy.deepcopy(self.base); p["india_min_lpa"] = lpa; p["visa"]["sponsorship"] = "required"
        job = {"title": p["roles"][0]["title"], "company": "X", "description": "", "location": "Pune", "country": "IN",
               "sponsorship": "local", "salary": salary, "url": "u"}
        return p, job, match.Matcher(p).evaluate(job)

    def test_india_roles_need_no_visa_and_respect_the_minimum_pay(self):
        for salary, lpa, status in self.CASES:
            _, _, r = self.evaluate(salary, lpa)
            self.assertEqual(r["visa_pay"]["status"], status, salary)
            self.assertTrue(r["sponsorship_offered"])
            self.assertNotIn("no_sponsorship", r["hidden_by_default"])
            self.assertEqual("pay_below_minimum" in r["hidden_by_default"], status == "below", salary)
            self.assertNotIn("language", r["hidden_by_default"])

    def test_browser_matcher_agrees(self):
        if not shutil.which("node"):
            self.skipTest("node needed")
        profiles, jobs = [], []
        for salary, lpa, _ in self.CASES:
            p, job, _ = self.evaluate(salary, lpa)
            profiles.append(p); jobs.append(job)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "jobs.json").write_text(json.dumps(jobs))
            (d / "profiles.json").write_text(json.dumps(profiles))
            runner = RUNNER.replace("return jobs.map(j => m.evaluate(j))", "return jobs.map(j => m.evaluate(j))")
            subprocess.run(["node", "-e", runner, str(d)], check=True, env={"ROOT": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"})
            js = json.loads((d / "js.json").read_text())
        for i, (p, job) in enumerate(zip(profiles, jobs)):
            self.assertEqual(js[i][i], json.loads(json.dumps(match.Matcher(p).evaluate(job))), self.CASES[i][0])


class KeywordDiscoveryTests(unittest.TestCase):
    def profile(self):
        from candidateboard import intake
        import tempfile as tf
        sys_path = ROOT / "tests"
        from tests_fixtures import SAP_CV
        with tf.TemporaryDirectory() as d:
            (Path(d) / "sap.txt").write_text(SAP_CV, encoding="utf-8")
            return intake.build_profile({"SAP Security & GRC": Path(d) / "sap.txt"}, "", name="Jane", slug="jane", location="Coventry")

    def test_job_without_a_target_title_is_found_by_cv_keywords(self):
        p = self.profile()
        job = {"title": "Compliance Delivery Officer", "company": "X", "country": "GB", "sponsorship": "confirmed", "url": "u", "location": "Test",
               "description": "Own SAP GRC Access Control, access risk analysis, segregation of duties reviews, firefighter emergency access, "
                              "authorisations, ITGC audit evidence and remediation.", "full_text": ""}
        r = match.Matcher(p).evaluate(job)
        self.assertIsNotNone(r)
        self.assertEqual((r["tier"], r["role"]), (4, "Matched on CV keywords"))
        self.assertGreaterEqual(len(r["skills_matched"]), 4)
        job["description"] = "Answer phones and book meetings."
        self.assertIsNone(match.Matcher(p).evaluate(job))

    def test_domain_keywords_count_for_a_role_the_cv_does_not_show(self):
        p = self.profile()
        p["roles"].append({"title": "Digital Marketing Executive", "family": "digital_marketing", "tier": 3, "track": "SAP Security & GRC", "source": "attached document"})
        job = {"title": "Digital Marketing Executive", "company": "X", "country": "GB", "sponsorship": "confirmed", "url": "u", "location": "Test",
               "description": "Run SEO, Google Analytics, email marketing and paid social campaigns. " * 3, "full_text": ""}
        r = match.Matcher(p).evaluate(job)
        self.assertTrue(r["skills_matched"])        # marketing keywords, not SAP ones


@unittest.skipUnless(shutil.which("node"), "node is needed")
class DocumentKeywordTests(unittest.TestCase):
    PROSE = "I have worked in digital marketing campaigns, SEO, Google Analytics, email marketing and social media content for retail brands."

    def test_document_without_titles_is_read_by_its_keywords_in_both_engines(self):
        from candidateboard import intake
        js = json.loads(subprocess.run(["node", "-e", """
const fs = require('fs'); const R = process.env.ROOT;
const I = require(R + '/candidates/intake.js').init(JSON.parse(fs.readFileSync(R + '/candidateboard/roles.json', 'utf8')));
const p = { roles: [], tracks: [{name: 'CV'}], family_evidence: {} };
console.log(JSON.stringify({ domains: I.documentDomains(process.env.PROSE), added: I.addPositions(p, process.env.PROSE).map(r => [r.title, r.source]) }));
""" ], check=True, capture_output=True, text=True, env={"ROOT": str(ROOT), "PROSE": self.PROSE, "PATH": "/usr/bin:/bin:/usr/local/bin"}).stdout)
        self.assertEqual(js["domains"], intake.document_domains(self.PROSE))
        self.assertTrue(js["added"] and all(src == "document keywords" for _, src in js["added"]))
        self.assertEqual(intake.document_domains("Hello"), [])


class RareRoleTests(unittest.TestCase):
    """Admin-type roles: scored on little CV evidence, and hidden for a candidate who needs a sponsor."""
    ADMIN = {"title": "Business Support Administrator", "company": "X", "country": "GB", "location": "Test", "url": "u",
             "description": "Office administration, diary management, filing, data entry, minute taking, reception cover, supplier invoices, stock ordering and travel booking. " * 3}

    def setUp(self):
        from candidateboard import intake
        sys_tests = ROOT / "tests"
        from tests_fixtures import SAP_CV
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "sap.txt").write_text(SAP_CV, encoding="utf-8")
            self.profile = intake.build_profile({"SAP": Path(d) / "sap.txt"}, "Business Support Administrator\n• Business Support Administrator\n", name="J", slug="j", location="Coventry")
        self.profile["visa"]["sponsorship"] = "required"

    def test_unevidenced_admin_role_is_capped_and_hidden_for_a_candidate_who_needs_a_sponsor(self):
        r = match.Matcher(self.profile).evaluate({**self.ADMIN, "sponsorship": "licensed_sponsor"})
        self.assertLessEqual(r["match"], 60)
        self.assertIn("role_not_sponsorable", r["hidden_by_default"])
        self.assertTrue(any("little evidence" in x for x in r["reasons"]))

    def test_an_advert_that_offers_sponsorship_or_a_candidate_who_needs_none_keeps_it_visible(self):
        r = match.Matcher(self.profile).evaluate({**self.ADMIN, "sponsorship": "confirmed"})
        self.assertNotIn("role_not_sponsorable", r["hidden_by_default"])
        self.assertIn("Role type is usually below the Skilled Worker skill level", r["flags"])
        self.profile["visa"]["sponsorship"] = "not_needed"
        r = match.Matcher(self.profile).evaluate({**self.ADMIN, "sponsorship": "licensed_sponsor"})
        self.assertNotIn("role_not_sponsorable", r["hidden_by_default"])
