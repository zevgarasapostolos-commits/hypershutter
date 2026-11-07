import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hypershutter.core import config, export, jobs
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project
from hypershutter.core.structure import NORMAL, Category, Structure
from test_proxies_drives import clip


@pytest.fixture
def event(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "support"))
    root = tmp_path / "076 EVENT"
    p = Project(root=str(root), name=root.name)
    p.devices["A"] = Device(id="A", kind="camera", pattern="C")
    for k, (cid, folder) in enumerate([("C0001", "01 ETOIMASIA NYFIS"), ("C0002", "01 ETOIMASIA NYFIS"), ("C0003", "02 XOROS")]):
        f = clip(root / folder / f"{cid}.MP4", 1 + k)
        p.clips[cid] = Clip(id=cid, rel=f"{folder}/{cid}.MP4", kind="video", size=f.stat().st_size, mtime=f.stat().st_mtime,
                            device="A", probe={"duration": 1 + k}, nominal=(datetime(2026, 7, 25, 12) + timedelta(minutes=k)).isoformat())
    cats = [Category("a", 1, "", "ΕΤΟΙΜΑΣΙΑ ΝΥΦΗΣ", "01 ETOIMASIA NYFIS", "", NORMAL, ["C0001", "C0002"]),
            Category("b", 2, "", "ΧΟΡΟΣ", "02 XOROS", "", NORMAL, ["C0003"])]
    st = Structure(cats, {"C0001": "a", "C0002": "a", "C0003": "b"}, {}, [])
    return p, st


def test_export_mirrors_the_folders_and_never_overwrites(event, tmp_path):
    p, st = event
    dest = tmp_path / "out"
    items = export.plan(p, st, "h264_1080_review", dest)
    assert [str(i.out.relative_to(dest)) for i in items] == [
        "h264_1080_review/01 ETOIMASIA NYFIS/C0001.mp4", "h264_1080_review/01 ETOIMASIA NYFIS/C0002.mp4",
        "h264_1080_review/02 XOROS/C0003.mp4"]
    assert [i.clip for i in export.plan(p, st, "h264_1080_review", dest, folders=["02"])] == ["C0003"]
    assert export.check(items, "h264_1080_review") == []
    existing = dest / "h264_1080_review" / "02 XOROS" / "C0003.mp4"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"someone else's file")
    items = export.plan(p, st, "h264_1080_review", dest)
    assert items[-1].out.name == "C0003 (2).mp4"
    q = export.queue(db_path=tmp_path / "jobs.db")
    assert export.enqueue(q, p, items, "h264_1080_review") == 3
    q.drain()
    assert q.counts("export") == {"done": 3}
    assert existing.read_bytes() == b"someone else's file"
    ffprobe = config.find_tool("ffprobe") or "ffprobe"
    d = float(subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              str(items[-1].out)], capture_output=True, text=True).stdout)
    assert abs(d - 3.0) < 0.15                                  # same length: a transcode, never a cut
    for f in (Path(p.root) / "01 ETOIMASIA NYFIS").iterdir():
        assert f.suffix == ".MP4"                               # nothing written next to the camera files


def test_export_space_check_and_pause(event, tmp_path, monkeypatch):
    p, st = event
    items = export.plan(p, st, "prores_422_lt", tmp_path / "out")
    monkeypatch.setattr(export.drives, "check_space", lambda d, need: f"{d}: needs {need / 1e9:.1f} GB")
    assert export.check(items, "prores_422_lt")[0].startswith(str(tmp_path / "out"))
    q = export.queue(db_path=tmp_path / "jobs.db")
    export.enqueue(q, p, items, "prores_422_lt")
    q.pause()
    q.start()
    assert not q.wait("export", timeout=1.0)                     # paused: nothing runs
    assert q.counts("export") == {"queued": 3}
    q.resume()
    assert q.wait("export", timeout=60)
    q.stop()
    assert q.counts("export") == {"done": 3}
    assert jobs.read_all(tmp_path / "jobs.db")[0].meta == '{"seconds": 1.0}'
