"""Checksum manifests on every destination of an ingest (thesis §6.1).

Each destination project keeps `.hypershutter/ingest/manifest.json`: every ingested file with its
size, xxHash64 and status (copied -> verified). It makes ingest resumable and is the proof that a
card was offloaded safely. Each session also writes an ASC MHL v1.1 hash list next to the copied
files (readable by Silverstack, ShotPut Pro, Hedge and `mhl verify`) and a JSON report.
"""

from __future__ import annotations

import json
import os
import platform
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

COPIED, VERIFIED, FAILED = "copied", "verified", "failed"


@dataclass
class Entry:
    rel: str                 # relative to the destination project folder
    size: int
    xxh64: str
    status: str              # copied | verified | failed
    source: str = ""         # card identity + path on the card
    when: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class Manifest:
    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir)
        self.path = self.dir / ".hypershutter" / "ingest" / "manifest.json"
        self._lock = threading.Lock()
        self.entries: dict[str, Entry] = {}
        if self.path.exists():
            for e in json.loads(self.path.read_text()).get("files", []):
                self.entries[e["rel"]] = Entry(**e)

    def get(self, rel: str) -> Entry | None:
        return self.entries.get(rel)

    def set(self, rel: str, size: int, xxh64: str, status: str, source: str = "") -> None:
        with self._lock:
            self.entries[rel] = Entry(rel, size, xxh64, status, source, _now())

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"version": 1, "algorithm": "xxh64",
                                       "files": [asdict(e) for e in sorted(self.entries.values(), key=lambda e: e.rel)]},
                                      ensure_ascii=False, indent=1))
            os.replace(tmp, self.path)

    def verified(self, rel: str, size: int) -> bool:
        """Already ingested and verified, and the file is still there with that size."""
        e = self.entries.get(rel)
        f = self.dir / rel
        return bool(e and e.status == VERIFIED and e.size == size and f.exists() and f.stat().st_size == size)


def write_mhl(path: Path, root: Path, entries: list[Entry], started: datetime, finished: datetime) -> Path:
    """ASC MHL v1.1 hash list; file paths are relative to the folder that holds the .mhl."""
    rows = []
    for e in entries:
        if e.status != VERIFIED:
            continue
        rel = os.path.relpath(root / e.rel, path.parent)
        f = root / e.rel
        mod = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S") if f.exists() else ""
        rows.append(f"  <hash>\n    <file>{escape(rel)}</file>\n    <size>{e.size}</size>\n"
                    f"    <lastmodificationdate>{mod}</lastmodificationdate>\n    <xxhash64be>{e.xxh64}</xxhash64be>\n"
                    f"    <hashdate>{escape(e.when[:19])}</hashdate>\n  </hash>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<hashlist version="1.1">\n  <creatorinfo>\n'
           f"    <name>HyperShutter</name>\n    <username>{escape(os.environ.get('USER', ''))}</username>\n"
           f"    <hostname>{escape(platform.node())}</hostname>\n    <tool>HyperShutter ingest</tool>\n"
           f"    <startdate>{started:%Y-%m-%dT%H:%M:%S}</startdate>\n    <finishdate>{finished:%Y-%m-%dT%H:%M:%S}</finishdate>\n"
           "  </creatorinfo>\n" + "\n".join(rows) + "\n</hashlist>\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return path
