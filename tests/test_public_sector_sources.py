import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from jobfeed import contacts, pipeline, sources, sponsors
from jobfeed.classify import TierRules
from jobfeed.models import Job

CONFIG = Path(__file__).resolve().parent.parent / "config"
NOW = datetime.now(timezone.utc)


def reed_result(job_id, employer, title="Business Analyst", date=None):
    return {"jobId": job_id, "jobTitle": title, "employerName": employer, "locationName": "Coventry", "jobUrl": f"https://www.reed.co.uk/jobs/{job_id}",
            "date": (date or NOW).strftime("%d/%m/%Y"), "jobDescription": "<p>Analyse things.</p>", "minimumSalary": 40000, "maximumSalary": 46000}


class PublicSectorEmployerTests(unittest.TestCase):
    def test_config_is_well_formed(self):
        rows = json.loads((CONFIG / "public_sector_employers.json").read_text())["employers"]
        names = [r["name"] for r in rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(r["name"].strip() and r["group"] for r in rows))
        self.assertTrue({"Home Office", "Coventry City Council", "Department for Work and Pensions"} <= set(names))
        sources_cfg = json.loads((CONFIG / "sources.json").read_text())
        self.assertTrue(sources_cfg["public_sector_employers"]["enabled"])
        self.assertIn("public_sector_employers", sources.SOURCES)

    def test_skipped_without_a_reed_key(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(sources.SkipSource):
            list(sources.public_sector_employers(7))

    def test_keeps_only_the_organisations_own_adverts_relabelled_to_its_register_name(self):
        payload = {"results": [reed_result(1, "Coventry City Council"), reed_result(2, "Coventry Building Society"),
                               reed_result(3, "Coventry City Council", date=datetime(2020, 1, 1, tzinfo=timezone.utc))]}
        with mock.patch.dict("os.environ", {"REED_API_KEY": "k"}), mock.patch.object(sources.http, "get_json", return_value=payload) as get:
            jobs = list(sources.public_sector_employers(7))
        self.assertEqual([(j.source_id, j.company, j.register_name, j.country, j.channel) for j in jobs], [("1", "Coventry City Council", "Coventry City Council", "GB", "official")])
        asked = {c.kwargs["params"]["keywords"] for c in get.call_args_list}
        self.assertIn("Home Office", asked)
        self.assertTrue(all(c.kwargs["params"]["postedByDirectEmployer"] == "true" for c in get.call_args_list))


class JobBoardExclusionTests(unittest.TestCase):
    def test_job_boards_and_recruiters_posing_as_employers_are_dropped(self):
        from jobfeed.agencies import AgencyFilter
        index = sponsors.SponsorIndex()
        for name in ("eFinancialCareers", "Salt Search", "Barclays Bank UK PLC"):
            index.add(sponsors.SponsorEntry(name, "UK Home Office", routes={"Skilled Worker"}))
        now = datetime.now(timezone.utc)

        def job(company, sid):
            return Job(source="Reed", source_id=sid, title="Business Analyst", company=company, location="London" + sid, country="GB",
                       url=f"https://x/{sid}", posted_at=now, description="Analyse things.")
        stats = {}
        out = pipeline.enrich([job("eFinancialCareers", "1"), job("Salt Search", "2"), job("Barclays Bank UK PLC", "3")], index,
                              TierRules.load(CONFIG / "company_tiers.json"), contacts.ContactBook({}), 7,
                              AgencyFilter.load(CONFIG / "agencies.json"), stats)
        self.assertEqual([j.company for j in out], ["Barclays Bank UK PLC"])
        self.assertEqual(stats["agency_removed"], 2)


class CouncilRssTests(unittest.TestCase):
    def test_council_feed_item_reaches_the_board_as_a_licensed_public_sector_job(self):
        rss = f"""<rss><channel><item><title>Senior Business Analyst</title><link>https://jobs.hull.example/123</link>
            <pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate><description>&lt;p&gt;Salary £45,000. Hull.&lt;/p&gt;</description></item></channel></rss>""".encode()
        feed = {"name": "Hull City Council", "url": "https://jobs.hull.example/rss", "employer": "Hull City Council", "location": "Hull",
                "register_name": "Hull City Council"}
        with mock.patch.object(sources.http, "get", return_value=rss):
            raw = list(sources.rss_feeds(7, [feed]))
        index = sponsors.SponsorIndex()
        index.add(sponsors.SponsorEntry("Hull City Council", "UK Home Office", routes={"Skilled Worker"}))
        out = pipeline.enrich(raw, index, TierRules.load(CONFIG / "company_tiers.json"), contacts.ContactBook({}), 7)
        self.assertEqual([(j.title, j.company, j.location, j.sponsorship, j.sector, j.channel) for j in out],
                         [("Senior Business Analyst", "Hull City Council", "Hull", "licensed_sponsor", "Public Sector & Government", "official")])

    def test_a_broken_feed_does_not_hide_the_others(self):
        good = f"""<rss><channel><item><title>Analyst</title><link>https://x/1</link><pubDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item></channel></rss>""".encode()

        def fake(url, **kw):
            if "bad" in url:
                raise OSError("down")
            return good
        with mock.patch.object(sources.http, "get", side_effect=fake):
            jobs = list(sources.rss_feeds(7, [{"name": "Bad", "url": "https://bad/rss"}, {"name": "Good", "url": "https://good/rss", "employer": "Good Council"}]))
        self.assertEqual([j.company for j in jobs], ["Good Council"])


class OverseasCoverageTests(unittest.TestCase):
    def test_australia_and_gulf_states_are_board_countries(self):
        from jobfeed import careers, classify
        self.assertTrue({"AU", "AE", "SA", "QA", "KW", "BH", "OM"} <= pipeline.COUNTRIES)
        self.assertEqual(pipeline.EMPLOYER_VISA_COUNTRIES, careers.GULF_STATES)
        self.assertIn("AU", classify.ENGLISH_SPEAKING_COUNTRIES)
        self.assertEqual((sources._guess_country("Riyadh", "GB"), sources._guess_country("Doha, Qatar", "GB"), sources._guess_country("Brisbane", "GB")),
                         ("SA", "QA", "AU"))
        self.assertEqual((careers._iso("Saudi Arabia"), careers._iso("Oman"), careers._iso("Australia")), ("SA", "OM", "AU"))

    def test_adzuna_searches_australia(self):
        searches = [(code, q) for code, q, *_ in sources._adzuna_searches()]
        self.assertIn(("au", {"what_phrase": "visa sponsorship"}), searches)
        self.assertEqual(sum(1 for c, _ in searches if c == "au"), 1 + len(sources.ROLE_QUERIES))
        self.assertEqual(sources.ADZUNA_COUNTRIES["au"], "AU")

    def test_gulf_job_is_kept_as_employer_visa_and_australian_job_needs_a_sponsorship_statement(self):
        now = datetime.now(timezone.utc)

        def job(country, sid, text=""):
            return Job(source="Reed", source_id=sid, title="Business Analyst", company="Acme Co", location={"SA": "Riyadh", "AU": "Sydney"}[country] + sid, country=country, url=f"https://x/{sid}",
                       posted_at=now, description=text, channel="career_site")
        out = pipeline.enrich([job("SA", "1"), job("AU", "2"), job("AU", "3", "Visa sponsorship is available.")], sponsors.SponsorIndex(),
                              TierRules.load(CONFIG / "company_tiers.json"), contacts.ContactBook({}), 7)
        self.assertEqual(sorted((j.country, j.sponsorship) for j in out), [("AU", "confirmed"), ("SA", "employer_visa")])


if __name__ == "__main__":
    unittest.main()
