import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jobfeed import classify, contacts, pipeline, sources, sponsors
from jobfeed.models import Job
from jobfeed.text import normalise_company, parse_date

CONFIG = Path(__file__).resolve().parent.parent / "config"
NOW = datetime.now(timezone.utc)


def make_job(**kw) -> Job:
    base = dict(source="Test", source_id="1", title="Software Engineer", company="Acme Ltd",
                location="London", country="GB", url="https://example.org/job/1",
                posted_at=NOW - timedelta(days=1), description="")
    base.update(kw)
    return Job(**base)


class TextTests(unittest.TestCase):
    def test_normalise_company(self):
        self.assertEqual(normalise_company("The Acme Group Ltd."), "acme")
        self.assertEqual(normalise_company("Smith & Jones LLP"), "smith jones")
        self.assertEqual(normalise_company("Siemens AG"), normalise_company("SIEMENS"))

    def test_parse_date_formats(self):
        for value in ("2026-09-29T10:00:00Z", "29/09/2026", "Tue, 29 Sep 2026 10:00:00 GMT", 1790676000):
            self.assertIsNotNone(parse_date(value), value)
        self.assertIsNone(parse_date("not a date"))


class SponsorshipSignalTests(unittest.TestCase):
    def test_positive(self):
        for text in ("Visa sponsorship is available for this role.",
                     "We are able to offer Skilled Worker sponsorship.",
                     "Applications from job seekers who require current Skilled worker sponsorship to work "
                     "in the UK are welcome and will be considered alongside all other applications.",
                     "Relocation and visa support provided. EU Blue Card eligible."):
            self.assertEqual(classify.sponsorship_signal(text), "positive", text)

    def test_negative_beats_positive_words(self):
        for text in ("We are unable to offer visa sponsorship.",
                     "No sponsorship available for this position.",
                     "Candidates must have the right to work in the UK without sponsorship.",
                     "Sponsorship is not available."):
            self.assertEqual(classify.sponsorship_signal(text), "negative", text)

    def test_silent(self):
        self.assertEqual(classify.sponsorship_signal("Great team, hybrid working."), "")


class ClassifierTests(unittest.TestCase):
    def test_sector(self):
        cases = {
            "Leeds Teaching Hospitals NHS Trust": "NHS & Healthcare",
            "University of Manchester": "University & Research Institute",
            "Oak Primary School": "School & College",
            "Birmingham City Council": "Public Sector & Government",
            "Hays Recruitment Agency": "Private Sector",
            "Acme Ltd": "Private Sector",
        }
        for company, sector in cases.items():
            self.assertEqual(classify.classify_sector(make_job(company=company)), sector, company)

    def test_domain(self):
        cases = {
            "Senior Backend Engineer": "Technical & Engineering",
            "Staff Nurse Band 5": "Healthcare & Clinical",
            "Research Associate in Genomics": "Science & Research",
            "Teacher of Mathematics": "Teaching & Academic",
            "Programme Manager": "Management & Business",
            "Management Accountant": "Finance & Legal",
        }
        for title, domain in cases.items():
            self.assertEqual(classify.classify_domain(make_job(title=title)), domain, title)

    def test_tiers(self):
        rules = classify.TierRules.load(CONFIG / "company_tiers.json")
        self.assertEqual(rules.classify(make_job(company="Deloitte LLP")), (1, "large"))
        self.assertEqual(rules.classify(make_job(company="Monzo Bank Ltd")), (3, "unknown"))  # not an exact name
        self.assertEqual(rules.classify(make_job(company="Monzo")), (2, "large"))
        self.assertEqual(rules.classify(make_job(company="Guy's and St Thomas' NHS Foundation Trust")), (1, "large"))
        self.assertEqual(rules.classify(make_job(company="Tiny Startup",
                                                 description="Join our team of 12 people")), (3, "small"))
        self.assertEqual(rules.classify(make_job(company="Mid Co",
                                                 description="We have 120 employees")), (3, "medium"))


class ContactTests(unittest.TestCase):
    def test_extract(self):
        found = contacts.extract_advert_emails(
            "Informal enquiries to jane.doe@trust.nhs.uk or recruitment@trust.nhs.uk. "
            "Do not reply to noreply@trust.nhs.uk.")
        self.assertEqual([c["email"] for c in found], ["jane.doe@trust.nhs.uk", "recruitment@trust.nhs.uk"])
        self.assertEqual(found[0]["type"], "named contact")
        self.assertEqual(found[1]["type"], "recruitment inbox")

    def test_verified_first(self):
        book = contacts.ContactBook({"acme": [{"email": "hr@acme.com", "type": "recruitment inbox",
                                               "provenance": "verified"}]})
        got = book.contacts_for(make_job(description="Email bob.smith@acme.com"))
        self.assertEqual([c["email"] for c in got], ["bob.smith@acme.com", "hr@acme.com"])


class SponsorIndexTests(unittest.TestCase):
    def test_trading_as_and_routes(self):
        idx = sponsors.SponsorIndex()
        idx.add(sponsors.SponsorEntry("Acme Holdings Ltd T/A Rocket Labs", "UK Home Office", routes={"Skilled Worker"}))
        idx.add(sponsors.SponsorEntry("Acme Holdings Ltd", "UK Home Office", routes={"Global Business Mobility"}))
        self.assertEqual(idx.lookup("Rocket Labs").register, "UK Home Office")
        self.assertEqual(idx.lookup("ACME HOLDINGS LIMITED").routes, {"Skilled Worker", "Global Business Mobility"})
        self.assertIsNone(idx.lookup("Unknown Co"))

    def test_uk_csv(self):
        csv_text = ('"Organisation Name","Town/City","County","Type & Rating","Route"\n'
                    '"Acme Ltd","London","","Worker (A rating)","Skilled Worker"\n')
        idx = sponsors.SponsorIndex()
        with mock.patch.object(sponsors, "_uk_csv_text", return_value=csv_text):
            sponsors.load_uk_register(idx)
        self.assertEqual(idx.lookup("Acme").rating, "Worker (A rating)")

    def test_nl_html(self):
        page = "<table><tr><th>Name</th></tr><tr><td>Adyen N.V.</td><td>34259528</td></tr></table>"
        idx = sponsors.SponsorIndex()
        with mock.patch.object(sponsors.http, "get_text", return_value=page):
            sponsors.load_nl_register(idx)
        self.assertEqual(idx.lookup("Adyen").register, "NL IND")


class EnrichTests(unittest.TestCase):
    def setUp(self):
        self.index = sponsors.SponsorIndex()
        self.index.add(sponsors.SponsorEntry("Acme Ltd", "UK Home Office", routes={"Skilled Worker"}))
        self.tiers = classify.TierRules.load(CONFIG / "company_tiers.json")
        self.book = contacts.ContactBook({})

    def run_enrich(self, jobs):
        return pipeline.enrich(jobs, self.index, self.tiers, self.book, days=7)

    def test_rules(self):
        jobs = [
            make_job(source_id="old", posted_at=NOW - timedelta(days=8), description="Visa sponsorship available"),
            make_job(source_id="neg", description="We cannot offer sponsorship"),
            make_job(source_id="licensed", description="Great role"),
            make_job(source_id="silent-unlicensed", company="Other Co", title="Analyst", description="Great role"),
            make_job(source_id="confirmed", company="Other Co", title="Nurse",
                     description="Visa sponsorship available. Contact a.b@other.co.uk"),
            make_job(source_id="eu-licensed-uk", country="DE", title="Designer", description="Great role"),
            make_job(source_id="us", country="US", title="Chemist", description="Visa sponsorship available"),
        ]
        out = {j.source_id: j for j in self.run_enrich(jobs)}
        self.assertEqual(set(out), {"licensed", "confirmed"})
        self.assertEqual(out["licensed"].sponsorship, "licensed_sponsor")
        self.assertEqual(out["licensed"].sponsor_routes, ["Skilled Worker"])
        self.assertEqual(out["confirmed"].sponsorship, "confirmed")
        self.assertEqual(out["confirmed"].contacts[0]["email"], "a.b@other.co.uk")
        self.assertEqual(out["confirmed"].domain, "Healthcare & Clinical")

    def test_dedupe_prefers_contacts(self):
        a = make_job(source="Reed", source_id="a", description="Visa sponsorship available")
        b = make_job(source="Adzuna", source_id="b", description="Visa sponsorship available. jobs@acme.com")
        out = self.run_enrich([a, b])
        self.assertEqual([j.source_id for j in out], ["b"])

    def test_to_dict_is_json(self):
        out = self.run_enrich([make_job(description="Visa sponsorship available " + "x " * 500)])
        data = out[0].to_dict()
        json.dumps(data)
        self.assertLessEqual(len(data["description"]), 401)
        self.assertNotIn("source_says_sponsorship", data)


class SourceParserTests(unittest.TestCase):
    """Offline fixtures for each connector's response format."""

    def test_arbeitnow(self):
        payload = {"data": [{"slug": "x", "company_name": "Rocket GmbH", "title": "Data Engineer",
                             "description": "<p>Hi</p>", "url": "https://a/x", "location": "Berlin",
                             "created_at": int(NOW.timestamp()), "job_types": ["full time"],
                             "visa_sponsorship": True}], "links": {"next": None}}
        with mock.patch.object(sources.http, "get_json", return_value=payload):
            jobs = list(sources.arbeitnow(7))
        self.assertEqual((jobs[0].country, jobs[0].source_says_sponsorship, jobs[0].description),
                         ("DE", True, "Hi"))

    def test_nhs_xml(self):
        xml = f"""<vacancies><vacancy><id>C9-1</id><title>Staff Nurse</title>
            <description>Sponsorship available</description><employer>Barts Health NHS Trust</employer>
            <salary>£30,000</salary><postDate>{NOW.date().isoformat()}</postDate>
            <url>https://www.jobs.nhs.uk/candidate/jobadvert/C9-1</url>
            <locations><location>London</location></locations></vacancy></vacancies>""".encode()
        with mock.patch.object(sources.http, "get", side_effect=[xml, b"<vacancies/>"] * 3):
            jobs = list(sources.nhs_jobs(7))
        self.assertEqual(jobs[0].company, "Barts Health NHS Trust")
        self.assertEqual(jobs[0].location, "London")

    def test_nhs_unexpected_response_is_reported(self):
        html = b"<html><body><p>Search moved</p></body></html>"
        with mock.patch.object(sources.http, "get", return_value=html):
            with self.assertRaisesRegex(RuntimeError, "no <vacancy> elements.*root <html>"):
                list(sources.nhs_jobs(7))

    def test_rss_failure_is_isolated(self):
        rss = f"""<rss><channel><item><title>Lecturer in Physics - University of Bath</title>
            <link>https://j/1</link><pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
            <description>Visa sponsorship available</description></item></channel></rss>""".encode()
        feeds = [{"name": "broken", "url": "https://bad"}, {"name": "jobs.ac.uk", "url": "https://ok"}]
        report = {}
        with mock.patch.object(sources.http, "get", side_effect=[OSError("down"), rss]):
            jobs = list(sources.rss_feeds(7, feeds, report))
        self.assertEqual((jobs[0].title, jobs[0].company), ("Lecturer in Physics", "University of Bath"))
        self.assertEqual((report["ok"], report["failed"]), (1, ["broken: down"]))

    def test_keyed_sources_skip_without_keys(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            for fn in (sources.adzuna, sources.reed):
                with self.assertRaises(sources.SkipSource):
                    list(fn(7))


if __name__ == "__main__":
    unittest.main()
