"""Deleting what the app knows about an event, when the user asks for it.

Only ever touches our own files in Application Support: never a drive, an event folder, footage or
a proxy. The journals and the list of drive copies always stay, because undo must keep working. A
clip's cache that another event in the app also uses (the same file in a test copy) stays too.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from hypershutter.core import audio_tags, config, describe, review, store, transcribe
from hypershutter.core.media import Clip
from hypershutter.core.project import Project


def _in_our_cache(path: Path) -> bool:
    return path.resolve().is_relative_to((config.app_support_dir() / "cache").resolve())


def _keys_of(data: dict) -> set[str]:
    return {store.file_key(Path(c["rel"]).name, c["size"], c["mtime"]) for c in data.get("clips", [])}


def _used_elsewhere(root: Path) -> set[str]:
    me = store.project_id(root)
    return {k for row in store.all_project_data() if row["id"] != me for k in _keys_of(row["data"])}


def _sound_texts(p: Project) -> dict[str, str]:
    """The sound text each clip was described with, when its folder is here (it names the cache file)."""
    if not Path(p.root).is_dir():
        return {}
    from hypershutter.core import pipeline
    clips = [c for c in p.clips.values() if audio_tags._cache(c).exists()]
    try:
        return pipeline.sound_texts(audio_tags.analyze_all(p, clips, p.event_type, speech=True)) if clips else {}
    except Exception:                               # those descriptions simply stay in the cache
        return {}


def _clip_files(p: Project, clip: Clip, sound: str) -> list[Path]:
    from hypershutter.core import proxies
    cache = config.app_support_dir() / "cache"
    key = store.file_key(clip.name, clip.size, clip.mtime)
    sha = hashlib.sha1(key.encode()).hexdigest()
    out = [cache / "frames" / sha[:20], cache / "sheets" / sha[:20], audio_tags._cache(clip), *describe.cache_files(clip, sound)]
    out += list((cache / "audio").glob(f"{sha}_*.npy"))
    prompt = transcribe.PROMPTS.get(p.event_type, transcribe.PROMPTS["baptism"])
    out.append(transcribe._cache(Path(clip.name), clip.size, clip.mtime, prompt))
    px = proxies.proxy_for(Path(p.root), clip.rel) if Path(p.root).is_dir() else None
    if px:                                          # the speech was read from the proxy when there was one
        st = px.stat()
        out.append(transcribe._cache(px, st.st_size, st.st_mtime, prompt))
    return out


def _files(root: Path, sound: dict[str, str] | None = None) -> list[Path]:
    p = Project.load(root)
    out = [config.app_support_dir() / "cache" / "structure" / store.project_id(root)]
    if p is None:
        return [f for f in out if f.exists()]
    keep = _used_elsewhere(root)
    for clip in p.clips.values():
        if store.file_key(clip.name, clip.size, clip.mtime) not in keep:
            out += _clip_files(p, clip, (sound or {}).get(clip.id, ""))
    return [f for f in out if f.exists()]


def _bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def size(root: Path) -> int:
    """Bytes the event's data takes on this Mac."""
    return sum(_bytes(f) for f in _files(root))


def forget(root: Path) -> int:
    """Delete the event's analysis data and its list entry; returns the bytes freed."""
    p = Project.load(root)
    files = _files(root, _sound_texts(p) if p else None)
    assert all(_in_our_cache(f) for f in files)
    freed = sum(_bytes(f) for f in files)
    for f in files:
        if f.is_dir():
            shutil.rmtree(f)
        else:
            f.unlink()
    store.delete_project(root)
    return freed
