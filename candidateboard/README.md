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

**On the web:** open `/candidates/` (the one link for everything: candidate list, boards, and the form behind the button *+ Add a candidate*; `add.html` redirects there). Upload each CV with a track name, add the suitable-roles list, answer the visa/clearance/licence questions and press *Scan CVs*. The scan runs **in your browser**: the CV is never uploaded. Correct any tier, then *Download profile* or *Copy JSON* and add it to the repo as `candidates/profiles/<slug>.json`; pushing it to `main` builds the board. The browser scan is a port of the Python one (`candidates/intake.js`, same `roles.json`), and `tests/test_intake_js.py` checks both give the same profile. PDFs must contain text (a scanned image is rejected).

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

## What the scan decides
* **Tracks**: one per CV, with the skills found in it (generic ones like "excel" are dropped).
* **Tiers** (by how strongly the CV evidences a role family, see `roles.json`): **1** core (CV headline and job titles),
  **2** close, **3** stretch. Roles the recruiter filed under a CV that does not exist yet (e.g. "With Retail CV") cap at tier 3.
  Families the CV supports but with no listed roles become **Other roles** (e.g. IT support, admin), shown only at employers that can sponsor.
* **Experience** from dated roles (overlaps counted once) is used to flag senior titles.

## Live matching on the board page
The daily build is up to a day old, but the shared feed is rebuilt every two hours. When a board opens, the page fetches that feed
(the `feed` branch, else `data/jobs.json`), scores it **in the browser** with `candidates/match.js` and adds any role the daily build
does not have, marked **Live**. It rechecks every 30 minutes and has a *Refresh now* button. If the feed cannot be fetched the banner
says so and the daily build is shown unchanged. Live matching scores the shared feed only: roles found by the candidate-specific Reed/Adzuna/NHS/jobs.ac.uk
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
