from datetime import datetime, timedelta

from hypershutter.core import structure, transcribe
from hypershutter.core.media import Clip
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, DRONE, FLOW, NORMAL


def test_ritual_ranges_keep_liturgy_and_cut_talk():
    S = transcribe.Segment
    segs = [S(0, 4, "καλησπέρα, ελάτε λίγο πιο κοντά", []),             # talk before the start
            S(5, 12, "Ευλογητός ο Θεός ημών πάντοτε", []),
            S(12.5, 14, "κράτα το έτσι", []),                            # a short instruction inside: glue
            S(14.2, 22, "Του Κυρίου δεηθώμεν, Κύριε ελέησον", []),
            S(30, 45, "πάμε για φωτογραφίες μετά, να μαζευτούν όλοι εδώ μπροστά", []),
            S(50, 58, "Δόξη και τιμή στεφάνωσον αυτούς", [])]
    assert transcribe.ritual_ranges(segs) == [(5, 22), (50, 58)]
    assert [s.start for s in transcribe.find(segs, transcribe.MOMENTS["crowning"])] == [50]


def test_structure_from_the_users_folders(tmp_path):
    p = Project(root=str(tmp_path), name="x")
    t0 = datetime(2026, 7, 25, 15, 0)
    for k, (cid, folder) in enumerate([("C1", "06 ΓΑΜΟΣ — ΡΟΗ"), ("C2", "06a ΓΑΜΟΣ — B-ROLL"), ("C3", "10 ΒΑΦΤΙΣΗ — ΡΟΗ"),
                                       ("C4", "11 ΒΑΦΤΙΣΗ — B-ROLL"), ("D1", "17 DRONE"), ("C5", "cam apos")]):
        p.clips[cid] = Clip(id=cid, rel=f"{folder}/{cid}.MP4", kind="video", size=1, mtime=0, device="A",
                            probe={"duration": 5}, nominal=(t0 + timedelta(minutes=k)).isoformat())
    st = structure.from_folders(p)
    kinds = {c.folder: (c.kind, c.parent) for c in st.categories}
    assert kinds["06a ΓΑΜΟΣ — B-ROLL"] == (BROLL, "06 ΓΑΜΟΣ — ΡΟΗ")
    assert kinds["11 ΒΑΦΤΙΣΗ — B-ROLL"] == (BROLL, "10 ΒΑΦΤΙΣΗ — ΡΟΗ")       # paired by name, not number
    assert kinds["17 DRONE"][0] == DRONE and kinds["10 ΒΑΦΤΙΣΗ — ΡΟΗ"][0] == FLOW
    assert "C5" not in st.assignment                                            # not in a numbered folder
    assert NORMAL not in {k for k, _ in kinds.values()}
