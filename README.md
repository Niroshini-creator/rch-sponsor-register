# rch-sponsor-register — Sponsored Jobs Board

A self-updating board of employers that **actively hire with visa sponsorship** in the **UK and Europe**.
It shows only vacancies posted in the **last 7 days** and covers every domain: technical, management,
science and research, NHS and healthcare, universities, schools and the public sector.

* **Static site** (`index.html`): works on GitHub Pages with no server. Filter by country, age, sponsorship
  evidence, employer tier (1/2/3), employer size (large/medium/small), sector and role domain. Export to CSV.
* **Data pipeline** (`jobfeed/`): Python 3.10+, standard library only. It fetches vacancies,
  checks employers against the official sponsor registers, classifies each job and writes `data/jobs.json`.
* **GitHub Actions** (`.github/workflows/refresh-jobs.yml`): runs the tests and rebuilds the feed twice a day.

## How a job gets onto the board

1. **Collected** from the sources below, keeping only jobs posted within `--days` (default 7). The browser
   applies the same limit again, so a stale feed never shows old jobs.
2. **Sponsorship check.** A job is kept only if one of these is true:
   * **Sponsorship offered**: the advert says so ("visa sponsorship available", "Skilled Worker
     sponsorship will be considered", "EU Blue Card", NHS Jobs' standard sponsorship wording), or the source
     flags it.
   * **Licensed sponsor**: the advert doesn't mention sponsorship, but the employer is on the official
     register for that country: the [UK Home Office register of licensed sponsors](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers)
     or the [Dutch IND register of recognised sponsors](https://ind.nl/en/public-register-recognised-sponsors/public-register-regular-labour-and-highly-skilled-migrants).

   Any advert that rules sponsorship out ("unable to sponsor", "right to work without sponsorship") is dropped.
3. **Classified**:
   * **Sector** (employer type): NHS & Healthcare, University & Research Institute, School & College,
     Public Sector & Government, Charity & Non-profit, Private Sector.
   * **Role domain**: Technical & Engineering, Management & Business, Science & Research,
     Healthcare & Clinical, Teaching & Academic, Finance & Legal.
   * **Tier and size**: see below.
4. **Hiring contacts** attached (see below), duplicates across sources merged, and the result written to `data/jobs.json`.

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

## Hiring manager emails

The board shows an email only if its origin is known:

* **from advert**: an address printed in the job advert (e.g. "informal enquiries to …"), labelled either
  *named contact* or *recruitment inbox*.
* **verified**: an address you added to [`config/contacts.json`](config/contacts.json) together with the public
  page you saw it on. It appears on every job from that employer.

Addresses are **never guessed** (e.g. `firstname.lastname@company`) or scraped from personal profiles. Guessed
addresses are often wrong, and emailing people via inferred personal data can breach UK GDPR / PECR. When no
address is published, the card links to the advert and to a LinkedIn people search for that employer's recruiters.

## Data sources

| Source | Coverage | Key needed |
|---|---|---|
| [Adzuna API](https://developer.adzuna.com/) | UK, IE, DE, NL, FR, BE, AT, CH, ES, IT, PL; all sectors | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (free) |
| [Reed API](https://www.reed.co.uk/developers/jobseeker) | UK, all sectors | `REED_API_KEY` (free) |
| NHS Jobs (public XML search) | NHS England & Wales | none |
| [Teaching Vacancies API](https://teaching-vacancies.service.gov.uk/) (DfE) | Schools in England | none |
| [Arbeitnow API](https://www.arbeitnow.com/api) | Germany / EU, visa-sponsorship filter | none |
| RSS feeds in `config/sources.json` | e.g. jobs.ac.uk (universities), EURAXESS (EU research) | none |

Sources without keys are skipped rather than failing. Each run's per-source status is shown under
*Data sources & last run status* on the page. The RSS feed URLs are examples, so check them for your
search and add any others you want (council job boards, Civil Service Jobs alerts, university career pages, etc.).

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

`UK_SPONSOR_REGISTER_CSV=/path/to/register.csv` uses a downloaded copy of the register instead of fetching it.

## Project layout

```
index.html, assets/          static front end
jobfeed/sources.py           one connector per job source
jobfeed/sponsors.py          UK Home Office + NL IND sponsor registers
jobfeed/classify.py          sponsorship wording, sector, domain, tier and size rules
jobfeed/contacts.py          advert email extraction + verified contact book
jobfeed/pipeline.py          fetch → verify → classify → dedupe → data/jobs.json
config/                      sources, tiers, verified contacts
tests/                       offline unit tests (no network needed)
```

## Caveats

* Being on a sponsor register means an employer *can* sponsor, not that it will for every role. Jobs marked
  **Licensed sponsor** need confirming with the employer.
* Only the UK and the Netherlands publish sponsor registers. For other European countries, jobs appear only
  when the advert itself offers sponsorship.
* Classification uses keyword rules, so some jobs will be mislabelled. Correct them by editing the rules in
  `jobfeed/classify.py` and `config/company_tiers.json`.
