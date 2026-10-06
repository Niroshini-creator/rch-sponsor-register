# rch-sponsor-register — Sponsored Jobs Board

A self-updating board of employers that **actively hire with visa sponsorship** in the **UK (including Scotland),
Europe (Netherlands, Luxembourg, Sweden, Finland, Poland, Spain and the rest of the EU), the USA and the UAE (Dubai)**.
It shows only vacancies posted in the **last 7 days** and covers every domain: technical, management,
science and research, NHS and healthcare, universities, schools and the public sector. It also lists employers that
take **UK Graduate visa (PSW)** and **US OPT / STEM OPT** holders.

Every job links to the **employer's own application**: its careers site, or the official public-sector
board it recruits through (NHS Jobs, Teaching Vacancies, jobs.ac.uk, EURAXESS). **Recruitment agencies and
consultancies are removed.**

* **Static site** (`index.html`): works on GitHub Pages with no server. Filter by country or region (Scotland, Dubai),
  age, job role, sponsorship evidence, English-speaking roles, PSW / OPT friendly roles, employer tier (1/2/3), employer
  size (large/medium/small), sector and role domain. Quick views for universities, schools, public sector & NHS, and a
  PSW & OPT employer directory. Export to CSV.
* **Data pipeline** (`jobfeed/`): Python 3.10+, standard library only. It fetches vacancies,
  checks employers against the official sponsor registers, classifies each job and writes `data/jobs.json`.
* **GitHub Actions** (`.github/workflows/refresh-jobs.yml`): runs the tests and rebuilds the feed twice a day.

## How a job gets onto the board

1. **Collected** from the sources below, keeping only jobs posted within `--days` (default 7). The browser
   applies the same limit again, so a stale feed never shows old jobs.
2. **Agencies removed.** Adverts from recruitment agencies and consultancies are dropped. They are recognised by
   name (list in [`config/agencies.json`](config/agencies.json), plus words like "Recruitment", "Staffing",
   "Resourcing") or by standard agency wording in the advert ("our client is…", "acting as an employment
   agency"). Reed is queried for direct-employer adverts only. If a real employer is caught by mistake, add it
   to `never_agency`.
3. **Sponsorship check.** A job is kept only if one of these is true:
   * **Sponsorship offered**: the advert says so ("visa sponsorship available", "Skilled Worker
     sponsorship will be considered", "EU Blue Card", NHS Jobs' standard sponsorship wording), or the source
     flags it.
   * **Licensed sponsor**: the advert doesn't mention sponsorship, but the employer is on the official
     register for that country: the [UK Home Office register of licensed sponsors](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers)
     or the [Dutch IND register of recognised sponsors](https://ind.nl/en/public-register-recognised-sponsors/public-register-regular-labour-and-highly-skilled-migrants),
     or, for US jobs, the [USCIS H-1B Employer Data Hub](https://www.uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub)
     (employers with approved H-1B petitions), or, for Irish jobs, the Department of Enterprise list of
     [employment permits issued to companies](https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/statistics/)
     this year or last (shown as "Permit employer").
   * **Employer visa (UAE)**: UAE employers sponsor the residence and work visa of every foreign hire, so every job in
     the UAE is kept.
   * **Graduate visa / OPT accepted** (hidden by default): the advert rules sponsorship out but says it welcomes
     Graduate visa (PSW) or OPT holders, who need no sponsorship.
   * **Ireland: open to Stamp 1G** (hidden by default): an Irish job with no sponsorship evidence that doesn't rule
     Stamp 1G holders out.

   The board opens on the first three (sponsorship evidence); the last two are for candidates who don't need it.

   Any other advert that rules sponsorship out ("unable to sponsor", "right to work without sponsorship",
   "must be a US citizen") is dropped.
4. **Classified**:
   * **Sector** (employer type): NHS & Healthcare, University & Research Institute, School & College,
     Public Sector & Government, Charity & Non-profit, Private Sector.
   * **Role domain**: Technical & Engineering, Management & Business, Science & Research,
     Healthcare & Clinical, Teaching & Academic, Finance & Legal.
   * **Job role** (from the title): Software Developer, DevOps & Cloud, Data Science & AI, Data Analyst,
     Business Analyst, IT Support, Application Support, Mechanical Engineering, Engineering, Project Manager, Finance & Accounting,
     HR & Recruitment, Digital Marketing, Logistics & Supply Chain, Medical Laboratory, Aviation, Other.
   * **Aviation & operations family** (when the title is one of them and the employer or advert is in aviation or
     aerospace): Airport Operations; Operations & Control; Planning, Network & Scheduling; Business, Strategy &
     Performance; Aerospace & Aeronautical Engineering; Projects, Programmes & PMO; Logistics, Supply Chain & Procurement; Commercial Aviation.
     Shown in the *Aviation & operations* tab and filter.
   * **Rarely sponsored**: front-line roles (passenger service, check-in, gate, baggage and ramp agents,
     reservations, customer service advisers, administrators, receptionists, retail and hospitality, and
     apprenticeships) are flagged
     and hidden by default, because they seldom meet sponsorship skill and salary levels.
   * **Region**: Scotland (UK jobs in Scottish places or employers such as NHS Lothian), Dubai and Abu Dhabi.
   * **English-speaking**: the advert is written in English and asks for no other language ("Dutch is a plus" is
     fine; "fluent German required" is not). Jobs in the UK, Ireland and the US always count.
   * **PSW / OPT friendly** (UK and US only): *stated* when the advert names the Graduate visa / PSW, OPT / STEM OPT /
     CPT or cap-exempt H-1B; *likely* when an entry-level title (graduate, junior, intern, new grad…) is at an
     employer that sponsors (UK) or files H-1Bs or uses E-Verify, which STEM OPT requires (US).
   * **Tier and size**: see below.
5. **Hiring contacts** attached (see below), and duplicates merged. When the same job appears on the employer's
   careers site and on a job board, the careers-site copy is kept. The result is written to `data/jobs.json`.

Each job is labelled with how you apply:

| Apply via | Meaning | Shown by default |
|---|---|---|
| **Employer careers site** | Read straight from the employer's own careers portal | yes |
| **Official board** | NHS Jobs, Teaching Vacancies (DfE), jobs.ac.uk, EURAXESS: where NHS trusts, schools, universities and research bodies post their own vacancies | yes |
| **Job board** | Adzuna, Reed, Arbeitnow reposts (agency adverts already removed) | no, tick it under *Apply via* |

## Employer tiers and size

Defined and editable in [`config/company_tiers.json`](config/company_tiers.json):

| Tier | Meaning |
|---|---|
| **1** | Market leaders and major institutions: FTSE 100 / Global 500, big tech, Big 4, global banks, NHS trusts and health boards, Russell Group and top EU universities, central government and EU institutions |
| **2** | Established mid-to-large organisations: FTSE 250 and scale-ups, other universities and research institutes, councils, police, multi-academy trusts, large charities |
| **3** | SMEs, start-ups, schools, GP practices, care providers and every other licensed sponsor |

Size follows the UK Companies Act bands: **small** (< 50 staff), **medium** (50–249), **large** (250+). It comes
from the config, otherwise from headcount mentioned in the advert, otherwise it is shown as *unknown*.
Add employers to `tier1`/`tier2` (optionally with `"size"`) or add regex `patterns` to improve coverage.

## PSW & OPT employer directory

The *PSW & OPT employers* tab lists employers for UK Graduate visa and US OPT holders:

* **Curated** graduate and new-grad employers in [`config/early_career_employers.json`](config/early_career_employers.json)
  (large employers with graduate schemes, mid-size tech consultancies, universities). Each run re-checks them against
  the UK sponsor register or the US H-1B data and shows *Licensed sponsor* / *Files H-1Bs*, or *Not matched* when the
  name was not found (add the legal name as `register_name`).
* **Found in feed**: any employer, of any size, with an entry-level role that is PSW / OPT friendly this week. This
  is where most small and mid-size employers come from.

## Hiring manager details

The board shows a contact only if its origin is known:

* **from advert**: an address printed in the job advert (e.g. "informal enquiries to …"), labelled either
  *named contact* or *recruitment inbox*. When the advert names the person next to it ("contact Dr Jane Smith,
  Head of Biochemistry, on 01234 567890 or jane.smith@…"), the name, job title and phone number are shown too.
  Platsbanken (Sweden) adverts carry the employer's own contact list, which is shown the same way.
* **verified**: an address you added to [`config/contacts.json`](config/contacts.json) together with the public
  page you saw it on. It appears on every job from that employer.

Addresses are **never guessed** (e.g. `firstname.lastname@company`) or scraped from personal profiles. Guessed
addresses are often wrong, and emailing people via inferred personal data can breach UK GDPR / PECR. When no
address is published, the card links to the advert and to LinkedIn people searches for that employer's hiring manager
(by job role) and recruiters.

## Data sources

### Employer career sites (`config/employers.json`)

Most employers run their careers page on an applicant tracking system that publishes a public job feed.
The board reads that feed directly, so the job and its Apply button are the employer's own. Supported:
**Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio, Workday, Teamtailor, Oracle Recruiting
Cloud, SAP SuccessFactors**.

To add an employer, open its careers page, look at the address of a job link, and add one line:

```json
{ "name": "Monzo", "ats": "greenhouse", "id": "monzo", "country": "GB", "register_name": "Monzo Bank Limited" }
{ "name": "GSK", "ats": "workday", "host": "gsk.wd5.myworkdayjobs.com", "site": "GSKCareers", "country": "GB" }
```

| Careers page address looks like | ats | id |
|---|---|---|
| `boards.greenhouse.io/monzo` | greenhouse | monzo |
| `jobs.lever.co/spotify` (`jobs.eu.lever.co` → add `"region": "eu"`) | lever | spotify |
| `jobs.ashbyhq.com/synthesia` | ashby | synthesia |
| `jobs.smartrecruiters.com/BoschGroup` | smartrecruiters | BoschGroup |
| `apply.workable.com/acme` | workable | acme |
| `acme.recruitee.com` | recruitee | acme |
| `acme.jobs.personio.de` | personio | acme |
| `gsk.wd5.myworkdayjobs.com/GSKCareers` | workday | `host` + `site` |
| `acme.teamtailor.com` (or its own domain, e.g. `careers.voi.com`) | teamtailor | acme (or `"host": "careers.voi.com"`) |
| `encd.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_3001` | oracle | `host` + `site` (CX_3001) |
| `jobs.swissport.com` (images from `rmkcdn.successfactors.com`) | successfactors | `"host": "jobs.swissport.com"` |

* `register_name` is the employer's legal name on the UK sponsor register, when it differs from the brand
  name. It lets the licence check match.
* `"local": true` marks an employer whose jobs are all in its home country (e.g. an NHS trust or a university
  on Workday). Otherwise, jobs in unrecognised locations are left out rather than assumed to be in the UK.
* The starter list is ~100 employers across the UK, Europe, the US and the UAE. Their board ids were entered from knowledge, not tested from here, so
  check the **Data sources** table on the board after the first run: failing employers are named there.

### Public-sector, NHS and university boards, and job boards

| Source | Coverage | Key needed |
|---|---|---|
| NHS Jobs (public XML search + each advert page for the full text and contact) | NHS England & Wales trusts (official) | none |
| [jobs.ac.uk](https://www.jobs.ac.uk/) search, newest first (each advert's schema.org JobPosting) | UK and overseas universities and research institutes (official) | none |
| [Times Higher Education unijobs](https://www.timeshighereducation.com/unijobs/) RSS + listing pages | Universities in the UK, US, Europe and the Gulf (official) | none |
| [EURAXESS](https://euraxess.ec.europa.eu/jobs/search) search + job pages | European research jobs (official) | none |
| [Platsbanken JobSearch API](https://jobsearch.api.jobtechdev.se/) (Arbetsförmedlingen) | Every advert in Sweden incl. universities, regions, municipalities (official) | none |
| [Teaching Vacancies API](https://teaching-vacancies.service.gov.uk/) (DfE) | State schools in England (official) | none |
| RSS feeds in `config/sources.json` | any extra feed you add, e.g. a council's vacancies (official) | none |
| [Adzuna API](https://developer.adzuna.com/) | UK (incl. a Scotland search), US, NL, PL, ES, DE, FR, BE, AT, CH, IT (no Irish site); one search per job role for the UK and US, airport operations and aeronautical searches across Europe (job board) | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (free) |
| [Reed API](https://www.reed.co.uk/developers/jobseeker) | UK, direct employers only; one search per job role (job board) | `REED_API_KEY` (free) |
| [Arbeitnow API](https://www.arbeitnow.com/api) | Germany / EU, visa-sponsorship filter (job board) | none |

Adzuna's free tier allows about 25 calls a minute, so the connector pauses between calls (`ADZUNA_PAUSE`, default 2.5 s)
and stops at `ADZUNA_MAX_CALLS` (default 200), running the most important searches first.

University boards and NHS Jobs read up to `ACADEMIC_MAX_ADVERTS` (default 150 per board) and `NHS_MAX_ADVERTS` (default 300)
advert pages per run, pausing `ACADEMIC_PAUSE` seconds (default 0.3) between them.

Sources without keys are skipped rather than failing. Each run's per-source status is shown under
*Data sources & last run status* on the page. The RSS feed URLs are examples, so check them for your
search and add any others you want: council job boards, NHS Scotland / HSC NI boards, university vacancy
feeds. Give each one `"channel": "official"`. Civil Service Jobs and most councils have no public feed; where
a public body's careers site runs on one of the supported ATS platforms (often Workday), add it to
`config/employers.json` instead.

## Setup

1. **Enable GitHub Pages**: *Settings → Pages → Deploy from branch → `main` / root*.
2. **Add API keys** (optional, recommended): *Settings → Secrets and variables → Actions*, then add
   `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`.
3. **Run the feed**: *Actions → Refresh sponsored jobs → Run workflow*. After that it runs at 05:17 and 13:17 UTC.

### Run locally

```bash
export ADZUNA_APP_ID=… ADZUNA_APP_KEY=… REED_API_KEY=…   # optional
python -m jobfeed --days 7            # writes data/jobs.json
python -m unittest discover -s tests  # run the tests
python -m http.server 8000            # open http://localhost:8000
```

`UK_SPONSOR_REGISTER_CSV=/path/to/register.csv` uses a downloaded copy of the register instead of fetching it, and
`US_H1B_EMPLOYERS_CSV=/path/to/h1b.csv` a downloaded export of the USCIS H-1B Employer Data Hub.
`JOBFEED_RETRIES=1` stops retrying unreachable sites (useful when testing offline).

## Project layout

```
index.html, assets/          static front end
jobfeed/careers.py           employer career sites (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio, Workday, Teamtailor, Oracle, SuccessFactors)
jobfeed/agencies.py          recruitment agency / consultancy detection
jobfeed/sources.py           NHS Jobs, Teaching Vacancies, Platsbanken, RSS and job-board connectors
jobfeed/sponsors.py          UK Home Office + NL IND sponsor registers, USCIS H-1B employer data
jobfeed/classify.py          sponsorship wording, sector, domain, job role, region, language, PSW/OPT, tier and size rules
jobfeed/contacts.py          advert email extraction + verified contact book
jobfeed/pipeline.py          fetch → verify → classify → dedupe → data/jobs.json
config/                      sources, employer career sites, agencies, tiers, verified contacts
tests/                       offline unit tests (no network needed)
```

## Caveats

* Being on a sponsor register means an employer *can* sponsor, not that it will for every role. Jobs marked
  **Licensed sponsor** need confirming with the employer.
* Ireland: an Irish role counts as sponsored when the advert offers an employment permit, or the employer was issued
  permits this year or last. Other Irish roles are kept for Stamp 1G holders (who need no permit) unless the advert
  rules them out ("Stamp 4 required", "EU/EEA citizens only"), and only show when that option is ticked. Irish universities
  come through jobs.ac.uk, Times Higher Education and EURAXESS (their own CoreHR sites have no public feed); the HSE
  and publicjobs.ie have no public feed either. Adzuna has no Irish site, so other Irish roles come from employer
  career sites (Stripe, Intercom, Mastercard, Ryanair, Veolia Ireland and others with Dublin offices).
* Heathrow and Vertiv (Oracle) and Manchester Airports Group, Swissport, Wizz Air, Brussels Airport, Ryanair and EY
  (SuccessFactors) are read directly. Other airlines and airports (easyJet, British Airways, Virgin Atlantic,
  Gatwick, Dublin Airport, Schiphol, Emirates, flydubai) have no public feed; their adverts reach the board only
  through the Reed and Adzuna aviation searches.
* Only the UK and the Netherlands publish sponsor registers, and the US publishes H-1B petition data. For other
  countries (Luxembourg, Sweden, Finland, Poland, Spain…), jobs appear only when the advert itself offers sponsorship
  or work-permit support.
* The USCIS site sometimes blocks automated downloads. If the *US H-1B register* row on the board shows an error,
  US jobs still appear when the advert offers sponsorship; download the export by hand and set `US_H1B_EMPLOYERS_CSV`
  to use it.
* Graduate visa (PSW) holders can work for any UK employer, and OPT holders for any US employer in their field;
  *PSW / OPT friendly* highlights the roles where that is most realistic, not the only ones open to you.
* The employer career sites added for the US, Nordics, Poland, Spain and the UAE were entered from knowledge;
  any that fail are named under *Data sources* on the board.
* Classification uses keyword rules, so some jobs will be mislabelled. Correct them by editing the rules in
  `jobfeed/classify.py` and `config/company_tiers.json`.
