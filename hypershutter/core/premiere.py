"""Write the highlights and ροή sequences (Premiere XML) and their previews for an event.

Output goes to the event folder, as the videographer keeps it: `<event> highlights.xml`,
`<event> ροή.xml`, `<NNN> highlights - preview (για έλεγχο).mp4`, the song in `music/`.
Reference projects are read-only, so their output goes to the repo's `reports/edit/` instead.
Existing files are never overwritten: a new name gets « (2)», « (3)» ….
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from hypershutter.core import config, describe, edit, edit_wedding, execute, frames, library, music, preview, xmeml
from hypershutter.core.project import Project
from hypershutter.core.structure import Structure

Progress = Callable[[str, int, int], None]


def read_only(p: Project) -> bool:
    try:
        execute.check_allowed(p, force=True)
        return False
    except PermissionError:
        return True


def output_dir(p: Project) -> Path:
    if read_only(p):
        return config.REPO_ROOT / "reports" / "edit" / p.name.strip()
    return Path(p.root)


def descriptions(p: Project, st: Structure) -> dict[str, dict]:
    """Pass-1 descriptions from the cache (never calls the API)."""
    fs = frames.FrameSettings()
    model = (st.usage or {}).get("model") or "claude-opus-5-5"
    return {cid: describe.cached(p, p.clips[cid], model, fs) or {} for cid in st.assignment if cid in p.clips}


def template(event_type: str) -> dict:
    t = config.load_preset(event_type).get("highlights")
    return t or config.load_preset("baptism")["highlights"]


def _free(path: Path) -> Path:
    if not path.exists():
        return path
    k = 2
    while (path.with_name(f"{path.stem} ({k}){path.suffix}")).exists():
        k += 1
    return path.with_name(f"{path.stem} ({k}){path.suffix}")


def _number(p: Project) -> str:
    first = p.name.strip().split(" ")[0]
    return first if first.isdigit() else p.name.strip()


def export(p: Project, st: Structure, song: Path | None = None, with_preview: bool = True,
           which: tuple[str, ...] = ("highlights", "flow"), progress: Progress | None = None) -> dict:
    root = Path(p.root)
    if p.event_type == "wedding":
        return _export_wedding(p, st, with_preview, which, progress)
    song = Path(song) if song else music.find_song(root) or library.song("baptism", "song")
    if song is None or not song.exists():
        raise FileNotFoundError("no song: put it in the event's music/ folder or choose one")
    out = output_dir(p)
    out.mkdir(parents=True, exist_ok=True)
    if not read_only(p) and song.parent != root / "music":
        target = root / "music" / song.name
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(song, target)                    # the song travels with the event
        song = target
    descs = descriptions(p, st)
    base, num = p.name.strip(), _number(p)
    result: dict = {"dir": str(out), "song": str(song), "warnings": []}
    if progress:
        progress("highlights", 0, 1)
    hl = edit.build_highlights(p, st, descs, song, template(p.event_type))
    result["warnings"] += hl.warnings
    seqs = []
    if "highlights" in which:
        seqs.append(("highlights", edit.highlights_sequence(f"{base} highlights", hl), f"{num} highlights"))
    if "flow" in which:
        fl = edit.build_flow(f"{base} ροή", p, st, descs, hl, _mic(p))
        result["warnings"] += fl.warnings
        result["flow_minutes"] = fl.minutes
        seqs.append(("flow", fl.seq, f"{num} ροή"))
    for key, seq, pv in seqs:
        problems = seq.check()
        if problems:
            raise RuntimeError(f"{key}: " + "; ".join(problems[:5]))
        xml = _free(out / f"{seq.name}.xml")
        xml.write_text(xmeml.to_xml(seq), encoding="utf-8")
        result[key] = {"xml": str(xml), "seconds": round(seq.duration / xmeml.FPS, 1),
                       "clips": sum(len(t) for t in seq.video)}
        if with_preview:
            mp4 = _free(out / f"{pv} - preview (για έλεγχο).mp4")
            preview.render(seq, mp4, progress=progress)
            result[key]["preview"] = str(mp4)
    return result


def _mic(p: Project):
    rec = [c for c in p.clips.values() if c.kind == "audio" and p.devices.get(c.device) and p.devices[c.device].kind == "recorder"]
    return max(rec, key=lambda c: c.duration) if rec else None


def _localize(p: Project, seq: xmeml.Sequence) -> None:
    """Songs and SFX are copied into the event's music/ folder, so the XML never points outside it."""
    if read_only(p):
        return
    root = Path(p.root)
    copies: dict[str, str] = {}
    for tr in seq.audio:
        for it in tr:
            src = Path(it.media.path)
            if it.media.has_video or root in src.parents:
                continue
            if str(src) not in copies:
                target = root / "music" / src.name
                if not target.exists():
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(src, target)
                copies[str(src)] = str(target)
            it.media = xmeml.Media(copies[str(src)], it.media.duration, it.media.fps, it.media.width, it.media.height,
                                   False, it.media.audio_channels)


def _export_wedding(p: Project, st: Structure, with_preview: bool, which: tuple[str, ...],
                    progress: Progress | None) -> dict:
    out = output_dir(p)
    out.mkdir(parents=True, exist_ok=True)
    descs = descriptions(p, st)
    base, num = p.name.strip(), _number(p)
    result: dict = {"dir": str(out), "song": "library (wedding)", "warnings": []}
    seqs = []
    if "highlights" in which:
        if progress:
            progress("highlights", 0, 1)
        hl = edit_wedding.build(p, st, descs)
        result["warnings"] += hl.warnings
        seqs.append(("highlights", edit_wedding.sequence(f"{base} highlights", hl), f"{num} highlights"))
    if "flow" in which:
        fl = edit_wedding.build_flow(f"{base} ροή", p, st, descs)
        result["warnings"] += fl.warnings
        result["flow_minutes"] = fl.minutes
        seqs.append(("flow", fl.seq, f"{num} ροή"))
    for key, seq, pv in seqs:
        _localize(p, seq)
        problems = seq.check()
        if problems:
            raise RuntimeError(f"{key}: " + "; ".join(problems[:5]))
        xml = _free(out / f"{seq.name}.xml")
        xml.write_text(xmeml.to_xml(seq), encoding="utf-8")
        result[key] = {"xml": str(xml), "seconds": round(seq.duration / xmeml.FPS, 1),
                       "clips": sum(len(t) for t in seq.video)}
        if with_preview:
            mp4 = _free(out / f"{pv} - preview (για έλεγχο).mp4")
            preview.render(seq, mp4, progress=progress)
            result[key]["preview"] = str(mp4)
    return result
