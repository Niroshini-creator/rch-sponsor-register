"""A compact digest of a job's whole advert, so the browser can match it without downloading the whole text.

The feed publishes only the first 400 characters of each advert, but the pipeline reads the full text (career-site systems,
NHS Jobs and jobs.ac.uk pages, Reed's detail call). From that full text this module records
  kw        every role-family keyword (candidateboard/roles.json) the advert uses: the CV's skills are drawn from the same list,
            so the browser can count skill matches against the full advert exactly;
  signals   the sentences that mention clearance, driving, nationality, right to work, sponsorship or language, which the
            browser's clearance / licence / nationality checks read;
  text_len  the length of the full text (a short text is only an extract, a long one a full advert).
"""

from __future__ import annotations

import re
from functools import lru_cache

from candidateboard import taxonomy

SIGNAL_RE = re.compile(
    r"clearance|\bbpss\b|\bsc\b|\bdv\b|security check|vetting|driving licen|driver|own (?:vehicle|transport|car)|right to work|"
    r"citizen|nationals?\b|nationality|\bbritish\b|visa|sponsor|permit|fluent|language|\bgerman\b|\bdutch\b|\bfrench\b", re.I)
SIGNALS_MAX = 600
_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


@lru_cache(maxsize=1)
def _keywords() -> list[tuple[str, re.Pattern]]:
    seen: dict[str, re.Pattern] = {}
    for fam in taxonomy.load().families.values():
        for term, rx in fam.keywords:
            seen.setdefault(term, rx)
    return list(seen.items())


def digest(title: str, text: str) -> tuple[list[str], str, int]:
    whole = f"{title}\n{text}"
    kw = [term for term, rx in _keywords() if rx.search(whole)]
    signals, total = [], 0
    if len(text) > 400:         # a shorter advert is already inside the published description
        for sentence in _SPLIT_RE.split(text):
            sentence = sentence.strip()
            if sentence and SIGNAL_RE.search(sentence) and sentence not in signals:
                sentence = sentence[:240]
                signals.append(sentence)
                total += len(sentence) + 1
                if total >= SIGNALS_MAX:
                    break
    return kw, " ".join(signals), len(text)
