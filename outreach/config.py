"""Paths and config loading."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "outreach.json"
TEMPLATE_DIR = ROOT / "templates" / "outreach"


def data_dir() -> Path:
    """Where contacts, the ledger and the suppression list live. Never commit this folder:
    it holds personal data. Override with OUTREACH_DATA."""
    return Path(os.environ.get("OUTREACH_DATA", ROOT / "outreach_data"))


def load_config(path: Path | None = None) -> dict:
    cfg = json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
    missing = [k for k in ("name", "company", "address", "email") if not cfg.get("sender", {}).get(k)]
    if missing:
        raise ValueError(f"config/outreach.json: sender.{', sender.'.join(missing)} must be set "
                         "(PECR requires your identity and a contact address in every message)")
    return cfg
