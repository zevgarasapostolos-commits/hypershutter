"""User settings (Application Support/settings.json). The API key is not here: it is in the Keychain."""

from __future__ import annotations

import json
from pathlib import Path

from hypershutter.core import config

DEFAULTS = {
    "language": "en",
    "frame_interval": 2.0,             # seconds per frame (1, 2 or 4)
    "use_sound": True,                 # sound analysis in the sorting
    "proxy_preset": "prores_proxy",
    "make_proxies": True,
    "export_preset": "h264_1080_review",
    "hash": "xxh64",
    "destinations": [],                # default ingest destinations
    "backup_destination": "",
    "rename_pattern": "",              # empty = keep the camera names
    "warn_percent": 10.0,
    "warn_gb": 50.0,
    "critical_gb": 10.0,
    "support_email": "support@hypershutter.app",       # placeholder until the user gives one
    "issues_url": "https://github.com/zevgarasapostolos-commits/hypershutter/issues",
    "onboarded": False,
}


def _file() -> Path:
    return config.app_support_dir() / "settings.json"


def load() -> dict:
    f = _file()
    d = dict(DEFAULTS)
    if f.exists():
        try:
            d.update(json.loads(f.read_text()))
        except json.JSONDecodeError:
            pass
    return d


def save(changes: dict) -> dict:
    d = load()
    for k, v in changes.items():
        if k in DEFAULTS:
            d[k] = v
    _file().write_text(json.dumps(d, ensure_ascii=False, indent=1))
    th = config.app_support_dir() / "drive_thresholds.json"          # read by drives.py
    th.write_text(json.dumps({"warn_percent": d["warn_percent"], "warn_gb": d["warn_gb"], "critical_gb": d["critical_gb"]}))
    return d
