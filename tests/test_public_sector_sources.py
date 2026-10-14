import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from jobfeed import contacts, pipeline, sources, sponsors
from jobfeed.classify import TierRules

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
        self.assertEqual([(j.source_id, j.company, j.register_name, j.country) for j in jobs], [("1", "Coventry City Council", "Coventry City Council", "GB")])
        asked = {c.kwargs["params"]["keywords"] for c in get.call_args_list}
        self.assertIn("Home Office", asked)
        self.assertTrue(all(c.kwargs["params"]["postedByDirectEmployer"] == "true" for c in get.call_args_list))


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


if __name__ == "__main__":
    unittest.main()
