import subprocess
from pathlib import Path

import pytest

from hypershutter.core import config, drives, jobs, proxies


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "appsupport"))


def clip(path: Path, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([config.find_tool("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=640x360:rate=25:duration={seconds}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True)
    return path


def test_proxy_lands_where_premiere_looks_and_queue_survives_a_restart(tmp_path):
    ev = tmp_path / "074 EVENT"
    clip(ev / "cam apos" / "C0001.MP4")
    clip(ev / "cam apos" / "C0002.MP4")
    (ev / "cam apos" / "C0003.MP4").write_bytes(b"not a video")
    db = tmp_path / "jobs.db"
    q = proxies.queue(db_path=db)
    rels = ["cam apos/C0001.MP4", "cam apos/C0002.MP4", "cam apos/C0003.MP4", "cam apos/C0001M01.XML"]
    assert proxies.enqueue(q, ev, rels, "h264") == 3                     # the XML is not a clip
    assert proxies.enqueue(q, ev, rels, "h264") == 0                     # no double jobs
    first = q._next()                                                    # the app stops while this one runs …
    assert first.status == jobs.QUEUED
    q2 = proxies.queue(db_path=db)                                       # … and starts again
    assert q2.counts("proxy") == {"queued": 3}
    q2.drain()
    c = q2.counts("proxy")
    assert c == {"done": 2, "failed": 1}                                 # a broken clip never stops the queue
    out = ev / "Proxies" / "cam apos" / "C0001.mov"
    assert proxies.proxy_for(ev, "cam apos/C0001.MP4") == out and out.stat().st_size > 0
    assert not list((ev / "Proxies").rglob(".*hspart*"))
    probe = subprocess.run([config.find_tool("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    assert probe == ["video", "audio"]                                   # sound kept (Attach Proxies needs it)
    assert proxies.enqueue(q2, ev, rels, "h264") == 1                    # only the failed one is queued again


def test_scan_ignores_proxies_and_exports(tmp_path):
    from hypershutter.core import scan
    ev = tmp_path / "E"
    clip(ev / "cam" / "C0001.MP4", 1)
    clip(ev / "Proxies" / "cam" / "C0001.mov", 1)
    clip(ev / "Exports" / "h264" / "C0001.mp4", 1)
    clips, ignored, _ = scan.discover(ev)
    assert [c.rel for c in clips] == ["cam/C0001.MP4"]


def test_drive_status_thresholds():
    t = {"warn_percent": 10, "warn_gb": 50, "critical_gb": 10}
    assert drives.classify(2000e9, 500e9, t)[0] == "ok"
    assert drives.classify(2000e9, 150e9, t)[0] == "warn"               # 7.5 % of a big drive
    assert drives.classify(1000e9, 40e9, t)[0] == "warn"
    assert drives.classify(1000e9, 5e9, t) == ("critical", "only 5.0 GB free")
