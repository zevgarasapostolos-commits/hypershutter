import hashlib
import json
import os
from pathlib import Path

import pytest

from hypershutter.core import cards, ingest
from hypershutter.core.manifest import VERIFIED, Manifest


@pytest.fixture(autouse=True)
def app_support(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "appsupport"))
    from hypershutter.core import config
    monkeypatch.setattr(config, "app_support_dir", lambda: _mk(tmp_path / "appsupport"))


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def sony_card(root: Path, n: int = 3, size: int = 300_000) -> Path:
    clip = root / "PRIVATE" / "M4ROOT" / "CLIP"
    clip.mkdir(parents=True)
    (root / "PRIVATE" / "M4ROOT" / "SUB").mkdir()
    for i in range(1, n + 1):
        (clip / f"C{i:04d}.MP4").write_bytes(os.urandom(size + i))
        (clip / f"C{i:04d}M01.XML").write_text(
            f'<NonRealTimeMeta><Device manufacturer="Sony" modelName="ILCE-7SM3" serialNo="123"/></NonRealTimeMeta>')
        (root / "PRIVATE" / "M4ROOT" / "SUB" / f"C{i:04d}S03.MP4").write_bytes(b"proxy")
        os.utime(clip / f"C{i:04d}.MP4", (1_700_000_000 + i, 1_700_000_000 + i))
    return root


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime, hashlib.md5(p.read_bytes()).hexdigest())
            for p in root.rglob("*") if p.is_file()}


def test_card_is_recognized_and_camera_proxies_left_out(tmp_path):
    card = cards.read_card(sony_card(tmp_path / "card"))
    assert card.kind == "sony" and card.camera == "Sony ILCE-7SM3" and card.identity == "sony:ILCE-7SM3:123"
    assert sorted(Path(f.rel).name for f in card.files) == ["C0001.MP4", "C0001M01.XML", "C0002.MP4", "C0002M01.XML",
                                                           "C0003.MP4", "C0003M01.XML"]
    dji = tmp_path / "dji" / "DCIM" / "100MEDIA"
    dji.mkdir(parents=True)
    (dji / "DJI_20260725150620_0001_D.MP4").write_bytes(b"x" * 10)
    (dji / "DJI_20260725150620_0001_D.SRT").write_text("1")
    assert cards.read_card(tmp_path / "dji").kind == "dji_drone"
    rec = tmp_path / "rec" / "FOLDER01"
    rec.mkdir(parents=True)
    (rec / "ZOOM0001.WAV").write_bytes(b"x" * 10)
    assert cards.read_card(tmp_path / "rec").kind == "recorder"


def test_ingest_to_two_drives_verified_and_card_untouched(tmp_path):
    root = sony_card(tmp_path / "card")
    before = snapshot(root)
    card = cards.read_card(root)
    a, b = tmp_path / "driveA", tmp_path / "driveB"
    events = []
    r = ingest.ingest(card, "074 TEST", "cam apos", [a, b], proxy="none", progress=events.append)
    assert r.safe_to_format and not r.failed and r.copied == 6 and r.skipped == 0
    for d in (a, b):
        clip = d / "074 TEST" / "cam apos" / "C0002.MP4"
        assert clip.read_bytes() == (root / "PRIVATE/M4ROOT/CLIP/C0002.MP4").read_bytes()
        assert int(clip.stat().st_mtime) == 1_700_000_002                     # the card's time travels along
        assert (d / "074 TEST" / "cam apos" / "C0002M01.XML").exists()       # sidecar next to its clip
        assert not list((d / "074 TEST").rglob("*S03.MP4")) and not list((d / "074 TEST").rglob("*.hspart"))
        m = Manifest(d / "074 TEST")
        assert all(e.status == VERIFIED for e in m.entries.values()) and len(m.entries) == 6
        mhl = list((d / "074 TEST" / "cam apos").glob("cam apos_*.mhl"))[0].read_text()
        assert mhl.count("<xxhash64be>") == 6 and "<file>C0001.MP4</file>" in mhl
        rep = json.loads(list((d / "074 TEST" / ".hypershutter" / "ingest").glob("*-cam apos.json"))[0].read_text())
        assert rep["safe_to_format"] is True
    assert snapshot(root) == before                                         # the card was only read
    assert cards.labels()[card.identity] == "cam apos"                      # remembered for next time
    assert {e["phase"] for e in events} >= {"copy", "verify", "done"}


def test_verification_catches_a_corrupted_copy_and_retries(tmp_path):
    card = cards.read_card(sony_card(tmp_path / "card"))
    hits = []

    def flip_once(path: Path):                     # a write error on drive B, the first time only
        if "driveB" in str(path) and path.name == "C0003.MP4" and not hits:
            hits.append(path)
            data = bytearray(path.read_bytes())
            data[1000] ^= 0xFF
            path.write_bytes(bytes(data))

    r = ingest.ingest(card, "E", "A", [tmp_path / "driveA", tmp_path / "driveB"], proxy="none", _corrupt=flip_once)
    assert hits and r.safe_to_format
    assert (tmp_path / "driveB/E/A/C0003.MP4").read_bytes() == Path(card.path, "PRIVATE/M4ROOT/CLIP/C0003.MP4").read_bytes()
    assert list((tmp_path / "driveB/E/A").glob(".C0003.MP4.hs-old-*"))      # the bad copy is kept aside, not deleted


def test_persistent_corruption_is_flagged_and_card_not_safe(tmp_path):
    card = cards.read_card(sony_card(tmp_path / "card"))

    def always(path: Path):
        if "driveB" in str(path) and path.name == "C0001.MP4":
            data = bytearray(path.read_bytes())
            data[0] ^= 0xFF
            path.write_bytes(bytes(data))

    r = ingest.ingest(card, "E", "A", [tmp_path / "driveA", tmp_path / "driveB"], proxy="none", _corrupt=always)
    assert not r.safe_to_format
    assert r.failed == [{"dest": str(tmp_path / "driveB" / "E"), "file": "A/C0001.MP4", "why": "checksum mismatch"}]


def test_resume_skips_verified_files_and_finishes_the_rest(tmp_path):
    card = cards.read_card(sony_card(tmp_path / "card"))
    dests = [tmp_path / "driveA", tmp_path / "driveB"]
    ingest.ingest(card, "E", "A", dests, proxy="none")
    m = Manifest(dests[1] / "E")                        # as if the ingest had stopped before verifying one file
    e = m.get("A/C0002.MP4")
    m.set(e.rel, e.size, e.xxh64, "copied", e.source)
    m.save()
    r = ingest.ingest(card, "E", "A", dests, proxy="none")
    assert r.copied == 1 and r.skipped == 5 and r.safe_to_format


def test_a_second_card_with_the_same_names_never_overwrites(tmp_path):
    dests = [tmp_path / "driveA"]
    first = cards.read_card(sony_card(tmp_path / "card1"))
    ingest.ingest(first, "E", "A", dests, proxy="none")
    second = cards.read_card(sony_card(tmp_path / "card2", size=200_000))   # camera counter started again
    r = ingest.ingest(second, "E", "A", dests, proxy="none")
    assert r.safe_to_format
    assert (tmp_path / "driveA/E/A/C0001.MP4").read_bytes() == Path(first.path, "PRIVATE/M4ROOT/CLIP/C0001.MP4").read_bytes()
    assert (tmp_path / "driveA/E/A/card2/C0001.MP4").read_bytes() == Path(second.path, "PRIVATE/M4ROOT/CLIP/C0001.MP4").read_bytes()


def test_preflight_blocks_without_space_or_on_the_card(tmp_path, monkeypatch):
    card = cards.read_card(sony_card(tmp_path / "card"))
    jobs = ingest.plan(card, "A")
    assert ingest.preflight(card, jobs, [tmp_path / "card" / "x"], "E")[0].endswith("cannot be on the card")
    monkeypatch.setattr(ingest, "_free", lambda p: 10)
    problems = ingest.preflight(card, jobs, [tmp_path / "driveA"], "E")
    assert problems and "GB free" in problems[0]
    with pytest.raises(OSError):
        ingest.ingest(card, "E", "A", [tmp_path / "driveA"])


def test_a_working_drive_is_never_taken_for_a_card(tmp_path, monkeypatch):
    import shutil
    drive = tmp_path / "drive"
    (drive / "074 EVENT" / "cam apos").mkdir(parents=True)
    (drive / "song.mp3").write_bytes(b"x")              # loose audio at the root of a 2 TB drive
    monkeypatch.setattr(cards.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(2 * 10**12, 10**12, 10**12))
    assert not cards.looks_like_card(drive)
    monkeypatch.setattr(cards.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(64 * 10**9, 10**9, 63 * 10**9))
    assert cards.looks_like_card(drive)                  # a small card with WAVs at the root: a recorder
    (drive / "DCIM").mkdir()
    assert cards.looks_like_card(drive)
