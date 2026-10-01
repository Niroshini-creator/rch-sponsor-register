"""Job roles, new countries and regions, English-speaking roles, PSW / OPT routes and hiring contacts."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from jobfeed import classify, contacts, pipeline, sources, sponsors
from jobfeed.models import Job

CONFIG = Path(__file__).resolve().parent.parent / "config"
NOW = datetime.now(timezone.utc)


def make_job(**kw) -> Job:
    base = dict(source="Test", source_id="1", title="Software Engineer", company="Acme Ltd",
                location="London", country="GB", url="https://example.org/job/1",
                posted_at=NOW - timedelta(days=1), description="")
    base.update(kw)
    return Job(**base)


class RoleTests(unittest.TestCase):
    def test_roles(self):
        cases = {
            "Senior Data Analyst": "Data Analyst",
            "Power BI Developer": "Data Analyst",
            "Business Analyst - Payments": "Business Analyst",
            "IT Support Technician": "IT Support",
            "2nd Line Service Desk Analyst": "IT Support",
            "Application Support Analyst": "Application Support",
            "Biomedical Scientist Band 5": "Medical Laboratory",
            "Medical Laboratory Technician": "Medical Laboratory",
            "Logistics Coordinator": "Logistics & Supply Chain",
            "Procurement Manager": "Logistics & Supply Chain",
            "Data Scientist": "Data Science & AI",
            "Machine Learning Engineer": "Data Science & AI",
            "Senior DevOps Engineer": "DevOps & Cloud",
            "Site Reliability Engineer": "DevOps & Cloud",
            "Java Developer": "Software Developer",
            "Senior Backend Engineer": "Software Developer",
            "Mechanical Engineer": "Engineering",
            "Management Accountant": "Finance & Accounting",
            "HR Business Partner": "HR & Recruitment",
            "Digital Marketing Executive": "Digital Marketing",
            "SEO Specialist": "Digital Marketing",
            "B1 Licensed Aircraft Engineer": "Aviation",
            "First Officer A320": "Aviation",
            "IT Project Manager": "Project Manager",
            "Scrum Master": "Project Manager",
            "Teacher of Mathematics": "Other",
            "Speech-Language Pathologist": "Other",
        }
        for title, role in cases.items():
            self.assertEqual(classify.classify_role(make_job(title=title)), role, title)
        self.assertEqual(classify.ROLES[-1], "Other")


class RegionAndLanguageTests(unittest.TestCase):
    def test_region(self):
        self.assertEqual(classify.classify_region(make_job(location="Glasgow, UK")), "Scotland")
        self.assertEqual(classify.classify_region(make_job(location="London", company="NHS Lothian")), "Scotland")
        self.assertEqual(classify.classify_region(make_job(location="Manchester")), "")
        self.assertEqual(classify.classify_region(make_job(location="Dubai, UAE", country="AE")), "Dubai")

    def test_country_words(self):
        for text, code in [("Dubai, United Arab Emirates", "AE"), ("Espoo, Finland", "FI"), ("Kraków", "PL"),
                           ("Luxembourg", "LU"), ("Uppsala", "SE"), ("San Francisco, CA", "US"),
                           ("Amstelveen", "NL"), ("Bilbao", "ES"), ("Inverness", "GB")]:
            self.assertEqual(sources._guess_country(text, default=""), code, text)

    def test_english(self):
        english = "You will join our platform team in Amsterdam and work with engineers across Europe on the product."
        self.assertTrue(classify.classify_english(make_job(country="NL", description=english)))
        self.assertTrue(classify.classify_english(make_job(country="NL", description=english + " Dutch is a plus.")))
        self.assertFalse(classify.classify_english(make_job(country="NL", description=english + " Fluent Dutch is required.")))
        self.assertFalse(classify.classify_english(make_job(country="DE", description=english + " Sehr gute Deutschkenntnisse; "
                                                            "German (C1) needed.")))
        dutch = "Wij zoeken een collega voor ons team in Utrecht die graag werkt met data en klanten van het bedrijf."
        self.assertFalse(classify.classify_english(make_job(country="NL", description=dutch)))


class EarlyCareerTests(unittest.TestCase):
    def test_stated(self):
        self.assertEqual(classify.classify_early_career(
            make_job(description="Graduate visa holders are welcome to apply.")), "stated")
        self.assertEqual(classify.classify_early_career(
            make_job(country="US", description="Candidates on STEM OPT are encouraged to apply.")), "stated")
        self.assertEqual(classify.classify_early_career(
            make_job(country="US", description="You may opt out of the pension scheme.")), "")
        self.assertEqual(classify.classify_early_career(
            make_job(country="US", description="We do not accept OPT candidates.")), "")
        capital_one = ("At this time, Capital One will not sponsor a new applicant for employment authorization, or offer "
                       "any immigration related support for this position (i e H1B, F-1 OPT, F-1 STEM OPT, F-1 CPT, J-1).")
        self.assertEqual(classify.classify_early_career(make_job(country="US", description=capital_one)), "")

    def test_likely_needs_sponsor_and_entry_level(self):
        job = make_job(title="Graduate Software Engineer")
        self.assertEqual(classify.classify_early_career(job), "")
        job.sponsorship = "licensed_sponsor"
        self.assertEqual(classify.classify_early_career(job), "likely")
        job.title = "Senior Software Engineer"
        self.assertEqual(classify.classify_early_career(job), "")
        us = make_job(country="US", title="New Grad Software Engineer", description="We are an E-Verify employer.")
        self.assertEqual(classify.classify_early_career(us), "likely")
        self.assertEqual(classify.classify_early_career(make_job(country="DE", title="Graduate Engineer",
                                                                 description="Graduate visa")), "")


class SponsorshipWordingTests(unittest.TestCase):
    def test_new_wording(self):
        for text in ("We will help you with your work permit and relocation.",
                     "H-1B sponsorship is available for this role.",
                     "We are happy to sponsor your H-1B visa."):
            self.assertEqual(classify.sponsorship_signal(text), "positive", text)
        for text in ("We are unable to provide H-1B sponsorship.",
                     "Must be a US citizen.",
                     "We will not sponsor immigration sponsorship for this role."):
            self.assertEqual(classify.sponsorship_signal(text), "negative", text)


class EnrichNewCountriesTests(unittest.TestCase):
    def setUp(self):
        self.index = sponsors.SponsorIndex()
        self.index.add(sponsors.SponsorEntry("Acme Ltd", "UK Home Office", routes={"Skilled Worker"}))
        self.index.add(sponsors.SponsorEntry("ACME INC", "US H-1B", routes={"H-1B"}))
        self.tiers = classify.TierRules.load(CONFIG / "company_tiers.json")

    def run_enrich(self, jobs):
        return {j.source_id: j for j in pipeline.enrich(jobs, self.index, self.tiers, contacts.ContactBook({}), days=7)}

    def test_countries_and_routes(self):
        out = self.run_enrich([
            make_job(source_id="us-h1b", country="US", location="Austin, TX", title="Data Analyst I"),
            make_job(source_id="us-other", country="US", company="Other Co", title="Data Analyst"),
            make_job(source_id="psw-only", company="Other Co", title="Graduate Analyst",
                     description="We cannot offer sponsorship, but Graduate visa holders are welcome."),
            make_job(source_id="no", company="Other Co", description="We cannot offer sponsorship."),
            make_job(source_id="se", country="SE", company="Nordic AB", title="Data Scientist",
                     description="We help you with your work permit. You will work in English with our team."),
            make_job(source_id="scot", location="Edinburgh", title="Business Analyst"),
        ])
        self.assertEqual(set(out), {"us-h1b", "psw-only", "se", "scot"})
        self.assertEqual((out["us-h1b"].sponsorship, out["us-h1b"].sponsor_register), ("licensed_sponsor", "US H-1B"))
        self.assertEqual((out["us-h1b"].role, out["us-h1b"].early_career, out["us-h1b"].english), ("Data Analyst", "likely", True))
        self.assertEqual((out["psw-only"].sponsorship, out["psw-only"].early_career), ("graduate_route", "stated"))
        self.assertEqual((out["se"].sponsorship, out["se"].english, out["se"].role), ("confirmed", True, "Data Science & AI"))
        self.assertEqual(out["scot"].region, "Scotland")
        data = out["scot"].to_dict()
        self.assertNotIn("advert_contacts", data)
        self.assertEqual(data["role"], "Business Analyst")

    def test_same_name_on_two_registers(self):
        self.assertEqual(self.index.lookup("Acme", "US").register, "US H-1B")
        self.assertEqual(self.index.lookup("Acme", "GB").register, "UK Home Office")

    def test_directory(self):
        jobs = list(self.run_enrich([
            make_job(source_id="a", title="Graduate Engineer", description="Visa sponsorship available"),
            make_job(source_id="b", company="Small Co", title="Junior Data Analyst",
                     description="Visa sponsorship available. We are a team of 20 people."),
        ]).values())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "early.json"
            path.write_text(json.dumps({"employers": [
                {"name": "Acme", "country": "GB", "programme": "Graduate scheme"},
                {"name": "Acme", "country": "US", "register_name": ["Nope LLC", "Acme Inc"]},
                {"name": "Missing Co", "country": "US"}]}))
            rows = {(r["name"], r["country"]): r for r in pipeline.build_directory(jobs, self.index, self.tiers, path)}
        self.assertEqual((rows["Acme", "GB"]["on_register"], rows["Acme", "GB"]["early_career_roles"]), (True, 1))
        self.assertEqual((rows["Acme", "US"]["register"], rows["Acme", "US"]["route"]), ("US H-1B", "OPT"))
        self.assertFalse(rows["Missing Co", "US"]["on_register"])
        self.assertTrue(rows["Missing Co", "US"]["register_checked"])
        empty = pipeline.build_directory([], sponsors.SponsorIndex(), self.tiers, CONFIG / "early_career_employers.json")
        self.assertFalse(any(r["register_checked"] for r in empty))
        self.assertEqual((rows["Small Co", "GB"]["curated"], rows["Small Co", "GB"]["size"]), (False, "small"))


class ContactDetailTests(unittest.TestCase):
    def test_named_contact_with_role_and_phone(self):
        found = contacts.extract_advert_emails(
            "For informal enquiries please contact Dr Jane Smith, Head of Biochemistry, on 01234 567 890 "
            "or jane.smith@trust.nhs.uk. Applications to recruitment@trust.nhs.uk.")
        self.assertEqual(found[0], {"email": "jane.smith@trust.nhs.uk", "type": "named contact", "provenance": "advert",
                                    "name": "Dr Jane Smith", "role": "Head of Biochemistry", "phone": "01234 567 890"})
        self.assertNotIn("name", found[1])  # the inbox is not Dr Smith's

    def test_team_is_not_a_person(self):
        found = contacts.extract_advert_emails("Contact the Recruitment Team at jobs@uni.ac.uk")
        self.assertNotIn("name", found[0])

    def test_published_contacts(self):
        job = make_job(advert_contacts=[{"name": "Anna Svensson", "role": "Rekryterande chef",
                                         "email": "anna@uu.se", "phone": "+46 18 471 00 00"},
                                        {"email": "noreply@uu.se"}])
        got = contacts.ContactBook({}).contacts_for(job)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["name"], got[0]["phone"], got[0]["provenance"]),
                         ("Anna Svensson", "+46 18 471 00 00", "advert"))


class NewSourceTests(unittest.TestCase):
    def test_jobtech_sweden(self):
        payload = {"hits": [{
            "id": "29", "headline": "Data Analyst", "publication_date": NOW.isoformat(),
            "webpage_url": "https://arbetsformedlingen.se/platsbanken/annonser/29",
            "employer": {"name": "Uppsala universitet"}, "workplace_address": {"municipality": "Uppsala", "region": "Uppsala län"},
            "description": {"text": "Visa sponsorship available."}, "employment_type": {"label": "Vanlig anställning"},
            "application_contacts": [{"name": "Anna Svensson", "description": "Head of unit", "email": "anna@uu.se"}],
        }]}
        with mock.patch.object(sources.http, "get_json", return_value=payload):
            jobs = list(sources.jobtech_sweden(7))
        job = jobs[0]
        self.assertEqual((job.country, job.channel, job.company, job.location),
                         ("SE", "official", "Uppsala universitet", "Uppsala, Uppsala län"))
        self.assertEqual(job.advert_contacts[0]["name"], "Anna Svensson")

    def test_adzuna_respects_call_budget(self):
        with mock.patch.dict("os.environ", {"ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": "b"}), \
             mock.patch.object(sources, "ADZUNA_MAX_CALLS", 3), mock.patch.object(sources, "ADZUNA_PAUSE", 0), \
             mock.patch.object(sources.http, "get_json", return_value={"results": []}) as get:
            list(sources.adzuna(7))
        self.assertEqual(get.call_count, 3)
        self.assertIn("/gb/", get.call_args_list[0].args[0])

    def test_teaching_vacancies_salary(self):
        self.assertEqual(sources._schema_salary(
            {"currency": "GBP", "value": {"minValue": 30000, "maxValue": 40000, "unitText": "YEAR"}}), "£30,000 – 40,000 a year")

    def test_us_h1b_register(self):
        data = ("Fiscal Year\tEmployer (Petitioner) Name\tInitial Approval\tContinuing Approval\n"
                "2025\tACME INC\t3\t0\n2025\tDENIED CO\t0\t0\n")
        idx = sponsors.SponsorIndex()
        with mock.patch.object(sponsors, "_us_h1b_text", return_value=data):
            sponsors.load_us_h1b(idx)
        self.assertEqual(idx.lookup("Acme Inc").routes, {"H-1B"})
        self.assertIsNone(idx.lookup("Denied Co"))
        self.assertEqual(sponsors._decode("a,b\n".encode("utf-16")), "a,b\n")


if __name__ == "__main__":
    unittest.main()
