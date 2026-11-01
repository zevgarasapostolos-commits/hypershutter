import wave
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from hypershutter.core import config, edit, music, preview, xmeml
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, DRONE, FLOW, NORMAL, Category, Structure
from hypershutter.core.xmeml import Item, Media, Sequence

T0 = datetime(2026, 10, 11, 16, 0, 0)
TPL = config.load_preset("baptism")["highlights"]


def _click_track(path: Path, bpm: float, seconds: float, sr: int = 22050) -> None:
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    for t in np.arange(0.25, seconds, 60 / bpm):
        i = int(t * sr)
        y[i:i + 300] += np.hanning(300).astype(np.float32) * np.sin(np.arange(300) * 0.6).astype(np.float32)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 30000).astype(np.int16).tobytes())


# (id, folder key, minute, duration, device, description)
PLAN = []
for k in range(6):
    PLAN.append((f"DJI_{k}", "dr", 5 + k * 40, 30, "DJI", {"moments": ["aerial"], "shot_type": "aerial"}))
for k in range(8):
    PLAN.append((f"C1{k:02d}", "ext", 1 + k, 12, "A", {"moments": ["church_exterior"], "shot_type": "wide"}))
for k in range(30):
    PLAN.append((f"C2{k:02d}", "det", 10 + k * 0.5, 9, "A", {"moments": ["details"], "shot_type": "detail", "star": k % 5 == 0}))
for k in range(20):
    PLAN.append((f"C3{k:02d}", "fam", 30 + k, 10, "A", {"people": ["mother", "baby"], "shot_type": "medium"}))
for k in range(20):
    PLAN.append((f"C4{k:02d}", "gst", 52 + k * 0.5, 6, "A", {"people": ["guests"], "shot_type": "medium"}))
PLAN.append(("M1", "katR", 75, 500, "A", {"take": "continuous_take", "notable": [{"t": 60, "what": "priest reads"},
                                                                                  {"t": 400, "what": "godparent says the name"}]}))
for k in range(10):
    PLAN.append((f"C5{k:02d}", "katB", 76 + k * 0.7, 8, "B", {"people": ["guests"], "shot_type": "close_up"}))
PLAN.append(("M2", "mysR", 95, 600, "A", {"take": "continuous_take", "moments": ["immersion"],
                                          "notable": [{"t": 50, "what": "oil"}, {"t": 300, "what": "immersion in the font"},
                                                      {"t": 500, "what": "dressing"}]}))
PLAN.append(("M3", "mysR", 106, 300, "A", {"take": "continuous_take", "notable": [{"t": 100, "what": "Gospel"}]}))
for k in range(25):
    PLAN.append((f"C6{k:02d}", "mysB", 105.2 + k * 0.04 if k < 1 else 95.5 + k * 0.4, 8, "A",
                 {"people": ["baby", "mother"] if k % 3 == 0 else ["guests"], "shot_type": "close_up",
                  "moments": ["immersion"] if k == 12 else []}))
for k in range(30):
    PLAN.append((f"C7{k:02d}", "rec", 130 + k * 2, 10, "A", {"people": ["guests"], "shot_type": "medium"}))
for k in range(3):
    PLAN.append((f"C8{k:02d}", "dance", 220 + k * 15, 300, "A", {"moments": ["dancing"]}))

CATS = [("ext", 1, "ΕΞΩΤΕΡΙΚΑ ΕΚΚΛΗΣΙΑΣ", NORMAL, ""), ("det", 2, "ΛΕΠΤΟΜΕΡΕΙΕΣ", NORMAL, ""),
        ("dr", 3, "DRONE", DRONE, ""), ("fam", 4, "ΠΟΡΤΡΕΤΑ ΟΙΚΟΓΕΝΕΙΑΣ (ΠΡΙΝ)", NORMAL, ""),
        ("gst", 5, "ΑΦΙΞΗ ΚΑΛΕΣΜΕΝΩΝ", NORMAL, ""), ("katR", 6, "ΚΑΤΗΧΗΣΗ — ΡΟΗ", FLOW, ""),
        ("katB", 6, "ΚΑΤΗΧΗΣΗ — B-ROLL", BROLL, "a"), ("mysR", 7, "ΜΥΣΤΗΡΙΟ — ΡΟΗ", FLOW, ""),
        ("mysB", 7, "ΜΥΣΤΗΡΙΟ — B-ROLL", BROLL, "a"), ("rec", 8, "ΔΕΞΙΩΣΗ — ΧΩΡΟΣ & ΤΡΑΠΕΖΙΑ", NORMAL, ""),
        ("dance", 9, "ΧΟΡΟΣ", NORMAL, "")]


@pytest.fixture
def event(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "support"))
    root = tmp_path / "080 test"
    p = Project(root=str(root), name="080 test")
    descs = {}
    for cid, key, minute, dur, dev, d in PLAN:
        rel = f"{key}/{cid}.MP4"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
        p.clips[cid] = Clip(id=cid, rel=rel, kind="video", size=1, mtime=0, device=dev,
                            probe={"duration": dur, "fps": 50.0, "width": 3840, "height": 2160, "acodec": "pcm", "channels": 2},
                            nominal=(T0 + timedelta(minutes=minute)).isoformat())
        descs[cid] = {"usable": True, "quality_issues": [], **d}
    for dev, kind in (("A", "camera"), ("B", "camera"), ("DJI", "drone")):
        p.devices[dev] = Device(id=dev, kind=kind, clips=[c for c, *_ in PLAN if p.clips[c].device == dev])
    cats = []
    for key, n, label, kind, sub in CATS:
        cats.append(Category(key, n, sub, label, f"{n:02d}{sub} X", "", kind, [c for c, k, *_ in PLAN if k == key],
                             parent="katR" if key == "katB" else "mysR" if key == "mysB" else ""))
    st = Structure(cats, {c: k for c, k, *_ in PLAN}, {}, [])
    song = tmp_path / "song.wav"
    _click_track(song, 129.2, 194.63)
    return p, st, descs, song


def test_pathurl_and_xml_shape(tmp_path):
    f = tmp_path / "a (1) b.MP4"
    f.write_bytes(b"x")
    m4k = Media(str(f), 10.0, fps=50)
    m1080 = Media(str(f), 10.0, fps=25, width=1920, height=1080)
    seq = Sequence("t", video=[[Item(m4k, 0, 50, 1.0, speed=0.5), Item(m1080, 50, 100, 2.0)]], audio=[[Item(m4k, 0, 50, 1.0, fade_out=10)]])
    assert not seq.check()
    root = ET.fromstring(xmeml.to_xml(seq).split("\n", 2)[2])
    items = root.findall(".//video/track/clipitem")
    assert (items[0].findtext("in"), items[0].findtext("out")) == ("50", "100")         # source frames at 50 fps
    assert (items[1].findtext("in"), items[1].findtext("out")) == ("50", "100")         # sequence frames
    assert items[1].find(".//parameter/value").text == "200.0"                           # 1080p fills 4K
    assert "%20%281%29%20" in root.findtext(".//pathurl")
    assert root.find(".//audio/track/transitionitem/alignment").text == "end-black"
    assert Sequence("t", video=[[Item(m4k, 0, 400, 2.0)]]).check()                      # past the clip's end


def test_music_grid(tmp_path):
    song = tmp_path / "s.wav"
    _click_track(song, 120.0, 150.0)
    a = music.analyse(song)
    assert abs(a["beat"] - 0.5) < 0.02
    g = music.fit(TPL, a)
    assert g.slots[0] == 0 and all(b > x for x, b in zip(g.slots, g.slots[1:])) and g.end <= 150
    off = [((t - a["phase"]) / (a["beat"] / 2)) % 1 for t in g.slots[1:]]
    assert max(min(o, 1 - o) for o in off) < 0.15                                     # cuts on half-beats


def test_highlights_follow_the_rules(event):
    p, st, descs, song = event
    hl = edit.build_highlights(p, st, descs, song, TPL)
    assert len(hl.cuts) == len(hl.grid.slots) and not hl.warnings
    kinds = [c.shot.cat.key for c in hl.cuts]
    assert kinds[0] == kinds[3] == kinds[-1] == "dr"                                     # drone open, title, close
    assert hl.film["film2"].shot.id == "M2" and abs(hl.film["film2"].src_in - 300) < 8   # FILM 2 = the immersion
    for a, b in zip(hl.cuts, hl.cuts[1:]):
        assert not (a.shot.id == b.shot.id and a.shot.cat.kind == FLOW)                  # no master back to back
    assert all(c.speed == 1.0 for c in hl.cuts if c.shot.cat.kind in (DRONE, FLOW))      # no slow-mo on masters
    seq = edit.highlights_sequence("080 highlights", hl)
    assert not seq.check() and len(seq.audio[2]) == 2                                    # FILM audio on A3


def test_flow(event):
    p, st, descs, song = event
    hl = edit.build_highlights(p, st, descs, song, TPL)
    fl = edit.build_flow("080 ροή", p, st, descs, hl)
    seq = fl.seq
    assert not seq.check()
    names = [m.name for m in seq.markers]
    assert any(n.startswith("ΚΑΤΗΧΗΣΗ") for n in names) and any(n.startswith("ΜΥΣΤΗΡΙΟ") for n in names)
    assert "ΒΟΥΤΙΑ" in names and any(n.startswith("ΧΟΡΟΙ") for n in names)
    dive = next(m.at for m in seq.markers if m.name == "ΒΟΥΤΙΑ")
    assert seq.video[1] and all(abs(it.start - dive) >= 10 * 25 for it in seq.video[1])   # no cutaway on the dive
    ids = [it.media.path for it in seq.video[1]]
    assert len(ids) == len(set(ids))                                                      # no b-roll reuse on V2


def test_preview_picture_puts_v2_over_v1(tmp_path):
    f = tmp_path / "a.MP4"
    f.write_bytes(b"x")
    m = Media(str(f), 100.0)
    v1 = Item(m, 0, 100, 0.0)
    v2 = Item(m, 40, 60, 50.0)
    seq = Sequence("t", video=[[v1], [v2]])
    assert [(it is v2, a, b) for it, a, b in preview.picture(seq)] == [(False, 0, 40), (True, 40, 60), (False, 60, 100)]


def test_preview_audio_track_is_laid_out_exactly(tmp_path):
    import subprocess

    from hypershutter.core import config
    tone = tmp_path / "tone.wav"
    subprocess.run([config.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=20",
                    "-ac", "2", str(tone)], check=True)
    m = Media(str(tone), 20.0, has_video=False, audio_channels=2)
    seq = Sequence("t", video=[[]], audio=[[Item(m, 25 * 600, 25 * 610, 1.0), Item(m, 25 * 1200, 25 * 1205, 0.0, fade_out=25)]])
    out = preview._mix(config.find_tool("ffmpeg"), seq, 1210.0, tmp_path / "mix.wav", tmp_path)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True).stdout
    assert abs(float(d) - 1210.0) < 0.05                       # long silent gaps are kept (amix+adelay lost them)
