"""Paths, tool discovery and preset loading.

All caches and state live under ~/Library/Application Support/HyperShutter/,
never inside an event folder (event folders are read-only until Apply).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

APP_NAME = "HyperShutter"
REPO_ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = REPO_ROOT / "presets"

# Homebrew locations first: a GUI app launched from Finder does not get the shell PATH.
_TOOL_DIRS = ["/opt/homebrew/bin", "/usr/local/bin"]


def app_support_dir() -> Path:
    """State/caches root. Override with HYPERSHUTTER_HOME (used by tests)."""
    override = os.environ.get("HYPERSHUTTER_HOME")
    root = Path(override) if override else Path.home() / "Library" / "Application Support" / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir(*parts: str) -> Path:
    d = app_support_dir().joinpath("cache", *parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_tool(name: str) -> str | None:
    for d in _TOOL_DIRS:
        p = Path(d) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(name)


@dataclass
class ToolStatus:
    name: str
    path: str | None
    version: str | None

    @property
    def ok(self) -> bool:
        return self.path is not None


def check_tool(name: str) -> ToolStatus:
    path = find_tool(name)
    if not path:
        return ToolStatus(name, None, None)
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"version (\S+)", out)
        return ToolStatus(name, path, m.group(1) if m else "unknown")
    except (OSError, subprocess.TimeoutExpired):
        return ToolStatus(name, path, None)


def ffmpeg_has_filter(filter_name: str) -> bool:
    """Homebrew's default ffmpeg build has no drawtext; callers fall back to PIL labels."""
    path = find_tool("ffmpeg")
    if not path:
        return False
    out = subprocess.run([path, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [filter_name] for line in out.splitlines() if len(line.split()) > 1)


def load_preset(event_type: str) -> dict:
    """Preset = hints for the model plus naming rules. Never a fixed category list."""
    path = PRESETS_DIR / f"{event_type}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No preset for event type '{event_type}' ({path})")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
