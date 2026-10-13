# Candidate matcher (test version)

A browser-only page, served by GitHub Pages at `/matcher/` beside the main sponsored-jobs board and `/mugilan/`.
Candidates add their CVs, visa details and preferred roles and see vacancies matched to them, with the visa salary check,
hiring contacts, a career-sites directory and an application tracker.

* **No server, no accounts.** Each tester's profile, CV text and tracked jobs are saved only in their own browser; nothing
  is uploaded and nothing is stored in this repository.
* **It reads this site's own `data/jobs.json`** (`../data/jobs.json`), so it is as fresh as the sponsored-jobs board and
  needs no separate data pipeline. It does not change the board, the feed or any workflow.
* **Not edited here.** The files are built from the `candidate-job-matcher` repository
  (`python -m matcher.build_static --jobs data/jobs.json --out matcher --jobs-url ../data/jobs.json`, then drop the
  generated `.nojekyll`). To update the page, rebuild there and replace this folder.
* India vacancies appear only once this feed carries Indian jobs (the board's feed doesn't yet).
