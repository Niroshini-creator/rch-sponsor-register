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
        # The live advert's wording, with the dots in "i.e." that used to end the sentence early.
        live = ("At this time, Capital One will not sponsor a new applicant for employment authorization, or offer any "
                "immigration related support for this position (i.e. H1B, F-1 OPT, F-1 STEM OPT, F-1 CPT, J-1, TN, E-2, "
                "E-3, L-1 and O-1, or any EADs or other forms of work authorization that require immigration support "
                "from an employer).")
        self.assertEqual(classify.classify_early_career(make_job(country="US", description=live)), "")
        self.assertEqual(classify.classify_early_career(make_job(
            country="US", description="New grads on STEM OPT (e.g. CS majors) are welcome to apply.")), "stated")

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


class AcademicSourceTests(unittest.TestCase):
    """Fixtures shaped like the live pages, captured from the source probe on 2026-10-01."""

    def test_jobs_ac_uk(self):
        day = NOW.strftime("%d %b")
        search = f"""<div id="job-listings"><div class="j-search-result__result ie-border-left" data-advert-id="1">
            <a href="/job/DTC595/research-fellow">Research Fellow</a>
            <div><strong>Date Placed: </strong>{day}
            </div></div><div class="j-search-result__result ie-border-left" data-advert-id="2">
            <a href="/job/OLD1/old">Old</a><div><strong>Date Placed: </strong>01 Jan
            </div></div></div>"""
        advert = json.dumps({"@context": "https://schema.org", "@type": "JobPosting", "title": "Research Fellow",
                             "description": "<p>Visa sponsorship available. Enquiries: Name: Katie Muscat "
                                            "Email Address: katie.muscat@manchester.ac.uk</p>",
                             "datePosted": NOW.isoformat(),
                             "hiringOrganization": {"@type": "Organization", "name": "The University of Manchester"},
                             "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Manchester",
                                                                            "addressCountry": "United Kingdom"}}],
                             "baseSalary": {"currency": "GBP", "value": {"minValue": "37694", "maxValue": "46049",
                                                                         "unitText": "YEAR"}}})
        page = f'<html><script type="application/ld+json">{advert}</script></html>'
        empty = '<div id="job-listings"></div>'
        with mock.patch.object(sources.http, "get_text", side_effect=[search] + [empty] * 6 + [page]), \
             mock.patch.object(sources, "ACADEMIC_PAUSE", 0):
            jobs = list(sources.jobs_ac_uk(7))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job.company, job.country, job.channel, job.salary),
                         ("The University of Manchester", "GB", "official", "£37,694 – 46,049 a year"))
        got = contacts.ContactBook({}).contacts_for(job)
        self.assertEqual((got[0]["name"], got[0]["email"]), ("Katie Muscat", "katie.muscat@manchester.ac.uk"))

    def test_the_unijobs(self):
        stamp = NOW.strftime("%a, %d %b %Y %H:%M:%S +0000")
        rss = f"""<rss><channel>
            <item><title>UNIVERSITY COLLEGE BIRMINGHAM: Academic Skills Tutor</title>
            <description>£31,236 – £34,610 per annum: UNIVERSITY COLLEGE BIRMINGHAM: We seek a tutor ... Birmingham, United Kingdom</description>
            <link>https://www.timeshighereducation.com/unijobs/listing/415823/academic-skills-tutor/?TrackID=8</link>
            <pubDate>{stamp}</pubDate></item>
            <item><title>UNIVERSITY OF SYDNEY: Research Fellow</title>
            <description>UNIVERSITY OF SYDNEY: Research... Camperdown, Australia</description>
            <link>https://www.timeshighereducation.com/unijobs/listing/416122/research-fellow/?TrackID=8</link>
            <pubDate>{stamp}</pubDate></item></channel></rss>""".encode()
        with mock.patch.object(sources.http, "get", return_value=rss), \
             mock.patch.object(sources.http, "get_text", return_value="<main>Visa sponsorship available.</main>") as page, \
             mock.patch.object(sources, "ACADEMIC_PAUSE", 0):
            jobs = list(sources.the_unijobs(7))
        self.assertEqual(len(jobs), 1)  # Australia is outside the board's countries: no advert request
        self.assertEqual((jobs[0].company, jobs[0].title, jobs[0].country, jobs[0].salary),
                         ("University College Birmingham", "Academic Skills Tutor", "GB", "£31,236 – £34,610 per annum"))
        self.assertEqual(jobs[0].description, "Visa sponsorship available.")
        page.assert_called_once()

    def test_euraxess(self):
        posted = NOW.strftime("%-d %B %Y")
        search = f"""<ul><li><article class="ecl-content-item"><ul><li class="ecl-content-block__primary-meta-item">
            <a href="/partnering/organisations/profile/x" hreflang="en">Iquadrat Informatica SL</a></li>
            <li class="ecl-content-block__primary-meta-item">Posted on: {posted}</li></ul>
            <h3 class="ecl-content-block__title"><a href="/jobs/469745"><span>Postdoc Research Engineer</span></a></h3>
            <span> Work Locations: </span></div><div class="ecl-text-standard ecl-u-d-flex"> Number of offers: 1, Spain,
            IQUADRAT INFORMATICA, Barcelona, 08006 </div></article></li></ul>"""
        with mock.patch.object(sources.http, "get_text",
                               side_effect=[search, "", search, "", search, "", "<main>Visa support.</main>"]), \
             mock.patch.object(sources, "EURAXESS_PAUSE", 0):
            jobs = list(sources.euraxess(7))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].description, "Visa support.")
        self.assertEqual((jobs[0].title, jobs[0].company, jobs[0].country, jobs[0].location),
                         ("Postdoc Research Engineer", "Iquadrat Informatica SL", "ES", "Barcelona, 08006"))


class SourceResilienceTests(unittest.TestCase):
    def test_euraxess_keeps_results_when_rate_limited(self):
        posted = NOW.strftime("%-d %B %Y")
        search = (f'<article class="ecl-content-item"><li class="ecl-content-block__primary-meta-item">Posted on: '
                  f'{posted}</li><h3><a href="/jobs/1"><span>Postdoc</span></a></h3></article>')
        with mock.patch.object(sources.http, "get_text",
                               side_effect=[search, OSError("HTTP Error 429"), OSError("HTTP Error 429"), "<main>x</main>"]), \
             mock.patch.object(sources, "EURAXESS_PAUSE", 0):
            jobs = list(sources.euraxess(7))
        self.assertEqual([j.title for j in jobs], ["Postdoc"])


class AviationTests(unittest.TestCase):
    def test_families(self):
        cases = {
            ("Flight Operations Analyst", "Acme"): "Operations & Control",
            ("Airport Duty Manager", "Gatwick Airport Limited"): "Operations & Control",
            ("Station Manager", "Menzies Aviation"): "Operations & Control",
            ("Network Planning Analyst", "Ryanair DAC"): "Planning, Network & Scheduling",
            ("Crew Planner", "easyJet"): "Planning, Network & Scheduling",
            ("Revenue Management Analyst", "Aer Lingus"): "Commercial Aviation",
            ("Continuing Airworthiness Engineer", "Acme"): "Aerospace & Engineering",
            ("Supply Chain Analyst", "Airbus Operations Limited"): "Logistics, Supply Chain & Procurement",
            ("Aerospace Buyer", "Acme"): "Logistics, Supply Chain & Procurement",
            ("Project Manager", "Rolls-Royce plc"): "Projects, Programmes & PMO",
            ("Business Analyst", "Heathrow Airport Limited"): "Business, Strategy & Performance",
            # Generic titles outside aviation are not aviation roles.
            ("Business Analyst", "Barclays"): "",
            ("Commercial Analyst", "Tesco"): "",
            ("Network Operations Analyst", "BT"): "",
        }
        for (title, company), family in cases.items():
            self.assertEqual(classify.classify_aviation(make_job(title=title, company=company)), family, title)
        self.assertEqual(set(classify.AVIATION_FAMILIES),
                         {f for _, f in cases.items() if f})

    def test_advert_context(self):
        aviation = "You will join our airline's network team, working with airport partners on aircraft rotations."
        self.assertEqual(classify.classify_aviation(make_job(title="Business Analyst", company="Acme", description=aviation)),
                         "Business, Strategy & Performance")
        once = "Occasional flights to clients may be needed; our airline client is one of many."
        self.assertEqual(classify.classify_aviation(make_job(title="Business Analyst", company="Acme",
                                                             description=once.replace("airline client", "client"))), "")

    def test_low_sponsorship_roles(self):
        for title in ("Passenger Service Agent", "Check-in Agent", "Gate Agent", "Baggage Handler", "Ramp Agent",
                      "Ground Operations Agent", "Reservations Agent", "Ticketing Agent", "Customer Service Advisor",
                      "Administrative Assistant", "Receptionist", "Retail Assistant"):
            job = make_job(title=title, company="Swissport")
            self.assertTrue(classify.is_low_sponsorship(job), title)
            self.assertEqual(classify.classify_aviation(job), "", title)
        self.assertFalse(classify.is_low_sponsorship(make_job(title="Airport Operations Manager")))
        apprentice = make_job(title="Aerospace Engineering Degree Apprenticeship", company="Airbus")
        self.assertTrue(classify.is_low_sponsorship(apprentice))
        self.assertEqual(classify.classify_aviation(apprentice), "")

    def test_irish_permit_wording(self):
        for text in ("We will support a Critical Skills Employment Permit application for the right candidate.",
                     "Critical Skills Employment Permit is available for this role.",
                     "Employment permit support provided."):
            self.assertEqual(classify.sponsorship_signal(text), "positive", text)
        self.assertEqual(sources._guess_country("Swords, Co. Dublin", default=""), "IE")
        self.assertEqual(sources._guess_country("Shannon, Ireland", default=""), "IE")

    def test_pipeline_sets_aviation_fields(self):
        index = sponsors.SponsorIndex()
        tiers = classify.TierRules.load(CONFIG / "company_tiers.json")
        jobs = [make_job(source_id="ops", title="Operations Control Analyst", company="Aer Lingus", country="IE",
                         location="Dublin", description="Critical Skills Employment Permit sponsorship available."),
                make_job(source_id="agent", title="Passenger Service Agent", company="Swissport",
                         description="Visa sponsorship available.")]
        out = {j.source_id: j for j in pipeline.enrich(jobs, index, tiers, contacts.ContactBook({}), days=7)}
        self.assertEqual((out["ops"].aviation, out["ops"].sponsorship, out["ops"].low_sponsorship),
                         ("Operations & Control", "confirmed", False))
        self.assertEqual((out["agent"].aviation, out["agent"].low_sponsorship), ("", True))
        self.assertIn("aviation", out["ops"].to_dict())


class Stamp1GTests(unittest.TestCase):
    def test_status(self):
        open_job = make_job(country="IE", location="Dublin", description="Join our Dublin data team.")
        self.assertEqual(classify.stamp1g_status(open_job), "open")
        self.assertEqual(classify.stamp1g_status(make_job(country="IE", description="Stamp 1G holders are welcome to apply.")),
                         "stated")
        for text in ("Applicants must hold Stamp 4 or be EU citizens.", "Stamp 4 required.",
                     "EU/EEA citizens only.", "Irish or EU citizenship is required.",
                     "Candidates need permanent right to work in Ireland.", "We cannot accept Stamp 1G holders.",
                     "Stamp 1G holders are not eligible for this role."):
            self.assertEqual(classify.stamp1g_status(make_job(country="IE", description=text)), "excluded", text)

    def test_pipeline_keeps_irish_roles(self):
        index = sponsors.SponsorIndex()
        tiers = classify.TierRules.load(CONFIG / "company_tiers.json")
        jobs = [make_job(source_id="open", country="IE", location="Dublin", company="Stripe", title="Data Analyst",
                         description="Join our Dublin team. We are unable to offer visa sponsorship."),
                make_job(source_id="permit", country="IE", location="Cork", title="Software Engineer",
                         description="Critical Skills Employment Permit sponsorship available."),
                make_job(source_id="stamp4", country="IE", location="Galway", title="Analyst",
                         description="Applicants must hold Stamp 4."),
                make_job(source_id="grad", country="IE", location="Dublin", title="Graduate Analyst",
                         description="Stamp 1G holders welcome."),
                make_job(source_id="uk", country="GB", company="Unknown Co", title="Analyst", description="Great role.")]
        out = {j.source_id: j for j in pipeline.enrich(jobs, index, tiers, contacts.ContactBook({}), days=7)}
        self.assertEqual(set(out), {"open", "permit", "grad"})
        self.assertEqual(out["open"].sponsorship, "stamp_1g")  # "no sponsorship" does not close it to Stamp 1G
        self.assertEqual(out["permit"].sponsorship, "confirmed")
        self.assertEqual((out["grad"].sponsorship, out["grad"].early_career), ("stamp_1g", "stated"))
