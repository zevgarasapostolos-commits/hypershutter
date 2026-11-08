import json

from test_structure_eval import BLACK, SPEC, _project, _raw

from hypershutter.core import config, review, structure

PRESET = config.load_preset("baptism")


def _setup():
    p = _project(SPEC)
    return p, structure.finalize(p, _raw(p), BLACK, PRESET)


def _folders(st):
    return [c.folder for c in st.categories]


def test_move_clip_resolves_and_empties_drop_out():
    p, st = _setup()
    st.needs_review = ["C5"]
    review.move_clips(p, st, PRESET, ["C5"], st.assignment["C1"])
    assert st.folder_of("C5") == "01 ΣΤΟΛΙΣΜΟΣ & CANDY BAR" and not st.needs_review
    review.move_clips(p, st, PRESET, ["C4"], st.assignment["C1"])
    assert _folders(st) == ["01 ΣΤΟΛΙΣΜΟΣ & CANDY BAR", "02 DRONE", "03 ΚΑΤΗΧΗΣΗ - ΡΟΗ", "03a ΚΑΤΗΧΗΣΗ - B-ROLL",
                            "99 ΑΧΡΗΣΤΑ"]


def test_split_gets_a_letter_and_merge_undoes_it():
    p, st = _setup()
    broll = st.assignment["C7"]
    new = review.split(p, st, PRESET, broll, ["C7"], "αντιδρασεις")
    assert st.folder_of("C7") == "04b ΑΝΤΙΔΡΑΣΕΙΣ"
    review.merge(p, st, PRESET, new, broll)
    assert st.folder_of("C7") == "04a ΚΑΤΗΧΗΣΗ - B-ROLL" and new not in {c.key for c in st.categories}


def test_rename_and_move_group_renumber():
    p, st = _setup()
    review.rename(p, st, PRESET, st.assignment["C4"], "πορτρετα γονεων")
    assert st.folder_of("C4") == "03 ΠΟΡΤΡΕΤΑ ΓΟΝΕΩΝ"
    review.move_group(p, st, PRESET, st.assignment["C6"], -1)          # the ΡΟΗ moves with its B-ROLL
    assert _folders(st)[2:5] == ["03 ΚΑΤΗΧΗΣΗ - ΡΟΗ", "03a ΚΑΤΗΧΗΣΗ - B-ROLL", "04 ΠΟΡΤΡΕΤΑ ΓΟΝΕΩΝ"]
    review.move_group(p, st, PRESET, st.assignment["C9"], -1)          # 99 stays last
    assert _folders(st)[-1] == "99 ΑΧΡΗΣΤΑ"


def test_save_load_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path))
    p, st = _setup()
    proposal = st.to_json()
    for c in proposal["categories"]:
        c.pop("parent")                                                 # a proposal saved before `parent`
    review.proposal_path(p).write_text(json.dumps({"structure": proposal}))
    loaded = review.load(p)
    assert not loaded.edited and next(c for c in loaded.categories if c.sub == "a").parent
    review.toggle_star(loaded, "C6")
    review.save(p, loaded)
    again = review.load(p)
    assert again.edited and again.stars == ["C6"]
    assert review.reset(p).stars == []


def test_an_event_named_in_greeklish_keeps_its_folders_when_edited():
    from types import SimpleNamespace as NS
    from hypershutter.core import review as rv
    preset = {"naming": {"greeklish_style": {"upsilon": "Y", "au_eu": "phonetic", "xi": "KS", "mp_nt": "literal"},
                         "sub_letter": "a", "unusable": {"number": 99}}}
    old = NS(categories=[NS(key="a", number=1, sub="", label_el="ΓΑΜΟΣ", folder="01 GAMOS", kind="flow", parent="")])
    rv.renumber(old, preset)
    assert old.categories[0].folder == "01 GAMOS"
    new = NS(categories=[NS(key="a", number=1, sub="", label_el="ΓΑΜΟΣ", folder="01 ΓΑΜΟΣ", kind="flow", parent="")])
    rv.renumber(new, preset)
    assert new.categories[0].folder == "01 ΓΑΜΟΣ"
