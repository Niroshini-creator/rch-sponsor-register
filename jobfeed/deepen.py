"""Read the whole advert for jobs whose source only returns a short snippet (Reed), so their digest covers the full text.

Adverts already read in full when fetched (career-site systems, NHS Jobs and jobs.ac.uk pages) need nothing here. Reed's detail call
is made once per job: a job seen in the previous feed reuses that feed's digest, and each run reads at most REED_DEEP_MAX new ones.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Iterable

from . import sources
from .models import Job

log = logging.getLogger("jobfeed")
REED_DEEP_MAX = int(os.environ.get("REED_DEEP_MAX", "200"))
PAUSE = 0.2


def previous_digests(path: Path) -> dict[str, tuple[list[str], str, int]]:
    """job id -> (kw, signals, text_len) from the feed published last time, for jobs whose full text was read then."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {j["id"]: (j.get("kw") or [], j.get("signals") or "", int(j.get("text_len") or 0))
            for j in data.get("jobs", []) if j.get("id") and (j.get("text_len") or 0) > 600}


def read_full_adverts(jobs: Iterable[Job], seen: dict, reed_text: Callable[[str], str] = sources.reed_job_text) -> int:
    """Replace the snippet of up to REED_DEEP_MAX unseen Reed jobs with the full advert. Returns how many were read."""
    read = 0
    for job in jobs:
        if job.source != "Reed" or job.id in seen or len(job.description) > 1500:
            continue
        if read >= REED_DEEP_MAX:
            break
        try:
            text = reed_text(job.source_id)
        except sources.SkipSource:
            break
        except Exception as err:  # noqa: BLE001 - keep the snippet when one advert can't be read
            log.warning("Reed advert %s unavailable: %s", job.source_id, err)
            continue
        if len(text) > len(job.description):
            job.description = text
            read += 1
        time.sleep(PAUSE)
    return read


def reuse_digest(job: Job, seen: dict) -> None:
    """A job read in full last time keeps that digest when this run only has its snippet."""
    old = seen.get(job.id)
    if old and old[2] > job.text_len:
        job.kw, job.signals, job.text_len = old[0], old[1], old[2]
