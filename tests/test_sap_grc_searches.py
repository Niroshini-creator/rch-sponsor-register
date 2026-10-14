import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from jobfeed import contacts, pipeline, sources, sponsors
from jobfeed.classify import TierRules
from jobfeed.models import Job

CONFIG = Path(__file__).resolve().parent.parent / "config"


class SapGrcSearchTests(unittest.TestCase):
    def test_adzuna_searches_sap_grc_without_the_sponsorship_word_and_early(self):
        searches = [(code, q, pages) for code, q, pages, *_ in sources._adzuna_searches()]
        sap = [(c, q, p) for c, q, p in searches if q.get("what_and") in sources.SAP_GRC_QUERIES]
        self.assertEqual([q["what_and"] for _, q, _ in sap], sources.SAP_GRC_QUERIES)
        self.assertTrue(all(c == "gb" and 1 <= p <= 2 and "sponsorship" not in q["what_and"] for c, q, p in sap))
        first_role = next(i for i, (_, q, _) in enumerate(searches) if q.get("what_and", "").startswith("sponsorship "))
        self.assertLess(searches.index(sap[-1]), first_role)      # ahead of the call budget running out
        self.assertGreaterEqual(sources.ADZUNA_MAX_CALLS, 260 + len(sources.SAP_GRC_QUERIES) * 2)

    def test_reed_searches_sap_grc(self):
        with mock.patch.dict("os.environ", {"REED_API_KEY": "k"}), mock.patch.object(sources.http, "get_json", return_value={"results": []}) as get:
            list(sources.reed(7))
        asked = {c.kwargs["params"]["keywords"] for c in get.call_args_list}
        self.assertTrue(set(sources.SAP_GRC_QUERIES) <= asked)

    def test_sap_grc_advert_from_a_licensed_sponsor_reaches_the_board_but_others_do_not(self):
        index = sponsors.SponsorIndex()
        index.add(sponsors.SponsorEntry("Acme Ltd", "UK Home Office", routes={"Skilled Worker"}))
        now = datetime.now(timezone.utc)

        def job(company, sid):
            return Job(source="Reed", source_id=sid, title="SAP GRC Access Control Consultant", company=company, location="Leeds", country="GB",
                       url=f"https://x/{sid}", posted_at=now, description="SAP GRC ARM ARA segregation of duties.", salary="£55,000")
        out = pipeline.enrich([job("Acme Ltd", "1"), job("Nowhere Ltd", "2")], index, TierRules.load(CONFIG / "company_tiers.json"),
                              contacts.ContactBook({}), 7)
        self.assertEqual([(j.company, j.sponsorship) for j in out], [("Acme Ltd", "licensed_sponsor")])

    def test_such_a_role_is_a_tier_one_match_for_an_sap_grc_candidate(self):
        from candidateboard import match
        profile = json.loads((CONFIG.parent / "candidates" / "profiles" / "sample-candidate.json").read_text())
        ev = match.Matcher(profile).evaluate({"title": "SAP GRC Access Control Consultant", "description": "SAP GRC ARM ARA segregation of duties " * 20,
                                              "company": "Acme Ltd", "country": "GB", "sponsorship": "licensed_sponsor", "salary": "55,000"})
        self.assertEqual((ev["tier"], ev["family"]), (1, "sap_security_grc"))
        self.assertGreaterEqual(ev["match"], 80)


class PublicSectorSearchTests(unittest.TestCase):
    def test_main_feed_searches_nhs_and_universities_for_role_types_as_well_as_sponsorship(self):
        for key, name, base in (("nhs_jobs", "nhs_jobs", sources.NHS_KEYWORDS), ("jobs_ac_uk", "jobs_ac_uk", sources.JOBS_AC_UK_QUERIES)):
            with mock.patch.object(sources, name, return_value=iter(())) as fn:
                list(sources.SOURCES[key](7))
            asked = fn.call_args.args[1]
            self.assertEqual(tuple(asked[:len(base)]), tuple(base))                    # the sponsorship searches still run first
            self.assertTrue({"business analyst", "sap", "grc", "information governance"} <= set(asked), key)

    def test_candidate_searches_keep_their_own_keywords(self):
        from candidateboard import sources as cs
        with mock.patch.object(cs.shared, "nhs_jobs", return_value=iter(())) as fn:
            list(cs.nhs(7, ["sap grc"]))
        self.assertEqual(fn.call_args.kwargs["keywords"], ("sap grc",))


if __name__ == "__main__":
    unittest.main()
