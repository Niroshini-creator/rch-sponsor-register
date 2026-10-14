# Candidate boards

One board per candidate: roles from the **last 7 days**, matched to that candidate's CV, visa, clearance and driving licence,
with a **match %** and plain labels (sponsorship offered / not offered / licensed sponsor, SC / BPSS / DBS clearance, driving
licence, pay against the Skilled Worker minimum). Built the same way as the sponsored-jobs board and `/mugilan/`, and served at
`/candidates/?c=<slug>`. The index at `/candidates/` lists every candidate.

> **Privacy.** This repository is public and GitHub Pages serves it, so a board is readable by anyone who has its link
> (the page is `noindex`, but that is not access control). A profile holds the name, headline, visa, skills and role lists;
> **no phone, email or CV file** is stored. For real candidates, use a **private repository** (Pages on a private repo needs a paid
> plan) or keep the profile out of git. `candidates/profiles/sample-candidate.json` is fictional.

## Add a candidate (about a minute)

**Candidates (self-serve):** send them `/candidates/`. They upload a CV, answer the visa/clearance/licence questions and press *Find vacancies*. The CV is scanned **in their browser** (never uploaded), the profile is matched live against the shared feed, and they see Tier 1/2/3 vacancies, each with an **Apply** button to the employer's own advert. Nothing is saved on the server; a reload within the same browser session keeps the results.

**Recruiters:** `/candidates/#boards` lists saved candidate boards. From a candidate's results, the *CV scan* tab has *Download profile (JSON)*; commit it as `candidates/profiles/<slug>.json` to turn it into a saved board that also includes the candidate-specific Reed/Adzuna/NHS/jobs.ac.uk searches (built daily). The browser scan is a port of the Python one (`candidates/intake.js`, same `roles.json`), and `tests/test_intake_js.py` checks both give the same profile. PDFs must contain text (a scanned image is rejected).

**Or on the command line:**

```
python -m candidateboard intake --slug jane-doe --name "Jane Doe" --location Coventry \
  --cv "SAP Security & GRC=sap_cv.pdf" --cv "Business Analyst=ba_cv.pdf" \
  --roles-file suitable_roles.pdf \
  --visa graduate --visa-label "Graduate visa (PSW)" --visa-expires 2027-11 --sponsorship preferred --new-entrant \
  --clearance none --driving-licence unknown
python -m candidateboard build --slug jane-doe        # needs REED_API_KEY / ADZUNA_* for live searches; --offline scores the shared feed only
```
`intake` reads each CV (PDF needs `pdftotext`), the recruiter's suitable-roles list (bullets = titles, other lines = sections),
and writes `candidates/profiles/<slug>.json`. The daily workflow then keeps the board current. **Review the profile**: tiers, roles and skills are plain
data you can edit. Change `visa.expires`, `clearance.held`, `driving_licence` (true/false/null), `min_match`, `roles[].tier`, anything.

## Roles the candidate adds
The form has a **Roles you are looking for** box (type a title, press Enter or *Add role*; suggestions come from the role list in `roles.json`), and the results page has the same box (**Roles you want**), so a candidate can add or remove roles after seeing results and the matching runs again without re-uploading the CV. Roles they add are **first choice (Tier 1)**, searched first, on the CV whose skills fit that kind of role best; a title the role list does not know is still matched by its words. A role only appears if employers advertise it in the feed this week, and its match % shows how much of the CV fits. On the command line: `--role "Data Analyst" --role "Project Coordinator"`; in a profile they are `roles[]` entries with `"source": "added by candidate"`.

## Genuine employers first
The page's **Where advertised** filter defaults to *Employer career sites, NHS, public sector, universities & schools*: adverts on an employer's own site or an official board (NHS Jobs, Teaching Vacancies, jobs.ac.uk, THE unijobs, Platsbanken, and the Civil Service / council search). Job boards (Reed, Adzuna, Arbeitnow) are one click away ("Also job boards, except Adzuna", "Everything"), and the page says how many more roles they hold. Job boards and recruiters that post under their own name (eFinancialCareers, Jobsite, Salt Search ...) are removed from the feed itself (`config/agencies.json`). A **Country** filter with counts is shown whenever the candidate chose more than one place.

## Careers-site links (Adzuna does not open everywhere)
Adzuna adverts open through an Adzuna page that some places (for example India) cannot load. For those roles the card leads with **Employer careers site →** and says what to search for there ("search for “Business Analyst” in London"); the Adzuna link stays beside it. The address comes from the feed's own `employer_site`, then `candidates/careerlinks.js`: `config/career_pages.json` (home pages of about 60 large employers, curated, with aliases) and the board address of every employer in `config/employers.json`; any NHS body falls back to NHS Jobs and any university to jobs.ac.uk. These are home pages, not the specific job. Add a company by editing `config/career_pages.json`.

**Adding an employer the feed reads directly** (so its real adverts, with real links, appear): paste any live job link from its career site:
`python -m jobfeed.addemployer "Comcast" "https://comcast.wd5.myworkdayjobs.com/en-US/Comcast_Careers/job/..." --country US`
It recognises Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Oracle Recruiting from the link alone (no network needed) and adds one line to `config/employers.json`. Employers on their own platform (Amazon, Google, Microsoft, TCS ...) cannot be read this way. A board that cannot be read is listed under "Where these vacancies come from" instead of stopping the feed. Entries marked `"verify": true` are best guesses to check after the next feed run.

## Where the candidate would work
The form asks which places to search: **United Kingdom, Ireland, Europe (EU/EEA and Switzerland), Australia, Middle East** (UAE, Saudi Arabia, Qatar, Kuwait, Bahrain, Oman); the regions and their countries are in `regions.json`. On the command line: `--regions GB,IE,EU,AU,ME`. The profile records `locations` and the expanded `countries`.

* **English only (on by default, `english_only`)**: outside the English-speaking countries (UK, Ireland, US, Malta, Australia), an advert that is not in English or asks for another language is hidden (shown with "Show roles ... in another language"). The feed decides this per advert (`english`).
* **Reserved posts**: adverts reserved for a country's own nationals ("(UAE National)", "Saudi nationals only", "citizens only") are hidden; "Emiratisation programme" or "open to UAE nationals and expats" are not.
* **Sponsorship abroad**: shown if the advert offers it, the employer is on that country's sponsor list (NL IND, Irish permits, US H-1B), or the country's employers sponsor by default (Gulf states). Australia has no public sponsor list, so only adverts that say they sponsor appear. **Pay against the visa minimum is checked for the UK and Ireland only**; other countries show "not checked".
* **Coverage is widest in the UK.** The feed is thin for Europe outside the registers above, and Australia (Adzuna) and the Gulf states beyond the UAE have few sources. The board's candidate-specific Reed / Adzuna / NHS / jobs.ac.uk searches are UK-only.

## What the scan decides
* **Tracks**: one per CV, with the skills found in it (generic ones like "excel" are dropped).
* **Tiers** (by how strongly the CV evidences a role family, see `roles.json`): **1** core (CV headline and job titles),
  **2** close, **3** stretch. Roles the recruiter filed under a CV that does not exist yet (e.g. "With Retail CV") cap at tier 3.
  Families the CV supports but with no listed roles become **Other roles** (e.g. IT support, admin), shown only at employers that can sponsor.
* **Experience** from dated roles (overlaps counted once) is used to flag senior titles.

## Live matching (what a self-serve candidate sees)
The daily build is up to a day old, but the shared feed is rebuilt every two hours. When a board opens, the page fetches that feed
(the `feed` branch, else `data/jobs.json`), scores it **in the browser** with `candidates/match.js` and adds any role the daily build
does not have, marked **Live**. It rechecks every 30 minutes and has a *Refresh now* button. If the feed cannot be fetched the banner
says so and the daily build is shown unchanged. Self-serve results are live matching only, so they cover the shared feed only: roles found by the candidate-specific Reed/Adzuna/NHS/jobs.ac.uk
searches (and full-advert reads) arrive with the daily build. `match.js` is a port of `match.py` + `checks.py` + the pay rules;
`tests/test_match_js.py` runs both on the real feed under several candidate variants and requires identical results.

## Where roles come from
| Source | Covers |
|---|---|
| Shared feed `data/jobs.json` (rebuilt every 2h by the main board) | NHS Jobs, Teaching Vacancies (schools), jobs.ac.uk and Times Higher Education (universities), employer career sites, Adzuna, Reed; each already checked against the Home Office register |
| Candidate searches (this package) | Reed, Adzuna, NHS Jobs and jobs.ac.uk searched with the candidate's own role titles, so niche roles (e.g. SAP GRC) the shared feed does not hold are found; the best Reed/NHS adverts are read in full |
| Not read | LinkedIn, Indeed, Glassdoor (no public API, scraping forbidden), recruitment agencies (removed) |

Without API keys only the shared feed is used and the page's *Data sources* panel says so: **the board is then a floor, not the market.**

## Match % and labels
Match % is **CV fit only**: title 50 · skills 40 · level 10 (explained on each card under *Why this score*). Adverts that exist only
as the feed's ~400-character extract cap skills at 22, so they top out near 80%; the card says "extract only". Separate labels:
* **Sponsorship**: offered · may be available · licensed sponsor (advert silent) · not offered · employer not on register. A licence without the **Skilled Worker** route is flagged.
* **Clearance**: DV / SC / CTC / NPPV / "security clearance" are hidden by default for a candidate holding none, and say whether the advert needs it or asks you to be *eligible to obtain* it; BPSS and DBS are shown as standard checks. In an extract with no mention the label says "check the advert".
* **Driving licence**: required / desirable, against the profile (unknown until confirmed).
* **Visa pay**: advertised pay against the Skilled Worker minimum (new-entrant rate when `visa.new_entrant`).
* **Sponsorability**: roles below degree level (admin, IT support, marketing/sales support, retail) are usually not sponsorable even by licensed sponsors since the 2025 skill-level rise. The card says "Sponsorship unlikely at this level"; confirm with the employer and the Home Office occupation list.

## Files
`roles.json` role families (edit to add roles) · `cv.py` CV scan · `intake.py` profile builder · `match.py` scoring and labels · `checks.py` clearance / licence ·
`pipeline.py` fetch, label, dedupe, write · `candidates/` the viewer. Workflow: `.github/workflows/refresh-candidates.yml` (daily 07:23 UTC, on profile changes, or on demand).
Tests: `python -m unittest discover -s tests -p "test_candidateboard.py"` (plus `test_intake_js.py` and `test_match_js.py`, which need Node).

## Attaching a document of suitable positions

On the upload form (and on the results page) a candidate can attach a PDF, Word (.docx) or text file listing the roles they want. It is read in the browser (`candidates/docread.js`; the old binary `.doc` is not supported, save as .docx or PDF). Bullet or numbered lines are titles, other lines are headings (a heading named after a CV picks that CV); a list with no bullets is read line by line, and "A / B" or comma lists are split. The Python parser (`cv.parse_role_list`) and the browser one stay identical (`tests/test_docread_js.py`). CVs can also be attached as .docx.
