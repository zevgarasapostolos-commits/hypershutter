from pathlib import Path

from hypershutter.core.media import Clip
from hypershutter.core.scan import assign_devices, discover


def _touch(root: Path, rel: str, data: bytes = b"x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_discover_groups_sidecars_and_skips_noise(tmp_path):
    for rel in ["cam apos/C4255.MP4", "cam apos/._C4255.MP4", "cam dim/C6501.MP4", "cam dim/C6501M01.XML",
                "drone/DJI_20261011163207_0033_D.MP4", "drone/DJI_20261011163207_0033_D.SRT",
                "drone/DJI_20261011163207_0033_D.LRF", "sound/DJI_02_20261004_120804.WAV",
                "music/song.mp3", "073 ροή - preview (για έλεγχο).mp4", "073 ροή.xml", "x.prproj",
                "Adobe Premiere Pro Auto-Save/a.prproj", "cam dim/C9999M01.XML", "cam apos/notes.txt"]:
        _touch(tmp_path, rel)
    clips, ignored, orphans = discover(tmp_path)
    by_id = {c.id: c for c in clips}
    assert set(by_id) == {"C4255", "C6501", "DJI_20261011163207_0033_D", "DJI_02_20261004_120804"}
    assert by_id["C6501"].sidecars == ["cam dim/C6501M01.XML"]
    assert sorted(by_id["DJI_20261011163207_0033_D"].sidecars) == [
        "drone/DJI_20261011163207_0033_D.LRF", "drone/DJI_20261011163207_0033_D.SRT"]
    assert by_id["DJI_02_20261004_120804"].kind == "audio"
    assert orphans == ["cam dim/C9999M01.XML"]
    assert "073 ροή - preview (για έλεγχο).mp4" in ignored       # root deliverables are not sources
    assert "music/" in ignored and "Adobe Premiere Pro Auto-Save/" in ignored


def test_duplicate_stems_get_unique_ids(tmp_path):
    _touch(tmp_path, "drone/DJI_0001.MP4")
    _touch(tmp_path, "DRONE2/DJI_0001.MP4")
    ids = sorted(c.id for c in discover(tmp_path)[0])
    assert ids == ["DJI_0001", "DJI_0001~2"]


def _clip(cid, kind="video", source="creation_time"):
    return Clip(id=cid, rel=f"x/{cid}.MP4", kind=kind, size=1, mtime=0, source=source)


def test_devices_split_by_numbering_and_merge_continuations():
    clips = [_clip(f"C{n}") for n in range(4156, 4170)] + [_clip(f"C{n}") for n in range(6507, 6510)]
    clips += [_clip(f"C{n}") for n in (4170, 4171)]                    # another card, same camera
    clips += [_clip("DJI_20261011163207_0033_D", source="dji_name"), _clip("DJI_02_20261004_120804", "audio", "rec_name")]
    devs = assign_devices(clips, {})
    assert len(devs["A"].clips) == 16 and devs["A"].pattern == "C41xx"
    assert devs["B"].clips == ["C6507", "C6508", "C6509"] and devs["B"].pattern == "C65xx"
    assert devs["DJI"].kind == "drone" and devs["REC"].kind == "recorder"


def test_sony_serial_groups_camera_and_absorbs_continuation():
    clips = [_clip("C6501", source="sony_xml"), _clip("C6502", source="sony_xml"), _clip("C6503")]
    clips += [_clip(f"C{n}") for n in range(3925, 3935)]
    meta = {"C6501": {"serial": "S1", "model": "Sony ILCE-7M4"}, "C6502": {"serial": "S1", "model": "Sony ILCE-7M4"}}
    devs = assign_devices(clips, meta)
    assert devs["A"].pattern == "C39xx"
    assert devs["B"].clips == ["C6501", "C6502", "C6503"] and devs["B"].model == "Sony ILCE-7M4"
