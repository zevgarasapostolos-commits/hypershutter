"""The videographer's music and sound-effect library, learned from his own Premiere projects.

For now HyperShutter uses only music and SFX the videographer has already used (his choice).
`learn()` reads a finished project: the songs of the highlights in order of appearance get
roles (intro, story, ceremony, party), the music under the ροή becomes beds, and the short
sounds become whooshes, ambiences and the film-projector sound. Baptisms always use the same
song. The library lives in Application Support (it holds paths on the user's disks).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hypershutter.core import config, prproj

ROLES = ("intro", "story", "ceremony", "party")
SFX_KINDS = {"whoosh": r"whoosh|swoosh|swish", "projector": r"super ?8|projector|8mm|film",
             "ambience": r"wind|bird|nature|ambien|atmosphere|water|stream|forest|rome|vespa"}
CAMERA = re.compile(r"^(C\d{4}|DJI_|C3\d{3})", re.I)


def path() -> Path:
    return config.app_support_dir() / "library.json"


def load() -> dict:
    p = path()
    return json.loads(p.read_text()) if p.exists() else {}


def save(lib: dict) -> None:
    path().write_text(json.dumps(lib, ensure_ascii=False, indent=1))


def _is_camera(p: str) -> bool:
    return bool(CAMERA.match(Path(p).name))


def learn(project: Path, event_type: str) -> dict:
    """Songs, beds and SFX of a finished project (read on a copy), merged into the library."""
    _, seqs = prproj.load(project)
    entry = {"highlights": [], "beds": [], "sfx": {k: [] for k in SFX_KINDS}, "source": Path(project).name}
    for name, info in seqs.items():
        low = name.lower()
        audio = [i for i in info.items if i.track.startswith("A") and i.path and not _is_camera(i.path)]
        total: dict[str, float] = {}
        first: dict[str, float] = {}
        for i in audio:
            total[i.path] = total.get(i.path, 0.0) + i.duration
            first[i.path] = min(first.get(i.path, 1e9), i.start)
        for p, d in total.items():
            nm = Path(p).name
            kind = next((k for k, rx in SFX_KINDS.items() if re.search(rx, nm, re.I)), None)
            if kind and d < 120:
                if p not in entry["sfx"][kind]:
                    entry["sfx"][kind].append(p)
            elif d >= 20 and "highlight" in low:
                entry["highlights"].append((first[p], p))
            elif d >= 20 and ("ροη" in low or "ροή" in low or "flow" in low):
                if p not in entry["beds"]:
                    entry["beds"].append(p)
    songs = [p for _, p in sorted(entry["highlights"])]
    songs = [p for p in songs if not re.search(r"esv2|bg-m|music-m", Path(p).name)]   # separated stems of an earlier export
    roles = ROLES if len(songs) >= 4 else ("intro", "ceremony", "party")[: len(songs)]
    entry["highlights"] = [{"role": r, "path": p} for r, p in zip(roles, songs)]
    lib = load()
    lib[event_type] = entry
    save(lib)
    return entry


def set_baptism_song(song: Path) -> None:
    lib = load()
    lib["baptism"] = {"highlights": [{"role": "song", "path": str(song)}], "beds": [], "sfx": {k: [] for k in SFX_KINDS}}
    save(lib)


def resolve(p: str) -> Path | None:
    """The file, also when the two T7 drives swapped mount names since it was learned."""
    path_ = Path(p)
    if path_.exists():
        return path_
    for a, b in (("/Volumes/T7 1/", "/Volumes/T7/"), ("/Volumes/T7/", "/Volumes/T7 1/")):
        if p.startswith(a) and Path(b + p[len(a):]).exists():
            return Path(b + p[len(a):])
    return None


def song(event_type: str, role: str) -> Path | None:
    for s in load().get(event_type, {}).get("highlights", []):
        if s["role"] == role and resolve(s["path"]):
            return resolve(s["path"])
    return None


def sfx(event_type: str, kind: str) -> list[Path]:
    return [r for p in load().get(event_type, {}).get("sfx", {}).get(kind, []) if (r := resolve(p))]


def beds(event_type: str) -> list[Path]:
    return [r for p in load().get(event_type, {}).get("beds", []) if (r := resolve(p))]
