"""Tiny HTTP helpers built on urllib."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "rch-sponsor-register/1.0 (+https://github.com/niroshini-creator/rch-sponsor-register)"
TIMEOUT = 30
RETRIES = int(os.environ.get("JOBFEED_RETRIES", "3"))


def get(url: str, params: dict | None = None, headers: dict | None = None,
        basic_auth: tuple[str, str] | None = None, retries: int = RETRIES, json_body: dict | None = None) -> bytes:
    """GET `url`, or POST `json_body` as JSON when given."""
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params, doseq=True)}"
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    hdrs.update(headers or {})
    if basic_auth:
        token = base64.b64encode(f"{basic_auth[0]}:{basic_auth[1]}".encode()).decode()
        hdrs["Authorization"] = f"Basic {token}"

    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs, data=data)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            # 4xx other than rate limiting will not improve on retry.
            if 400 <= err.code < 500 and err.code != 429:
                raise
            last_err = err
        except (urllib.error.URLError, TimeoutError) as err:
            last_err = err
        if attempt + 1 < retries:
            time.sleep(2 ** (attempt + 1))
    assert last_err is not None
    raise last_err


def get_json(url: str, **kwargs):
    return json.loads(get(url, headers={"Accept": "application/json"}, **kwargs))


def post_json(url: str, body: dict, **kwargs):
    return get_json(url, json_body=body, **kwargs)


def get_text(url: str, **kwargs) -> str:
    return get(url, **kwargs).decode("utf-8", errors="replace")
