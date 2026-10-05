# Mugilan matched-roles board

A separate, self-contained board for one candidate (OSS/BSS Solution Architect, see `config/profile.json`).
It shows UK roles **posted in the last 7 days**, each with a **match %** against the CV, and **rebuilds itself every day**.

It does **not** change the main sponsored-jobs board: its own folder (`mugilan/`), its own workflow
(`.github/workflows/refresh-mugilan-jobs.yml`), its own output (`mugilan/data/jobs.json`) and its own concurrency group.
It only *imports* helpers from `jobfeed/` (HTTP, dates, sponsor register, agency list) and never writes to them.
Once on `main`, GitHub Pages serves it at `/mugilan/` beside the main board.

## What it filters on
| Candidate fact | Handling |
|---|---|
| Interested in OSS/BSS Solution Architect (plus related titles in `profile.json`) | Searches and title scoring |
| No SC / DV clearance | Adverts needing SC, DV, CTC, NPPV or "security clearance" are **removed** |
| Global Business Mobility visa (needs a new sponsor) | Adverts refusing sponsorship are **removed**; others are tagged *offers sponsorship*, *licensed sponsor* (UK Home Office register), *agency*, or *not verified* (−5) |
| £60,000 expectation | Pay topping out below it: −10 and flagged; pay reaching it: +5; no pay stated: flagged |
| Network capacity planning strength | "Network capacity / planning" titles and keywords score |
| 90-day notice | Adverts asking for an immediate start are flagged |
| UK driving licence | Shown in the profile; no filtering needed |
| Posted within 7 days | Applied in the feed and again in the browser |

## Match score (0-100)
Title 40 · OSS/BSS/telecom keywords 35 · network technology (GPON, DOCSIS, MPLS, SDH, DWDM…) 10 · architecture/GCP 5 ·
seniority 5 · salary 5; penalties for junior titles, low pay and unverified sponsorship. Roles under `min_match` (45) are hidden.
Each card has a *Why this score* breakdown. Tune the tables in `jobmatch/score.py` and the searches in `config/profile.json`.

## Daily update
The workflow runs at 06:43 UTC (also on demand: *Actions → Refresh Mugilan matched jobs → Run workflow*). Each run refetches,
rescores and merges with the previous feed, so finds stay until they are 7 days old even if a source has a bad day.
Needs the same optional secrets as the main board: `REED_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` (free).

## Sources, honestly
* **Reed** and **Adzuna** (official APIs; Adzuna re-lists many Indeed and agency adverts). Reed's search returns only a short snippet,
  so for Reed adverts that already look promising (snippet score 20+, best first, up to `MUGILAN_DEEP_MAX`=80 per run) the full
  advert is fetched from Reed's job-details API before scoring and the clearance / sponsorship checks.
* **Employer career sites** (`config/employers.json`, empty until you add employers; Workday, Greenhouse, Lever and more).
* **LinkedIn, Indeed and Glassdoor** have no public search API and forbid scraping, so they are not read directly.
  **NHS Jobs** is not included: it has almost no telecom OSS/BSS roles.
* Without API keys the feed is empty and the page says which sources were skipped.

## Run locally
```
REED_API_KEY=… ADZUNA_APP_ID=… ADZUNA_APP_KEY=… python -m mugilan.jobmatch
python -m unittest discover -s mugilan/tests -t .
python -m http.server   # then open /mugilan/
```
