import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hypershutter.core import config, execute, index
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, FLOW, NORMAL, Category, Structure

PRESET = config.load_preset("baptism")
T0 = datetime(2026, 10, 11, 16, 0, 0)

FILES = {   # rel: (device, minutes after T0, duration, sidecars)
    "cam apos/C0001.MP4": ("A", 0, 6, ["cam apos/C0001M01.XML"]),
    "cam apos/C0002.MP4": ("A", 1, 5, []),
    "cam apos/C0003.MP4": ("A", 30, 120, []),
    "cam dim/C6501.MP4": ("B", 31, 8, ["cam dim/C6501.THM"]),
    "drone/DJI_20261011160300_0001_D.MP4": ("DJI", 3, 12, ["drone/DJI_20261011160300_0001_D.SRT"]),
    "sound/DJI_01_20261011_163000.WAV": ("REC", 30, 100, []),
}


@pytest.fixture
def event(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "support"))
    root = tmp_path / "075 test event"
    p = Project(root=str(root), name=root.name)
    for rel, (dev, minute, dur, side) in FILES.items():
        for f in [rel, *side]:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_bytes(os.urandom(64 + len(f)))
        cid = Path(rel).stem
        wrong = timedelta(hours=-14) if dev == "A" else timedelta(0)      # camera A's clock is 14 h behind
        p.clips[cid] = Clip(id=cid, rel=rel, kind="audio" if rel.endswith(".WAV") else "video",
                            size=(root / rel).stat().st_size, mtime=(root / rel).stat().st_mtime, sidecars=side,
                            probe={"duration": dur}, device=dev,
                            nominal=(T0 + timedelta(minutes=minute) + wrong).isoformat())
    for dev, kind in (("A", "camera"), ("B", "camera"), ("DJI", "drone"), ("REC", "recorder")):
        p.devices[dev] = Device(id=dev, kind=kind, clips=[c.id for c in p.clips.values() if c.device == dev],
                                pattern=dev)
    p.devices["A"].drift, p.devices["A"].drift_status = 14 * 3600.0, "manual"
    cats = [Category("p1", 1, "", "ΣΤΟΛΙΣΜΟΣ", "01 STOLISMOS", "Στολισμός.", NORMAL),
            Category("p2", 2, "", "DRONE", "02 DRONE", "", "drone"),
            Category("p3", 3, "", "ΚΑΤΗΧΗΣΗ — ΡΟΗ", "03 KATIXISI - ROI", "", FLOW),
            Category("p4", 3, "a", "ΚΑΤΗΧΗΣΗ — B-ROLL", "03a KATIXISI - B-ROLL", "", BROLL, parent="p3")]
    assign = {"C0001": "p1", "C0002": "p1", "DJI_20261011160300_0001_D": "p2", "C0003": "p3", "C6501": "p4"}
    st = Structure(cats, assign, {k: 0.9 for k in assign}, [], stars=["C0003"])
    p.save()
    return p, st


def _snapshot(root: Path) -> dict:
    return {str(f.relative_to(root)): (f.stat().st_size, f.stat().st_mtime) for f in root.rglob("*")
            if f.is_file() and ".hypershutter" not in f.parts}


def test_plan_moves_clips_sidecars_and_overlapping_audio(event):
    p, st = event
    pl = execute.plan(p, st)
    dst = {m.src: m.dst for m in pl.moves}
    assert pl.ok and pl.folders == ["01 STOLISMOS", "02 DRONE", "03 KATIXISI - ROI", "03a KATIXISI - B-ROLL"]
    assert dst["cam apos/C0001M01.XML"] == "01 STOLISMOS/C0001M01.XML"            # sidecar travels with its clip
    assert dst["cam dim/C6501.THM"] == "03a KATIXISI - B-ROLL/C6501.THM"
    assert dst["sound/DJI_01_20261011_163000.WAV"] == "03 KATIXISI - ROI/DJI_01_20261011_163000.WAV"   # by overlap


def test_apply_then_undo_restores_everything(event):
    p, st = event
    root = Path(p.root)
    before = _snapshot(root)
    j = execute.apply(p, st, execute.plan(p, st), PRESET, extras=index.generated_files)
    assert j["status"] == "applied"
    assert (root / "01 STOLISMOS/C0001.MP4").exists() and (root / "01 STOLISMOS/C0001M01.XML").exists()
    assert not (root / "cam apos/C0001.MP4").exists() and (root / "cam apos").is_dir()   # sources stay, empty
    assert (root / "00 EVRETIRIO PLANON.md").exists()
    assert json.loads((root / ".hypershutter/journal.json").read_text())["status"] == "applied"
    assert Project.load(root).clips["C0001"].rel == "01 STOLISMOS/C0001.MP4"
    assert execute.plan(p, st).moves == []                                          # nothing left to do

    u = execute.undo(p)
    assert u["status"] == "undone" and _snapshot(root) == before
    assert not (root / "01 STOLISMOS").exists() and not (root / "00 EVRETIRIO PLANON.md").exists()
    assert Project.load(root).clips["C0001"].rel == "cam apos/C0001.MP4"


def test_journal_is_written_first_and_undo_recovers_a_failed_run(event, monkeypatch):
    p, st = event
    root = Path(p.root)
    before = _snapshot(root)
    real = os.rename
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] == 3:
            assert json.loads((root / ".hypershutter/journal.json").read_text())["moves"]   # journal already on disk
            raise OSError("disk unplugged")
        real(a, b)

    monkeypatch.setattr(execute.os, "rename", flaky)
    with pytest.raises(OSError):
        execute.apply(p, st, execute.plan(p, st), PRESET)
    monkeypatch.setattr(execute.os, "rename", real)
    assert execute.last_applied(p)["status"] == "failed"
    execute.undo(p)
    assert _snapshot(root) == before


def test_never_overwrites(event):
    p, st = event
    root = Path(p.root)
    (root / "01 STOLISMOS").mkdir()
    (root / "01 STOLISMOS/C0002.MP4").write_bytes(b"someone else's file")
    pl = execute.plan(p, st)
    assert not pl.ok and any("will not overwrite" in c for c in pl.conflicts)
    with pytest.raises(RuntimeError):
        execute.apply(p, st, pl, PRESET)
    assert (root / "cam apos/C0002.MP4").exists()


def test_reference_and_hand_organized_projects_are_refused(event, tmp_path):
    p, st = event
    ref = Project(root=str(tmp_path / "073 Β11-10-2026 Γ "), name="073 Β11-10-2026 Γ ", clips=p.clips)
    with pytest.raises(PermissionError):
        execute.check_allowed(ref)
    for c in p.clips.values():
        c.rel = "05 SOMETHING/" + c.name
    with pytest.raises(PermissionError):
        execute.check_allowed(p)


def test_rename_pattern_renames_sidecars_and_undo_restores_names(event):
    p, st = event
    root = Path(p.root)
    before = _snapshot(root)
    pl = execute.plan(p, st, rename="{num}_{n:03d}_{name}")
    dst = {m.src: m.dst for m in pl.moves}
    assert dst["cam apos/C0001.MP4"] == "01 STOLISMOS/01_001_C0001.MP4"
    assert dst["cam apos/C0001M01.XML"] == "01 STOLISMOS/01_001_C0001M01.XML"
    execute.apply(p, st, pl, PRESET)
    execute.undo(p)
    assert _snapshot(root) == before


def test_existing_generated_file_is_set_aside_and_restored(event):
    p, st = event
    root = Path(p.root)
    (root / "00 EVRETIRIO PLANON.md").write_text("my own notes")
    execute.apply(p, st, execute.plan(p, st), PRESET, extras=index.generated_files)
    assert "ευρετήριο πλάνων" in (root / "00 EVRETIRIO PLANON.md").read_text()
    execute.undo(p)
    assert (root / "00 EVRETIRIO PLANON.md").read_text() == "my own notes"


def test_index_format(event):
    p, st = event
    md = index.render_index(p, st, PRESET)
    assert md.startswith("# 075 test event — ευρετήριο πλάνων")
    assert "**Βάφτιση, 11/10/2026 (απογευματινή).** 5 βίντεο και 1 αρχεία ήχου σε 4 φακέλους." in md
    assert "Κάμερα A = `A` (κύρια, 3 κλιπ)" in md
    assert "> **Το ρολόι της κάμερας A ήταν λάθος κατά +14:00.** Η διόρθωση ορίστηκε με το χέρι." in md
    assert "**Χρονολόγιο:** ΣΤΟΛΙΣΜΟΣ 16:00–16:01 · DRONE 16:03 · **ΚΑΤΗΧΗΣΗ 16:30–16:32**" in md
    assert "## 01 STOLISMOS\n\nΣτολισμός.\n\n**2 πλάνα · 0.2 λεπτά**" in md
    assert "| `C0003.MP4` ⭐ | A |" in md


def test_backup_copies_and_verifies(event, tmp_path):
    p, _ = event
    r = execute.backup(p, tmp_path / "backup")
    assert r["copied"] == r["verified"] == r["files"] == 9
    assert (tmp_path / "backup/075 test event/cam apos/C0001M01.XML").exists()
    assert execute.backup(p, tmp_path / "backup")["copied"] == 0
    with pytest.raises(ValueError):
        execute.backup(p, Path(p.root) / "inside")


def test_reapply_after_an_edit_moves_only_the_change_and_undoes_in_order(event):
    p, st = event
    root = Path(p.root)
    before = _snapshot(root)
    execute.apply(p, st, execute.plan(p, st), PRESET, extras=index.generated_files)
    after_first = _snapshot(root)
    (root / "00 CONTACT SHEETS").mkdir(exist_ok=True)
    (root / "00 CONTACT SHEETS/02.jpg").write_bytes(b"sheet of the drone folder")    # stale after the edit
    after_first = _snapshot(root)
    st.assignment["DJI_20261011160300_0001_D"] = "p1"                              # the drone clip moves to 01
    st.categories = [c for c in st.categories if c.key != "p2"]
    pl = execute.plan(p, st)
    assert [m.clip for m in pl.moves] == ["DJI_20261011160300_0001_D"] * 2      # clip + its .SRT
    execute.apply(p, st, pl, PRESET, extras=index.generated_files)
    assert not (root / "02 DRONE").exists() and not (root / "00 CONTACT SHEETS/02.jpg").exists()
    execute.undo(p)                                                              # undoes the second run only
    assert _snapshot(root) == after_first
    execute.undo(p)                                                              # then the first
    rest = {k: v for k, v in _snapshot(root).items() if k != "00 CONTACT SHEETS/02.jpg"}   # made by the test
    assert rest == before


def test_edited_project_is_reported(event):
    p, st = event
    root = Path(p.root)
    (root / "075 ροή.xml").write_text("<xmeml><pathurl>file://localhost/x/cam%20apos/C0001.MP4</pathurl></xmeml>")
    (root / "notes.xml").write_text("<x>nothing here</x>")
    assert execute.plan(p, st).edited == ["075 ροή.xml"]
