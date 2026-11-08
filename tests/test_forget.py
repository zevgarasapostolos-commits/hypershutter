import copy as cp
import json
from pathlib import Path

import pytest

from hypershutter.app.bridge import Bridge
from hypershutter.core import audio_tags, config, credentials, describe, drives, execute, forget, index, review, store, transcribe
from hypershutter.core.project import Project
from test_execute import PRESET, _snapshot, event  # noqa: F401  (the fixture)
import hashlib


def _seed(p: Project, clip) -> list[Path]:
    """One cached item of every kind for a clip."""
    sha = hashlib.sha1(store.file_key(clip.name, clip.size, clip.mtime).encode()).hexdigest()
    frame = config.cache_dir("frames", sha[:20], "i2_w640") / "f.jpg"
    sheet = config.cache_dir("sheets", sha[:20], "x") / "s.jpg"
    sound = config.cache_dir("audio") / f"{sha}_4000.npy"
    tags = audio_tags._cache(clip)
    words = transcribe._cache(Path(clip.name), clip.size, clip.mtime, transcribe.PROMPTS["baptism"])
    desc = describe.cache_files(clip)[1]
    files = [frame, sheet, sound, tags, words, desc]
    for f in files:
        f.write_bytes(b"x" * 100)
    return files


def _setup(p):
    p.save()
    review.proposal_path(p).write_text("{}")
    return {c.id: _seed(p, c) for c in p.clips.values()}


def test_remove_from_the_list_only_hides_it(event):
    p, _ = event
    root = Path(p.root)
    seeded = _setup(p)
    store.hide_project(root)
    assert root.name not in [r["name"] for r in store.recent_projects()]
    assert root.name in [r["name"] for r in store.recent_projects(include_hidden=True)]      # Drives still counts it
    assert store.load_project(root) is not None and all(f.exists() for fs in seeded.values() for f in fs)
    store.show_project(root)
    assert root.name in [r["name"] for r in store.recent_projects()]
    store.hide_project(root)
    p.save()                                            # a new scan also brings it back
    assert root.name in [r["name"] for r in store.recent_projects()]


def test_forget_deletes_only_our_own_data(event):
    p, _ = event
    root = Path(p.root)
    seeded = _setup(p)
    before = _snapshot(root)
    assert forget.size(root) >= 600 * len(seeded)
    freed = forget.forget(root)
    assert freed >= 600 * len(seeded) and not any(f.exists() for fs in seeded.values() for f in fs)
    assert store.load_project(root) is None and not review.proposal_path(p).exists()
    assert _snapshot(root) == before                    # the event folder is exactly as it was


def test_a_cache_another_event_uses_stays(event, tmp_path):
    p, _ = event
    root = Path(p.root)
    seeded = _setup(p)
    other = cp.deepcopy(p)
    other.root, other.name = str(tmp_path / "test copy"), "test copy"
    shared = next(iter(p.clips))
    other.clips = {shared: p.clips[shared]}
    other.save()
    forget.forget(root)
    assert all(f.exists() for f in seeded[shared])
    assert not any(f.exists() for cid, fs in seeded.items() if cid != shared for f in fs)
    assert store.load_project(Path(other.root)) is not None


def test_undo_still_works_after_the_data_is_deleted(event):
    p, st = event
    root = Path(p.root)
    _setup(p)
    before = _snapshot(root)
    execute.apply_everywhere(p, st, PRESET, extras=index.generated_files)
    forget.forget(root)
    assert list(config.cache_dir("journals", store.project_id(root)).glob("*.json"))             # the journal stayed
    p2 = cp.deepcopy(p)                                 # the folder is opened and scanned again
    p2.save()
    execute.undo_everywhere(p2)
    after = _snapshot(root)
    assert {k: v for k, v in after.items() if ".hypershutter" not in k} == {k: v for k, v in before.items() if ".hypershutter" not in k}


def test_the_app_refuses_while_a_task_runs_and_clears_the_open_event(event, monkeypatch):
    p, st = event
    monkeypatch.setattr(credentials, "get_api_key", lambda: None)
    b = Bridge(lambda path: path, pick_folder=lambda: None, start_queue=False)
    root = Path(p.root)
    _setup(p)
    review.proposal_path(p).write_text(json.dumps({"structure": st.to_json()}))
    assert b.open_project(str(root))["known"]
    b._job = {"status": "running"}
    with pytest.raises(RuntimeError):
        b.remove_project(str(root), delete_data=True)
    assert store.load_project(root) is not None
    b._job = None
    r = b.remove_project(str(root))
    assert b._p is None and root.name not in [x["name"] for x in r["recent"]] and r["freed"] == 0
    b.open_project(str(root))                           # opened again: back on the list
    assert root.name in [x["name"] for x in b.recent()]
