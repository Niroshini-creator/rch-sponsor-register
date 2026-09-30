"""Text normalisation shared by the matching and classification code."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Legal suffixes and filler words dropped when comparing employer names.
_NAME_NOISE = {
    "ltd", "limited", "plc", "llp", "llc", "inc", "incorporated", "corp", "corporation", "sl",
    "co", "company", "group", "holdings", "uk", "gb", "the", "and", "gmbh", "ag", "bv",
    "nv", "sa", "sas", "sarl", "srl", "spa", "ab", "as", "oy", "se", "kg",
}


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = _TAG_RE.sub(" ", html.unescape(value))
    return _WS_RE.sub(" ", html.unescape(text)).strip()


def normalise_company(name: str | None) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()  # "Nestlé" -> "Nestle"
    name = name.lower().replace("&", " and ")
    name = re.sub(r"\(.*?\)", " ", name).replace(".", "")  # "N.V." -> "nv"
    name = re.sub(r"[^a-z0-9 ]+", " ", name)
    words = [w for w in name.split() if w not in _NAME_NOISE]
    return " ".join(words)


def parse_date(value) -> datetime | None:
    """Parse the assorted date formats job APIs return into aware UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    value = str(value).strip()
    if value.isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc)

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:  # RFC 822, as used by RSS feeds
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
