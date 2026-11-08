"""Review: the user's corrections to a proposed structure, kept in Application Support.

Edits never touch footage. They change the proposal (which folder each clip goes to, folder
names, order, stars) and renumber the folders: numbers follow the order the user sets, a part
split off another shares its number with a letter (08 / 08a / 08b), and 99 stays last.
Apply (M5) reads the reviewed copy.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from hypershutter.core import config, store
from hypershutter.core.greeklish import folder_name, greek_folder_name, has_greek
from hypershutter.core.project import Project
from hypershutter.core.structure import BROLL, FLOW, NORMAL, UNUSABLE, Category, Structure, ordered_clips


def proposal_path(p: Project) -> Path:
    return config.cache_dir("structure", store.project_id(Path(p.root))) / "latest.json"


def review_path(p: Project) -> Path:
    return config.cache_dir("structure", store.project_id(Path(p.root))) / "review.json"


def load(p: Project) -> Structure | None:
    """The reviewed copy if the user edited the proposal, else the proposal itself."""
    for path in (review_path(p), proposal_path(p)):
        if path.exists():
            st = Structure.from_json(json.loads(path.read_text())["structure"])
            _link_pairs(st)
            return st
    return None


def save(p: Project, st: Structure) -> None:
    st.edited = True
    review_path(p).write_text(json.dumps({"structure": st.to_json()}, ensure_ascii=False))


def reset(p: Project) -> Structure | None:
    """Drop the user's edits (only our own file in Application Support) and return the proposal."""
    review_path(p).unlink(missing_ok=True)
    return load(p)


def _link_pairs(st: Structure) -> None:
    """Proposals saved before `parent` existed: a B-ROLL part belongs to the ΡΟΗ with its number."""
    flows = {c.number: c.key for c in st.categories if c.kind == FLOW}
    for c in st.categories:
        if c.kind == BROLL and not c.parent and c.number in flows:
            c.parent = flows[c.number]


def _letter(first: str, k: int) -> str:
    return chr(ord(first) + k - 1)


def _groups(st: Structure) -> list[list[Category]]:
    """Consecutive runs of a head folder followed by the parts split off it."""
    groups: list[list[Category]] = []
    for c in st.categories:
        if c.kind != UNUSABLE and groups and c.parent in {x.key for x in groups[-1]}:
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


def renumber(st: Structure, preset: dict) -> None:
    naming = preset["naming"]
    style = naming["greeklish_style"]
    # an event named before folders became Greek may already be organized on disk: its names stay
    latin = not any(has_greek(c.folder) for c in st.categories) and any(has_greek(c.label_el) for c in st.categories)
    st.categories = [c for c in st.categories if c.kind != UNUSABLE] + [c for c in st.categories if c.kind == UNUSABLE]
    n = 0
    for group in _groups(st):
        head = group[0]
        if head.kind == UNUSABLE:
            head.number, head.sub = naming["unusable"]["number"], ""
        else:
            n += 1
            for k, c in enumerate(group):
                c.number, c.sub = n, (_letter(naming["sub_letter"], k) if k else "")
        for c in group:
            c.folder = folder_name(c.number, c.label_el, c.sub, style) if latin else greek_folder_name(c.number, c.label_el, c.sub)


def refresh(p: Project, st: Structure, preset: dict) -> None:
    """Rebuild each folder's clip list in timeline order, drop empty folders, renumber."""
    order = [c.id for c in ordered_clips(p, [cid for cid in st.assignment if cid in p.clips])]
    for cat in st.categories:
        cat.clips = [cid for cid in order if st.assignment[cid] == cat.key]
    st.categories = [c for c in st.categories if c.clips]
    renumber(st, preset)


def _cat(st: Structure, key: str) -> Category:
    for c in st.categories:
        if c.key == key:
            return c
    raise KeyError(f"no folder {key!r}")


def _check_clips(st: Structure, clip_ids: list[str]) -> None:
    missing = [c for c in clip_ids if c not in st.assignment]
    if missing:
        raise KeyError(f"unknown clips: {', '.join(missing)}")


def _label(text: str) -> str:
    label = " ".join(text.split()).upper()
    if not label:
        raise ValueError("empty name")
    return label


def move_clips(p: Project, st: Structure, preset: dict, clip_ids: list[str], key: str) -> None:
    _cat(st, key)
    _check_clips(st, clip_ids)
    for cid in clip_ids:
        st.assignment[cid] = key
    resolve(st, clip_ids)
    refresh(p, st, preset)


def rename(p: Project, st: Structure, preset: dict, key: str, label: str) -> None:
    _cat(st, key).label_el = _label(label)
    refresh(p, st, preset)


def set_description(st: Structure, key: str, text: str) -> None:
    _cat(st, key).description_el = " ".join(text.split())


def merge(p: Project, st: Structure, preset: dict, src: str, dst: str) -> None:
    if src == dst:
        raise ValueError("cannot merge a folder into itself")
    _cat(st, src), _cat(st, dst)
    for cid, k in st.assignment.items():
        if k == src:
            st.assignment[cid] = dst
    for c in st.categories:
        if c.parent == src:              # its lettered parts now follow the folder it went into
            c.parent = dst
    refresh(p, st, preset)


def split(p: Project, st: Structure, preset: dict, key: str, clip_ids: list[str], label: str = "") -> str:
    """Move the given clips to a new folder right after `key` that shares its number (08 -> 08a)."""
    src = _cat(st, key)
    _check_clips(st, clip_ids)
    if not clip_ids:
        raise ValueError("select the clips for the new folder")
    unusable = src.kind == UNUSABLE
    new = Category(key=f"u{uuid.uuid4().hex[:8]}", number=0, sub="", label_el=_label(label or src.label_el),
                   folder="", description_el="", kind=NORMAL if unusable or src.kind == FLOW else src.kind,
                   parent="" if unusable else src.key)
    i = st.categories.index(src)
    family = {src.key}
    j = i + 1
    while j < len(st.categories) and st.categories[j].parent in family:
        family.add(st.categories[j].key)
        j += 1
    st.categories.insert(j, new)
    for cid in clip_ids:
        st.assignment[cid] = new.key
    resolve(st, clip_ids)
    refresh(p, st, preset)
    return new.key


def move_group(p: Project, st: Structure, preset: dict, key: str, delta: int) -> None:
    """Move a folder together with its lettered parts one place up (-1) or down (+1); 99 stays last."""
    groups = [g for g in _groups(st) if g[0].kind != UNUSABLE]
    rest = [c for c in st.categories if c.kind == UNUSABLE]
    i = next((k for k, g in enumerate(groups) if any(c.key == key for c in g)), None)
    if i is None:
        _cat(st, key)                    # unknown key -> KeyError; 99 itself does not move
        return
    j = max(0, min(len(groups) - 1, i + delta))
    groups.insert(j, groups.pop(i))
    st.categories = [c for g in groups for c in g] + rest
    refresh(p, st, preset)


def toggle_star(st: Structure, clip_id: str) -> bool:
    _check_clips(st, [clip_id])
    if clip_id in st.stars:
        st.stars.remove(clip_id)
        return False
    st.stars.append(clip_id)
    return True


def resolve(st: Structure, clip_ids: list[str]) -> None:
    """The user has looked at these clips: they no longer need review."""
    done = set(clip_ids)
    st.needs_review = [c for c in st.needs_review if c not in done]
