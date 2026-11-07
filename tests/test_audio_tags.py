from datetime import datetime, timedelta

import numpy as np

from hypershutter.core import audio_tags as at
from hypershutter.core import config, structure, transcribe
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project


def tags(*windows):
    """Windows as (groups dict, dB, place)."""
    return {"windows": [{"t": 5.0 * i, "db": db, "groups": g, "place": pl} for i, (g, db, pl) in enumerate(windows)]}


def test_groups_do_not_overlap_and_cover_known_classes():
    seen = {}
    for g, idx in at.GROUPS.items():
        for i in idx:
            assert i not in seen, (i, g, seen.get(i))
            seen[i] = g
    assert seen[28] == "chanting" and seen[201] == "bells" and seen[67] == "applause" and seen[23] == "crying"
    assert all(0 <= i < 527 for i in seen)


def test_window_reduces_classes_to_groups_and_place():
    probs = np.zeros(527, dtype=np.float32)
    probs[30], probs[0], probs[507] = 0.8, 0.3, 0.6          # chant, speech, large hall
    w = at.window_of(10.0, np.full(16000, 0.1, dtype=np.float32), probs)
    assert w.groups == {"chanting": 0.8, "speech": 0.3} and w.place == "large hall"
    assert -21 < w.db < -19                                    # 0.1 rms = -20 dBFS


def test_short_line_and_timeline():
    t = tags(({"chanting": 0.9, "speech": 0.5}, -25, "large hall"), ({"chanting": 0.8}, -26, "large hall"),
             ({"applause": 0.7, "crowd": 0.4}, -18, "large hall"), ({"speech": 0.3}, -30, ""))
    assert at.shares(t)["chanting"] == 0.5
    line = at.short_line(t, ["liturgy", "crowning"])
    assert line.startswith("chanting 50%") and "large hall" in line and line.endswith("heard: liturgy, crowning")
    text = at.timeline_text(t, ["crowning"])
    assert "0:00–0:05 chanting + speech; 0:05–0:10 chanting; 0:10–0:15 applause + crowd" in text and "crowning" in text
    assert at.short_line({"no_audio": True}, []) == "no sound" and at.short_line({"missing": True}, []) == ""


def test_cue_words_from_whisper_text():
    S = transcribe.Segment
    segs = [S(0, 4, "Του Κυρίου δεηθώμεν", []), S(4, 9, "Στέφεται ο δούλος του Θεού", []),
            S(9, 12, "Κύριε ελέησον", [])]
    assert at.cues(segs) == ["liturgy", "crowning"]
    assert at.cues([S(0, 3, "Να ζήσετε, να είστε ευτυχισμένοι!", []), S(3, 5, "Γεια μας!", [])]) == ["wishes", "toast"]
    assert at.cues([]) == []


def _project(tmp_path, specs):
    """specs: (id, minutes after 12:00, duration s, device, sound tags or None)."""
    p = Project(root=str(tmp_path), name="x")
    p.devices = {"A": Device(id="A", kind="camera", pattern="C", clips=[]),
                 "B": Device(id="B", kind="camera", pattern="C6", clips=[])}
    t0 = datetime(2026, 7, 25, 12, 0)
    sound = {}
    for cid, m, dur, dev, t in specs:
        p.clips[cid] = Clip(id=cid, rel=f"{cid}.MP4", kind="video", size=1, mtime=0, device=dev,
                            probe={"duration": dur}, nominal=(t0 + timedelta(minutes=m)).isoformat())
        if t is not None:
            sound[cid] = {"tags": t, "heard": []}
    return p, sound


def test_offline_splits_a_service_out_of_one_time_segment(tmp_path):
    talk = tags(({"speech": 0.9}, -25, ""))
    chant = tags(({"chanting": 0.9}, -25, "large hall"))
    party = tags(({"music": 0.95, "crowd": 0.6}, -15, ""))
    specs = [(f"a{i}", i, 20, "B", talk) for i in range(4)]
    specs += [("m1", 4, 600, "A", chant)] + [(f"b{i}", 5 + i, 10, "B", chant) for i in range(4)]
    specs += [(f"c{i}", 9 + i, 20, "B", party) for i in range(4)]
    p, sound = _project(tmp_path, specs)
    preset = config.load_preset("wedding")
    st = structure.offline_structure(p, list(p.clips), preset, sound=sound)
    kinds = {c.kind for c in st.categories}
    assert structure.FLOW in kinds and structure.BROLL in kinds
    assert st.folder_of("m1") != st.folder_of("b0") and st.folder_of("b0") == st.folder_of("b3")
    assert len({st.folder_of(c) for c in ("a0", "a3")}) == 1 and st.folder_of("a0") != st.folder_of("c0")
    plain = structure.offline_structure(p, list(p.clips), preset)            # no sound: one part (no time gap)
    assert len({plain.folder_of(c) for c in p.clips}) == 1


def test_pass2_lines_show_only_the_chosen_signals(tmp_path):
    p, _ = _project(tmp_path, [("c1", 0, 12, "A", None)])
    d = {"moments": ["crowns"], "location": "church_interior", "people": ["bride"], "shot_type": "wide",
         "take": "cutaway", "posed": False, "description": "The crowns are exchanged."}
    c = p.clips["c1"]
    assert structure._line(1, p, c, d, frozenset({"time"})) == "#1 | 12:00:00–12:00:12 | 0:12"
    full = structure._line(1, p, c, d, structure.ALL_SIGNALS, "chanting 80%")
    assert "| main |" in full and "crowns are exchanged" in full and full.endswith("sound: chanting 80%")
    assert "sound:" not in structure._line(1, p, c, d, frozenset({"time", "camera", "image"}))
    assert "(no pictures)" in structure.system_prompt(frozenset({"time", "camera", "audio"}))
    assert "Sound:" not in structure.system_prompt(frozenset({"time", "camera", "image"}))
