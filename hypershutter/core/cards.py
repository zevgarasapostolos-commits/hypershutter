"""Memory cards: find them under /Volumes, recognize the camera by the card's folder structure, and
remember the source label the videographer gave each camera (thesis §6.1).

A card is only ever read: nothing here opens a file on a card for writing.
"""

from __future__ import annotations

import json
import os
import shutil
import plistlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hypershutter.core import config
from hypershutter.core.media import AUDIO_EXT, SIDECAR_EXT, VIDEO_EXT

VOLUMES = Path("/Volumes")
SKIP_DIRS = {".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems", ".DocumentRevisions-V100",
             "System Volume Information", "THMBNL", "$RECYCLE.BIN"}
SONY_PROXY_DIR = "SUB"                      # the camera's own low-res proxies (C0001S03.MP4): not footage
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT | SIDECAR_EXT


@dataclass
class CardFile:
    rel: str                                 # path on the card
    size: int
    mtime: float


@dataclass
class Card:
    path: str
    name: str
    kind: str                                # sony | avchd | dji_drone | recorder | dcim | generic
    identity: str                            # camera model + serial, else the volume UUID
    camera: str = ""                         # e.g. "Sony ILCE-7SM3"
    files: list[CardFile] = field(default_factory=list)
    label: str = ""                          # remembered source label, e.g. "cam apos"

    @property
    def bytes(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def media(self) -> list[CardFile]:
        return [f for f in self.files if Path(f.rel).suffix.lower() in VIDEO_EXT | AUDIO_EXT]


def _walk(root: Path, include_camera_proxies: bool = False) -> list[CardFile]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                       and (include_camera_proxies or d != SONY_PROXY_DIR)]
        for n in filenames:
            if n.startswith("."):
                continue
            if Path(n).suffix.lower() in MEDIA_EXT:
                f = Path(dirpath) / n
                st = f.stat()
                out.append(CardFile(str(f.relative_to(root)), st.st_size, st.st_mtime))
    return sorted(out, key=lambda f: f.rel)


def kind_of(root: Path, files: list[CardFile]) -> str:
    if (root / "PRIVATE" / "M4ROOT" / "CLIP").is_dir() or (root / "PRIVATE" / "XDROOT").is_dir():
        return "sony"
    if (root / "PRIVATE" / "AVCHD").is_dir():
        return "avchd"
    names = [Path(f.rel).name for f in files]
    if (root / "DCIM").is_dir() and any(n.upper().startswith("DJI_") for n in names):
        return "dji_drone"
    media = [f for f in files if Path(f.rel).suffix.lower() in VIDEO_EXT | AUDIO_EXT]
    if media and sum(Path(f.rel).suffix.lower() in AUDIO_EXT for f in media) > len(media) / 2:
        return "recorder"
    if (root / "DCIM").is_dir():
        return "dcim"
    return "generic"


SONY_DEVICE = re.compile(r'<Device[^>]*manufacturer="([^"]*)"[^>]*modelName="([^"]*)"(?:[^>]*serialNo="([^"]*)")?')


def _sony_camera(root: Path, files: list[CardFile]) -> tuple[str, str]:
    for f in files:
        if f.rel.upper().endswith(".XML"):
            try:
                m = SONY_DEVICE.search((root / f.rel).read_text(errors="ignore")[:20000])
            except OSError:
                continue
            if m:
                serial = m.group(3) or ""
                if serial == "4294967295" or not serial.strip("0"):      # a placeholder: two bodies would look the same
                    serial = ""
                return f"{m.group(1)} {m.group(2)}", f"{m.group(2)}:{serial}" if serial else ""
    return "", ""


def volume_uuid(path: Path) -> str:
    try:
        r = subprocess.run(["diskutil", "info", "-plist", str(path)], capture_output=True, timeout=10)
        return plistlib.loads(r.stdout).get("VolumeUUID", "") if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return ""


def read_card(path: Path, include_camera_proxies: bool = False) -> Card:
    """What is on a card (or on a folder copied from one), without changing anything on it."""
    root = Path(path)
    files = _walk(root, include_camera_proxies)
    kind = kind_of(root, files)
    camera, ident = _sony_camera(root, files) if kind == "sony" else ("", "")
    if not ident:
        uuid = volume_uuid(root) if str(root).startswith(str(VOLUMES)) else ""
        ident = f"volume:{uuid}" if uuid else f"path:{root.name}"
    card = Card(str(root), root.name, kind, f"{kind}:{ident}", camera, files)
    card.label = labels().get(card.identity, "")
    return card


RECORDER_DIRS = ("ZOOM", "FOLDER01", "MUSIC", "SOUND", "RECORD", "RECORDINGS")
SMALL_VOLUME = 512 * 10**9                  # a bare-audio volume above this is a drive, not a recorder card


def looks_like_card(path: Path) -> bool:
    """Only by the card's own structure: a working drive full of projects is never walked."""
    if (path / "DCIM").is_dir() or (path / "PRIVATE" / "M4ROOT").is_dir() or (path / "PRIVATE" / "AVCHD").is_dir() \
            or (path / "PRIVATE" / "XDROOT").is_dir():
        return True
    if any((path / d).is_dir() for d in RECORDER_DIRS):
        return True
    try:                                         # recorders that write WAVs at the root of a small card
        return shutil.disk_usage(path).total < SMALL_VOLUME and any(
            p.suffix.lower() in AUDIO_EXT for p in path.iterdir() if p.is_file())
    except OSError:
        return False


def detect(volumes: Path = VOLUMES) -> list[Card]:
    """Mounted volumes that look like camera or recorder cards (by structure only)."""
    out = []
    for v in sorted(volumes.iterdir()) if volumes.exists() else []:
        try:
            if v.is_dir() and not v.is_symlink() and looks_like_card(v):
                out.append(read_card(v))
        except OSError:
            continue
    return out


# ---------------- remembered labels ----------------

def _labels_file() -> Path:
    return config.app_support_dir() / "card_labels.json"


def labels() -> dict[str, str]:
    f = _labels_file()
    return json.loads(f.read_text()) if f.exists() else {}


def remember(identity: str, label: str) -> None:
    d = labels()
    d[identity] = label.strip()
    _labels_file().write_text(json.dumps(d, ensure_ascii=False, indent=1))
