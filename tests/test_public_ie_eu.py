"""Irish public-sector and EU Careers readers, and how their adverts are labelled.

The HTML snippets below are cut down from the live pages (publicjobs.tal.net, localgovernmentjobs.ie,
educationposts.ie, eu-careers.europa.eu) as they were in November 2026."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobfeed import classify, contacts, pipeline, public_ie_eu as p, sponsors
from jobfeed.models import Job

CONFIG = Path(__file__).resolve().parent.parent / "config"
NOW = datetime.now(timezone.utc)

PUBLICJOBS = """<h2 role="alert">261 results match</h2>
<ul id="tile-results-list" class="">
<li class="col-md-6 opp-container" id="oppid-10583" data-oppid="10583">
  <div class="opp_10583 search_res details_row candidate-opp-tile" data-oppid="10583" data-title="Deputy Director &#8211; Coastal Units Branch, Irish Coast Guard (IRCG)">
    <h3 class="candidate-opp-field-2">
      <a class="subject" href="https://publicjobs.tal.net/vx/lang-en-GB/mobile-0/appcentre-1/brand-4/candidate/so/pm/1/pl/3/opp/10583-Deputy-Director/en-GB">
        Deputy Director – Coastal Units Branch, Irish Coast Guard (IRCG)</a>
    </h3>
    <div class="candidate-opp-field-3"><span class="candidate-opp-field-label">Vacancy type:</span> publicjobs</div>
    <div class="candidate-opp-field-5"><span class="candidate-opp-field-label">Department/Organisation:</span> Department of Transport</div>
    <div class="candidate-opp-field-6"><span class="candidate-opp-field-label">Location:</span> Dublin</div>
    <div class="candidate-opp-field-7"><span class="candidate-opp-field-label">Advertising Date:</span> 13 Nov 2026</div>
    <div class="candidate-opp-field-8"><span class="candidate-opp-field-label">Closing Date:</span> 17 Dec 2026</div>
  </div>
</li>
</ul>"""

LOCAL_GOVERNMENT = """<div class="job-cards-items">
<div class="job-cards-item">
  <a href="/jobs/Wicklow-County-Council/Temporary-Senior-Executive-Planner" title="Link to Temporary Senior Executive Planner Job">
    <div class="job-cards-council"><h2>Temporary Senior Executive Planner</h2><p>Wicklow County Council</p></div>
    <div class="job-cards-date">
      <p><span class="bold">Advertised Date: </span>30 Oct 2026</p>
      <p><span class="bold">Closing Date: </span>19 Nov 2026, 12:00 PM</p>
      <p><span class="bold">Grade: </span>Temporary Senior Executive Planner</p>
      <p><span class="bold">Salary Scale: </span>€80,680 - €100,692 gross per annum</p>
      <p><span class="bold">Location: </span>Wicklow</p>
    </div>
    <div class="job-cards-details"><p class="reference">46/2026</p></div>
  </a>
</div>
</div>"""

EDUCATION_POSTS = """<tbody>
<tr data-href="/post/view/264072" style="cursor: pointer;"><td><a href="/post/view/264072">264072</a></td><td><a href="/post/view/264072">WhiteCrow Research- On behalf of a prestigious UAE school</a></td><td><a href="/post/view/264072">Teacher</a></td><td><a href="/post/view/264072">English<br /></a></td><td><a href="/post/view/264072">Fixed-term</a></td><td><a href="/post/view/264072">Dublin 1</a></td><td><a href="/post/view/264072"><span>23/12/2026</span><span>23-Dec</span></a></td><td></td></tr>
<tr data-href="/post/view/264030" style="cursor: pointer;"><td><a href="/post/view/264030">264030</a></td><td><a href="/post/view/264030">St Mary's C.B.S.</a></td><td><a href="/post/view/264030">Teacher</a></td><td><a href="/post/view/264030">Mathematics<br /></a></td><td><a href="/post/view/264030">Specific Purpose - Maternity Leave</a></td><td><a href="/post/view/264030">Wexford</a></td><td><a href="/post/view/264030"><span>14/12/2026</span><span>14-Dec</span></a></td><td></td></tr>
</tbody>"""

EU_LIST = """<div class="eujmp-vacancy-result"><ul class="eujmp-vacancy-result__top-meta"><li>European Border and Coast Guard Agency (FRONTEX)</li><li><time datetime="2026-11-17T11:00:00+00:00">17 November 2026</time></li></ul><a href="/jobs/intelligence-analyst_en" class="ecl-link ecl-link--standalone eujmp-vacancy-result__title">Intelligence analyst</a><ul class="eujmp-vacancy-result__bottom-meta"><li>Temporary staff</li><li>AD 7</li><li><span class="wt-icon--location-filled" aria-hidden="true"></span>Warsaw, Poland</li></ul></div>"""

EU_DETAIL = """<div class="eujmp-vacancy__details ecl-u-mb-xl">
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Reference:</strong> RCT-2026-00055</p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Application deadline:</strong> <time datetime="2026-11-17T11:00:00+00:00">17 November 2026, 12:00 (CET)</time></p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Institution:</strong> European Border and Coast Guard Agency (FRONTEX)</p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Location:</strong> Warsaw, Poland</p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Domain:</strong> Public Administration</p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Contract type:</strong> <a href="/working-us/contract-types_en">Temporary staff</a></p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><strong>Grade:</strong> AD 7</p>
  <p class="ecl-u-mt-none ecl-u-mb-xs"><a href="https://microsite.frontex.europa.eu/en/recruitments/RCT-2026-00055" class="ecl-link ecl-link--standalone">Vacancy link</a></p>
</div>
<div class="ecl-file__content"><div class="ecl-file__title">Intelligence Analyst</div><div class="ecl-file__primary-meta"><div class="ecl-file__primary-meta-item">22 October 2026</div></div></div>"""


class ReaderTests(unittest.TestCase):
    def test_publicjobs_tiles(self):
        jobs, total = p.parse_publicjobs(PUBLICJOBS)
        self.assertEqual(total, 261)
        j = jobs[0]
        self.assertEqual((j.title, j.company, j.location, j.country, j.closes_at),
                         ("Deputy Director – Coastal Units Branch, Irish Coast Guard (IRCG)", "Department of Transport",
                          "Dublin", "IE", "2026-12-17"))
        self.assertEqual(j.posted_at.date().isoformat(), "2026-11-13")
        self.assertTrue(j.url.startswith("https://publicjobs.tal.net/") and "/opp/10583-" in j.url)

    def test_local_government_cards(self):
        j = p.parse_local_government(LOCAL_GOVERNMENT)[0]
        self.assertEqual((j.title, j.company, j.location, j.closes_at),
                         ("Temporary Senior Executive Planner", "Wicklow County Council", "Wicklow", "2026-11-19"))
        self.assertEqual(j.salary, "€80,680 - €100,692 gross per annum")
        self.assertEqual(j.url, "https://www.localgovernmentjobs.ie/jobs/Wicklow-County-Council/Temporary-Senior-Executive-Planner")

    def test_education_posts_rows_skip_recruiters_for_schools_abroad(self):
        jobs = p.parse_education_posts(EDUCATION_POSTS, "second_level")
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual((j.title, j.company, j.location, j.contract, j.closes_at),
                         ("Teacher (Mathematics)", "St Mary's C.B.S.", "Wexford", "Specific Purpose - Maternity Leave", "2026-12-14"))
        self.assertEqual(j.url, "https://www.educationposts.ie/post/view/264030")

    def test_eu_careers_list_and_vacancy_page(self):
        item = p.parse_eu_list(EU_LIST)[0]
        self.assertEqual((item["title"], item["institution"], item["deadline"], item["contract"], item["grade"], item["location"]),
                         ("Intelligence analyst", "European Border and Coast Guard Agency (FRONTEX)", "2026-11-17",
                          "Temporary staff", "AD 7", "Warsaw, Poland"))
        info = p.parse_eu_detail(EU_DETAIL)
        self.assertEqual(info["apply"], "https://microsite.frontex.europa.eu/en/recruitments/RCT-2026-00055")
        self.assertEqual((info["reference"], info["published"], info["domain"]), ("RCT-2026-00055", "22 October 2026", "Public Administration"))
        self.assertEqual([p.eu_country(x) for x in ("Warsaw, Poland", "Geel, Belgium", "Luxembourg, Luxembourg", "Nowhere")],
                         ["PL", "BE", "LU", ""])


class LabelTests(unittest.TestCase):
    def enrich(self, jobs):
        return pipeline.enrich(jobs, sponsors.SponsorIndex(), classify.TierRules.load(CONFIG / "company_tiers.json"),
                               contacts.ContactBook({}), days=7)

    def job(self, sid, **kw):
        base = dict(source="publicjobs.ie", source_id=sid, title=f"Administrative Officer {sid}", company="Department of Transport",
                    location="Dublin", country="IE", url=f"https://x/{sid}", posted_at=NOW - timedelta(days=1), channel="official")
        return Job(**{**base, **kw})

    def test_irish_public_service_and_eu_labels_and_open_adverts(self):
        future = (NOW + timedelta(days=20)).date().isoformat()
        past = (NOW - timedelta(days=1)).date().isoformat()
        jobs = [
            self.job("pj"),
            self.job("pj-old-open", posted_at=NOW - timedelta(days=20), closes_at=future),   # older than 7 days but still open
            self.job("pj-closed", closes_at=past),
            self.job("pj-old", posted_at=NOW - timedelta(days=20)),                           # no closing date: usual 7 days
            self.job("council-elsewhere", source="Reed", company="Cork County Council",
                     description="Candidates must, by the date of any job offer, be a citizen of the European Economic Area."),
            self.job("eu", source="EU Careers", company="European Commission", location="Brussels, Belgium", country="BE"),
            self.job("eu-dublin", source="EU Careers", company="Eurofound", location="Dublin, Ireland"),
        ]
        out = {j.source_id: j for j in self.enrich(jobs)}
        self.assertEqual(set(out), {"pj", "pj-old-open", "council-elsewhere", "eu", "eu-dublin"})
        for sid in ("pj", "pj-old-open", "council-elsewhere"):
            self.assertEqual(out[sid].sponsorship, "ie_public_sector", sid)
        self.assertEqual((out["eu"].sponsorship, out["eu-dublin"].sponsorship), ("eu_institution", "eu_institution"))
        self.assertEqual(out["pj"].salary_check, "")   # no permit salary minimum applies to either label
        self.assertEqual((out["pj"].sector, out["eu"].sector), ("Public Sector & Government", "Public Sector & Government"))

    def test_sponsorship_stated_in_an_irish_public_advert_still_wins(self):
        out = self.enrich([self.job("hse", source="publicjobs.ie", company="HSE",
                                    description="Visa sponsorship is available for this role.")])
        self.assertEqual(out[0].sponsorship, "confirmed")


if __name__ == "__main__":
    unittest.main()
