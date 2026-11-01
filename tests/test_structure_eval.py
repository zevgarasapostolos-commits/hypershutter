from datetime import datetime, timedelta

from hypershutter.core import config, evaluate, structure
from hypershutter.core.media import Clip, Device
from hypershutter.core.project import Project

T0 = datetime(2026, 10, 11, 16, 0, 0)


def _project(spec):
    """spec: (id, device, minutes after T0, duration s)."""
    p = Project(root="/tmp/x", name="x")
    for cid, dev, minute, dur in spec:
        p.clips[cid] = Clip(id=cid, rel=f"f/{cid}.MP4", kind="video", size=1, mtime=0, device=dev,
                            probe={"duration": dur}, nominal=(T0 + timedelta(minutes=minute)).isoformat())
    for dev, kind in (("A", "camera"), ("B", "camera"), ("DJI", "drone")):
        p.devices[dev] = Device(id=dev, kind=kind, clips=[c for c, d, *_ in spec if d == dev])
    return p


SPEC = [("C1", "A", 0, 6), ("C2", "A", 1, 5), ("C3", "A", 2, 7),            # decor
        ("D1", "DJI", 3, 12),                                                # drone
        ("C4", "A", 10, 4), ("C5", "A", 11, 5),                              # portraits
        ("C6", "A", 20, 135), ("B1", "B", 21, 5), ("C7", "A", 22, 6),        # catechism master + b-roll
        ("C8", "A", 25, 20),                                                 # 20 s clip wrongly put in flow
        ("C9", "A", 40, 2)]                                                  # unusable


def _raw(p):
    order = [c.id for c in structure.ordered_clips(p, list(p.clips))]
    idx = {c: i + 1 for i, c in enumerate(order)}
    parts = [
        {"id": "p1", "label_el": "ΣΤΟΛΙΣΜΟΣ & CANDY BAR", "description_el": "Στολισμός.", "kind": "normal", "ceremony": ""},
        {"id": "p2", "label_el": "ΠΟΡΤΡΕΤΑ ΟΙΚΟΓΕΝΕΙΑΣ (ΠΡΙΝ)", "description_el": "", "kind": "normal", "ceremony": ""},
        {"id": "p3", "label_el": "ΚΑΤΗΧΗΣΗ", "description_el": "", "kind": "ceremony_flow", "ceremony": "ΚΑΤΗΧΗΣΗ"},
        {"id": "p4", "label_el": "ΚΑΤΗΧΗΣΗ", "description_el": "", "kind": "ceremony_broll", "ceremony": "ΚΑΤΗΧΗΣΗ"},
        {"id": "p5", "label_el": "ΑΧΡΗΣΤΑ", "description_el": "", "kind": "unusable", "ceremony": ""},
    ]
    a = {"C1": "p1", "C2": "p2", "C3": "p1", "C4": "p2", "C5": "p2", "C6": "p3", "B1": "p4", "C7": "p4",
         "C8": "p3", "C9": "p5"}                                              # D1 missing, C2 an outlier
    conf = {"C2": 0.3}
    return {"parts": parts, "notes": "", "_order": order,
            "assignments": [{"clip": idx[c], "part": k, "confidence": conf.get(c, 0.9)} for c, k in a.items()]}


BLACK = {"C9": {"quality_issues": ["black"], "usable": False, "people": []}}


def test_finalize_numbers_names_and_fixes():
    p = _project(SPEC)
    st = structure.finalize(p, _raw(p), BLACK, config.load_preset("baptism"))
    folders = {c: st.folder_of(c) for c in p.clips}
    assert folders["C1"] == folders["C3"] == folders["C2"] == "01 STOLISMOS & CANDY BAR"   # outlier smoothed
    assert folders["D1"] == "02 DRONE"                                                     # drone numbered at its time
    assert folders["C4"] == "03 PORTRETA OIKOGENEIAS (PRIN)"
    assert folders["C6"] == "04 KATIXISI - ROI"
    assert folders["C8"] == folders["B1"] == "04a KATIXISI - B-ROLL"                        # short clip out of ΡΟΗ
    assert folders["C9"] == "99 AXRISTA"
    assert sorted(st.assignment) == sorted(p.clips)                                         # every clip once


def test_unusable_only_without_picture():
    p = _project(SPEC)
    blurry = {"C9": {"quality_issues": ["blurry", "accidental"], "usable": False, "people": ["guests"]}}
    st = structure.finalize(p, _raw(p), blurry, config.load_preset("baptism"))
    assert st.folder_of("C9") == st.folder_of("C8") and not any(c.number == 99 for c in st.categories)
    assert "C9" in st.needs_review
    floor = {"C9": {"quality_issues": ["floor_or_ground"], "usable": False, "people": []}}
    assert structure.finalize(p, _raw(p), floor, config.load_preset("baptism")).folder_of("C9") == "99 AXRISTA"


def test_offline_segments_by_time_gaps():
    p = _project(SPEC)
    st = structure.offline_structure(p, list(p.clips), config.load_preset("baptism"), gap_minutes=5)
    names = {c: st.folder_of(c) for c in p.clips}
    assert names["D1"].endswith("DRONE") and st.source == "offline"
    assert names["C1"] == names["C3"] != names["C4"]
    assert len(st.needs_review) == len(p.clips) - 1                                         # all but the drone


def test_metrics_perfect_and_relabelled_are_equal():
    truth = {"a": "01 X", "b": "01 X", "c": "02 Y", "d": "02 Y", "e": "03 Z"}
    pred = {"a": "p", "b": "p", "c": "q", "d": "q", "e": "r"}
    m = evaluate.metrics(truth, pred, list(truth))
    assert m["matched_accuracy"] == 1.0 and m["ari"] == 1.0 and m["pairwise"]["f1"] == 1.0 and not m["errors"]


def test_metrics_one_error():
    truth = {"a": "X", "b": "X", "c": "X", "d": "Y", "e": "Y", "f": "Y"}
    pred = {"a": "p", "b": "p", "c": "q", "d": "q", "e": "q", "f": "q"}
    m = evaluate.metrics(truth, pred, list(truth))
    assert m["matched_accuracy"] == round(5 / 6, 4)
    assert m["errors"] == [{"clip": "c", "truth": "X", "pred": "q", "pred_as": "Y"}]
    assert m["pairwise"]["precision"] < 1 and m["pairwise"]["recall"] < 1 and 0 < m["ari"] < 1


def test_truth_from_index(tmp_path):
    md = tmp_path / "idx.md"
    md.write_text("# x\n\n## 01 ΣΤΟΛΙΣΜΟΣ\n\n| clip | κάμ. |\n|---|---|\n| `C4156.MP4` | A |\n\n"
                  "## 05 DRONE\n| `DJI_20261011163207_0033_D.MP4` | DJI |\n", encoding="utf-8")
    assert evaluate.truth_from_index(md) == {"C4156": "01 ΣΤΟΛΙΣΜΟΣ", "DJI_20261011163207_0033_D": "05 DRONE"}


def test_broll_without_its_flow_has_no_letter():
    p = _project(SPEC)
    raw = _raw(p)
    for a in raw["assignments"]:
        if a["part"] == "p3":
            a["part"] = "p4"                                   # nothing left in the ΡΟΗ
    st = structure.finalize(p, raw, BLACK, config.load_preset("baptism"))
    assert st.folder_of("C6") == "04 KATIXISI - B-ROLL"


def test_metrics_single_group_does_not_divide_by_zero():
    m = evaluate.metrics({"a": "X", "b": "X"}, {"a": "p", "b": "p"}, ["a", "b"])
    assert m["ari"] == 1.0 and m["matched_accuracy"] == 1.0
