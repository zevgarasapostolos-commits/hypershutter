"""The shot index (`00 EVRETIRIO PLANON.md`) and one contact sheet per folder, written by Apply.

Format as in the videographer's own index (CLAUDE.md 4.5): title, one bold summary line,
camera legend, clock-correction note, a one-line timeline of the day, then per folder a Greek
sentence, `**N πλάνα · X λεπτά**` and the table of clips on the corrected timeline.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from hypershutter.core import frames, sheets
from hypershutter.core.execute import full_assignment
from hypershutter.core.greeklish import to_greeklish
from hypershutter.core.media import fmt_duration, fmt_offset
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, FLOW, UNUSABLE, Structure

TYPE_EL = {"baptism": "Βάφτιση", "wedding": "Γάμος", "event": "Εκδήλωση"}
TIMELINE_GAP = timedelta(minutes=20)          # a folder filmed twice in the day shows twice
SHEET_LAYOUT = sheets.SheetLayout(width=2576, cols=7, rows=1000)


def index_filename(preset: dict) -> str:
    n = preset["naming"]
    return f"00 {to_greeklish(n['index_label'], n['greeklish_style'])}.md"


def sheets_dir(preset: dict) -> str:
    return preset["naming"]["contact_sheets_dir"]


def _time_of_day(t: datetime) -> str:
    return "πρωινή" if t.hour < 12 else "μεσημεριανή" if t.hour < 15 else "απογευματινή" if t.hour < 19 else "βραδινή"


def _members(p: Project, st: Structure) -> dict[str, list[str]]:
    assign = full_assignment(p, st)
    out: dict[str, list[str]] = {c.key: [] for c in st.categories}
    for cid in sorted(assign, key=lambda x: (p.corrected(p.clips[x]) or datetime.min, x)):
        if assign[cid] in out:
            out[assign[cid]].append(cid)
    return out


def _legend(p: Project) -> str:
    devs = sorted(p.devices.values(), key=lambda d: ({"camera": 0, "drone": 1}.get(d.kind, 2), -len(d.clips), d.id))
    main = next((d.id for d in devs if d.kind == "camera"), None)
    parts = []
    for d in devs:
        n = len(d.clips)
        if d.kind == "camera":
            parts.append(f"Κάμερα {d.id} = `{d.pattern}` ({'κύρια, ' if d.id == main else ''}{n} κλιπ)")
        elif d.kind == "drone":
            parts.append(f"`{d.id}` = drone ({n} κλιπ)")
        else:
            parts.append(f"`{d.id}` = ηχογράφηση ({n} αρχεία)")
    return " · ".join(parts) + "."


def _clock_notes(p: Project) -> list[str]:
    notes = []
    for d in sorted(p.devices.values(), key=lambda d: d.id):
        if d.drift_status not in ("auto", "manual") or abs(d.drift) < 60:
            continue
        who = "της κάμερας " + d.id if d.kind == "camera" else f"του `{d.id}`"
        line = f"> **Το ρολόι {who} ήταν λάθος κατά {fmt_offset(d.raw_offset)}.**"
        if d.drift_status == "manual":
            line += " Η διόρθωση ορίστηκε με το χέρι."
        else:
            proofs = []
            for e in d.evidence:
                n, h = p.clips.get(e.get("needle")), p.clips.get(e.get("hay"))
                if n and h and 0 <= e.get("at", -1) <= h.duration:
                    proofs.append(f"το `{n.name}` ({n.device}) πέφτει μέσα στο `{h.name}` ({h.device})")
                if len(proofs) == 2:
                    break
            line += (" Βρέθηκε από τον κοινό ήχο: " + ", και ".join(proofs) + "." if proofs
                     else " Βρέθηκε από τον κοινό ήχο των καμερών.")
        notes.append(line + " Όλες οι ώρες είναι διορθωμένες.")
    return notes


def _timeline(p: Project, st: Structure, members: dict[str, list[str]]) -> str:
    groups: dict[int, dict] = {}
    for c in st.categories:
        if c.kind == UNUSABLE:
            continue
        g = groups.setdefault(c.number, {"label": c.label_el, "ceremony": False, "times": []})
        if not c.sub:
            g["label"] = c.label_el
        if c.kind in (FLOW, BROLL):
            g["ceremony"] = True
            g["label"] = c.label_el.split(" — ")[0]
        for cid in members[c.key]:
            clip = p.clips[cid]
            t = p.corrected(clip)
            if t:
                g["times"].append((t, t + timedelta(seconds=clip.duration)))
    segments = []
    for g in groups.values():
        spans = sorted(g["times"])
        start = end = None
        for a, b in spans:
            if start is not None and a - end > TIMELINE_GAP:
                segments.append((start, end, g))
                start = None
            if start is None:
                start, end = a, b
            end = max(end, b)
        if start is not None:
            segments.append((start, end, g))
    out = []
    for a, b, g in sorted(segments, key=lambda s: s[0]):
        when = f"{a:%H:%M}" if f"{a:%H:%M}" == f"{b:%H:%M}" else f"{a:%H:%M}–{b:%H:%M}"
        text = f"{g['label']} {when}"
        out.append(f"**{text}**" if g["ceremony"] else text)
    return " · ".join(out)


def render_index(p: Project, st: Structure, preset: dict) -> str:
    members = _members(p, st)
    clips = [p.clips[c] for ids in members.values() for c in ids]
    times = [t for t in (p.corrected(c) for c in clips) if t]
    first = min(times) if times else None
    n_video = sum(c.kind == "video" for c in clips)
    n_audio = sum(c.kind == "audio" for c in clips)
    folders = [c for c in st.categories if members[c.key]]
    title = TYPE_EL.get(p.event_type, "Εκδήλωση") + (f" {p.event_name.strip()}" if p.event_name.strip() else "")
    when = f", {first.day}/{first.month}/{first.year} ({_time_of_day(first)})" if first else ""
    lines = [f"# {p.name.strip()} — ευρετήριο πλάνων", "",
             f"**{title}{when}.** {n_video} βίντεο" + (f" και {n_audio} αρχεία ήχου" if n_audio else "")
             + f" σε {len(folders)} φακέλους.", "", _legend(p), ""]
    for note in _clock_notes(p):
        lines += [note, ""]
    lines += [f"**Χρονολόγιο:** {_timeline(p, st, members)}", "",
              f"Contact sheet ανά φάκελο: `{sheets_dir(preset)}/`", ""]
    stars = set(st.stars)
    for c in folders:
        ids = members[c.key]
        minutes = sum(p.clips[x].duration for x in ids) / 60
        lines += [f"## {c.folder}", ""]
        if c.description_el:
            lines += [c.description_el, ""]
        lines += [f"**{len(ids)} πλάνα · {minutes:.1f} λεπτά**", "", "| clip | κάμ. | ώρα | διάρκεια |", "|---|---|---|---|"]
        for cid in ids:
            clip = p.clips[cid]
            t = p.corrected(clip)
            star = " ⭐" if cid in stars else ""
            lines.append(f"| `{clip.name}`{star} | {clip.device} | {t:%H:%M:%S} | {fmt_duration(clip.duration)} |"
                         if t else f"| `{clip.name}`{star} | {clip.device} | — | {fmt_duration(clip.duration)} |")
        lines.append("")
    return "\n".join(lines)


def folder_sheets(p: Project, st: Structure, preset: dict) -> list[tuple[str, bytes]]:
    """One sheet per folder named by its number (`08a.jpg`): the middle frame of each clip,
    labelled `clip time duration`, 7 across."""
    fs = frames.FrameSettings()
    members = _members(p, st)
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for c in st.categories:
            tiles = []
            for cid in members[c.key]:
                clip = p.clips[cid]
                fr = frames.load_cached(clip, fs) or []
                if not fr:
                    continue
                t = p.corrected(clip)
                label = f"{os.path.splitext(clip.name)[0]} {t:%H:%M:%S} {fmt_duration(clip.duration)}" if t else clip.name
                tiles.append((fr[len(fr) // 2].path, label))
            if not tiles:
                continue
            name = f"{c.number:02d}{c.sub}.jpg"
            target = Path(tmp) / name
            sheets.render(tiles, SHEET_LAYOUT, target, for_model=False)
            out.append((f"{sheets_dir(preset)}/{name}", target.read_bytes()))
    return out


def generated_files(p: Project, st: Structure, preset: dict) -> list[tuple[str, bytes]]:
    """Everything Apply writes besides moving footage."""
    files = [(index_filename(preset), render_index(p, st, preset).encode("utf-8"))]
    return files + folder_sheets(p, st, preset)
