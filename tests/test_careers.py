import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jobfeed import careers, classify, contacts, pipeline, sponsors
from jobfeed.agencies import AgencyFilter
from jobfeed.models import Job

CONFIG = Path(__file__).resolve().parent.parent / "config"
NOW = datetime.now(timezone.utc)
ISO_NOW = NOW.isoformat()
CUTOFF = NOW - timedelta(days=7)


def run_feed(fn, emp, responses, method="get_json"):
    with mock.patch.object(careers.http, method, side_effect=responses):
        return list(fn(emp, CUTOFF))


class CareerSiteParserTests(unittest.TestCase):
    def test_greenhouse(self):
        payload = {"jobs": [
            {"id": 1, "title": "Backend Engineer", "first_published": ISO_NOW, "location": {"name": "London, UK"},
             "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "content": "&lt;p&gt;Visa sponsorship available&lt;/p&gt;"},
            {"id": 2, "title": "Old role", "first_published": "2020-01-01T00:00:00Z", "location": {"name": "London"},
             "absolute_url": "x", "content": ""},
            {"id": 3, "title": "US role", "first_published": ISO_NOW, "location": {"name": "New York, NY"},
             "absolute_url": "y", "content": ""},
        ]}
        jobs = run_feed(careers.greenhouse, {"name": "Acme", "id": "acme", "country": "GB"}, [payload])
        self.assertEqual([j.source_id for j in jobs], ["1", "3"])
        self.assertEqual((jobs[0].country, jobs[0].channel, jobs[0].description),
                         ("GB", "career_site", "Visa sponsorship available"))
        self.assertEqual(jobs[1].country, "US")  # dropped later by the pipeline, never mislabelled as UK

    def test_unrecognised_location_not_assumed_local(self):
        payload = {"jobs": [{"id": 1, "title": "Engineer", "first_published": ISO_NOW,
                             "location": {"name": "Bengaluru"}, "absolute_url": "u", "content": ""}]}
        emp = {"name": "Acme", "id": "acme", "country": "GB"}
        self.assertEqual(run_feed(careers.greenhouse, emp, [payload])[0].country, "")
        self.assertEqual(run_feed(careers.greenhouse, {**emp, "local": True}, [payload])[0].country, "GB")

    def test_lever(self):
        payload = [{"id": "abc", "text": "Data Scientist", "createdAt": NOW.timestamp() * 1000,
                    "hostedUrl": "https://jobs.lever.co/acme/abc", "categories": {"location": "Berlin", "commitment": "Full-time"},
                    "descriptionPlain": "Relocation and visa support provided.", "lists": [{"text": "You", "content": "<li>PhD</li>"}]}]
        job = run_feed(careers.lever, {"name": "Acme", "id": "acme", "country": "GB"}, [payload])[0]
        self.assertEqual((job.country, job.contract), ("DE", "Full-time"))
        self.assertIn("PhD", job.description)

    def test_ashby(self):
        payload = {"jobs": [{"id": "x1", "title": "Research Scientist", "publishedAt": ISO_NOW, "location": "Remote",
                             "address": {"postalAddress": {"addressCountry": "United Kingdom"}},
                             "jobUrl": "https://jobs.ashbyhq.com/acme/x1", "descriptionPlain": "text", "isListed": True}]}
        job = run_feed(careers.ashby, {"name": "Acme", "id": "acme", "country": "US"}, [payload])[0]
        self.assertEqual(job.country, "GB")

    def test_smartrecruiters_fetches_detail(self):
        listing = {"content": [{"id": "9", "name": "Chemist", "releasedDate": ISO_NOW,
                                "location": {"city": "Stuttgart", "country": "de"}}]}
        detail = {"postingUrl": "https://jobs.smartrecruiters.com/Acme/9",
                  "jobAd": {"sections": {"jobDescription": {"text": "<p>Blue Card support</p>"}}}}
        job = run_feed(careers.smartrecruiters, {"name": "Acme", "id": "Acme"}, [listing, detail])[0]
        self.assertEqual((job.country, job.description, job.url), ("DE", "Blue Card support", detail["postingUrl"]))

    def test_workable(self):
        payload = {"jobs": [{"title": "Nurse", "shortcode": "S1", "url": "https://apply.workable.com/acme/j/S1",
                             "published_on": NOW.date().isoformat(), "city": "Dublin", "country": "Ireland",
                             "description": "<p>Sponsorship available</p>"}]}
        job = run_feed(careers.workable, {"name": "Acme", "id": "acme"}, [payload])[0]
        self.assertEqual(job.country, "IE")

    def test_recruitee(self):
        payload = {"offers": [{"id": 5, "title": "PM", "published_at": ISO_NOW, "location": "Amsterdam",
                               "country_code": "NL", "careers_url": "https://acme.recruitee.com/o/pm",
                               "description": "<p>a</p>", "requirements": "<p>b</p>"}]}
        job = run_feed(careers.recruitee, {"name": "Acme", "id": "acme"}, [payload])[0]
        self.assertEqual((job.country, job.description), ("NL", "a b"))

    def test_personio(self):
        xml = f"""<workzag-jobs><position><id>77</id><office>Munich</office><name>Lab Technician</name>
          <createdAt>{ISO_NOW}</createdAt><jobDescriptions><jobDescription><name>About</name>
          <value>&lt;p&gt;Visa sponsorship is available&lt;/p&gt;</value></jobDescription></jobDescriptions>
          </position></workzag-jobs>""".encode()
        job = run_feed(careers.personio, {"name": "Acme", "id": "acme"}, [xml], method="get")[0]
        self.assertEqual((job.country, job.url), ("DE", "https://acme.jobs.personio.de/job/77"))
        self.assertIn("Visa sponsorship", job.description)

    def test_workday(self):
        listing = {"jobPostings": [
            {"title": "Scientist", "externalPath": "/job/Cambridge/Scientist_R1", "locationsText": "Cambridge, UK", "postedOn": "Posted 2 Days Ago"},
            {"title": "Old", "externalPath": "/job/x", "locationsText": "London", "postedOn": "Posted 30+ Days Ago"},
            {"title": "US", "externalPath": "/job/y", "locationsText": "Boston, United States", "postedOn": "Posted Today"},
        ]}
        detail = {"jobPostingInfo": {"jobReqId": "R1", "jobDescription": "<p>Hi</p>", "location": "Cambridge, UK",
                                     "externalUrl": "https://acme.wd3.myworkdayjobs.com/Careers/job/R1",
                                     "country": {"descriptor": "United Kingdom"}}}
        emp = {"name": "Acme", "host": "acme.wd3.myworkdayjobs.com", "site": "Careers"}
        with mock.patch.object(careers.http, "post_json", return_value=listing), \
             mock.patch.object(careers.http, "get_json", return_value=detail) as get:
            jobs = list(careers.workday(emp, CUTOFF))
        self.assertEqual([(j.source_id, j.country) for j in jobs], [("R1", "GB")])
        self.assertEqual(get.call_count, 1)  # no detail call for the old or US roles

    def test_one_broken_board_does_not_stop_others(self):
        report = {}
        ok = {"jobs": [{"id": 1, "title": "Engineer", "first_published": ISO_NOW,
                        "location": {"name": "London"}, "absolute_url": "u", "content": ""}]}
        employers = [{"name": "Broken", "ats": "greenhouse", "id": "nope"},
                     {"name": "Typo", "ats": "taleo", "id": "t"},
                     {"name": "Paused", "ats": "greenhouse", "id": "p", "enabled": False},
                     {"name": "Works", "ats": "greenhouse", "id": "ok"}]
        def fake_get_json(url, **kw):
            if "/boards/nope/" in url:
                raise OSError("404")
            return ok
        with mock.patch.object(careers.http, "get_json", side_effect=fake_get_json):
            jobs = list(careers.career_sites(7, employers, report))
        self.assertEqual([j.company for j in jobs], ["Works"])
        self.assertEqual(report["ok"], 1)
        self.assertEqual(len(report["failed"]), 2)


    def test_time_budget_stops_paging_and_keeps_results(self):
        report = {}
        page = {"jobPostings": [{"title": f"Role {i}", "externalPath": f"/job/{i}", "locationsText": "London, UK",
                                 "postedOn": "Posted Today"} for i in range(20)]}
        detail = {"jobPostingInfo": {"jobReqId": "R", "location": "London, UK"}}
        emp = {"name": "Big Co", "ats": "workday", "host": "big.wd3.myworkdayjobs.com", "site": "Careers"}
        with mock.patch.object(careers.http, "post_json", return_value=page) as post, \
             mock.patch.object(careers.http, "get_json", return_value=detail):
            jobs = list(careers.career_sites(7, [emp], report, budget_s=0))
        self.assertEqual(jobs, [])
        self.assertEqual(post.call_count, 0)
        self.assertEqual((report["ok"], report["slow"]), (1, ["Big Co"]))


class AgencyFilterTests(unittest.TestCase):
    def setUp(self):
        self.f = AgencyFilter.load(CONFIG / "agencies.json")

    def test_agencies(self):
        for company, text in [("Hays Specialist Recruitment", ""), ("Michael Page UK", ""),
                              ("Smith Recruitment Ltd", ""), ("Acme", "Our client is a leading bank"),
                              ("Acme", "Acme is acting as an employment agency for this role")]:
            self.assertTrue(self.f.is_agency(company, text), company)

    def test_employers(self):
        for company, text in [("Barts Health NHS Trust", ""), ("Reed Smith", ""), ("Deloitte", "work with our client teams"),
                              ("NHS Professionals", "locum shifts"), ("University of Leeds", "")]:
            self.assertFalse(self.f.is_agency(company, text), company)


class DirectPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.index = sponsors.SponsorIndex()
        self.index.add(sponsors.SponsorEntry("Monzo Bank Limited", "UK Home Office", routes={"Skilled Worker"}))
        self.tiers = classify.TierRules.load(CONFIG / "company_tiers.json")

    def job(self, **kw):
        base = dict(source="X", source_id="1", title="Backend Engineer", company="Monzo", location="London",
                    country="GB", url="https://e/1", posted_at=NOW - timedelta(hours=3), description="")
        base.update(kw)
        return Job(**base)

    def test_prefix_lookup_only_for_career_sites(self):
        stats = {}
        out = pipeline.enrich([self.job(channel="career_site"), self.job(source_id="2", title="Analyst", channel="aggregator")],
                              self.index, self.tiers, contacts.ContactBook({}), 7, AgencyFilter.load(CONFIG / "agencies.json"), stats)
        self.assertEqual([(j.title, j.sponsorship) for j in out], [("Backend Engineer", "licensed_sponsor")])

    def test_career_site_beats_job_board_copy(self):
        board = self.job(source="Adzuna", source_id="a", company="Monzo Bank Ltd", channel="aggregator",
                         description="Visa sponsorship available. hr@monzo.com")
        direct = self.job(source="Monzo careers", source_id="d", channel="career_site")
        out = pipeline.enrich([board, direct], self.index, self.tiers, contacts.ContactBook({}), 7)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].channel, "career_site")
        self.assertEqual(out[0].contacts[0]["email"], "hr@monzo.com")  # email kept from the board copy

    def test_agency_adverts_removed_and_counted(self):
        stats = {}
        agency = self.job(company="Hays", channel="aggregator", description="Visa sponsorship available")
        out = pipeline.enrich([agency], self.index, self.tiers, contacts.ContactBook({}), 7,
                              AgencyFilter.load(CONFIG / "agencies.json"), stats)
        self.assertEqual((out, stats["agency_removed"]), ([], 1))

    def test_non_european_dropped(self):
        out = pipeline.enrich([self.job(country="US", channel="career_site"), self.job(country="", channel="career_site")],
                              self.index, self.tiers, contacts.ContactBook({}), 7)
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
