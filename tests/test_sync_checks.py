import numpy as np

from hypershutter.core import checks, sync
from hypershutter.core.media import Clip, Device, fmt_offset
from hypershutter.core.sync import SR, Match, ncc, parse_offset, vote


def test_ncc_finds_needle_in_noisy_haystack():
    rng = np.random.default_rng(1)
    hay = rng.standard_normal(SR * 120).astype(np.float32)
    needle = hay[SR * 47: SR * 52] + 0.5 * rng.standard_normal(SR * 5).astype(np.float32)
    lag, psr = ncc(needle, hay)
    assert abs(lag - SR * 47) <= 1 and psr > 20


def test_ncc_unrelated_audio_is_weak():
    rng = np.random.default_rng(2)
    _, psr = ncc(rng.standard_normal(SR * 5), rng.standard_normal(SR * 120))
    assert psr < sync.PSR_MIN


def test_needles_segment_long_recordings_and_keep_small_devices_whole():
    rec = Clip(id="DJI_02_20261004_120804", rel="sound/x.WAV", kind="audio", size=1, mtime=0,
               probe={"duration": 3600.0, "acodec": "pcm_s24le"}, nominal="2026-10-04T12:08:04")
    segs = sync._needles([rec])
    assert len(segs) == 3600 // sync.SEGMENT_EVERY            # one segment every 5 min of the hour
    assert all(seg == sync.NEEDLE_MAX for _, _, seg in segs)
    shorts = [Clip(id=f"C65{i:02d}", rel="b", kind="video", size=1, mtime=0, probe={"duration": 5.0 + i},
                   nominal=f"2026-10-11T17:0{i}:00") for i in range(7)]
    assert len(sync._needles(shorts)) == 7                    # same half hour, still all used


def test_vote_needs_agreement():
    a = Match("B1", "A1", 3.0, 20.0, 39556.0)
    b = Match("B2", "A2", 9.0, 11.0, 39556.8)
    stray = Match("B3", "A9", 1.0, 8.0, 120.0)
    rel, conf, ms = vote([a, b, stray])
    assert abs(rel - 39556.4) < 0.5 and [m.needle for m in ms] == ["B1", "B2"] and conf > 0.5
    assert vote([Match("B1", "A1", 0, 9.0, 5.0)]) is None          # one weak vote is not enough


def test_offsets_parse_and_format():
    assert parse_offset("+14:00") == 50400 and parse_offset("-0:44") == -2640
    assert parse_offset("+03:00:44") == 10844 and parse_offset("-44") == -44
    assert fmt_offset(50400) == "+14:00" and fmt_offset(10844) == "+03:00:44"
    d = Device(id="A", kind="camera", tz_offset=10800, drift=39600)
    assert fmt_offset(d.raw_offset) == "+14:00"


def test_checks_flag_duplicates_and_corrupt(tmp_path):
    (tmp_path / "a").mkdir()
    payload = bytes(range(256)) * 20000
    for name in ("C1.MP4", "C2.MP4", "C3.MP4"):
        (tmp_path / "a" / name).write_bytes(payload if name != "C3.MP4" else payload[:-1] + b"\x00")
    (tmp_path / "a" / "C4.MP4").write_bytes(b"")
    ok = {"duration": 5.0, "vcodec": "h264"}
    clips = [Clip(id=f"C{i}", rel=f"a/C{i}.MP4", kind="video", size=(tmp_path / f"a/C{i}.MP4").stat().st_size,
                  mtime=0, probe=dict(ok)) for i in range(1, 5)]
    summary = checks.run_checks(tmp_path, clips)
    assert summary["duplicates"] == [["C1", "C2"]]
    assert summary["corrupt"] == {"C4": "zero-length file"}
    assert clips[1].flags == ["duplicate of C1"] and clips[2].flags == []
    assert (tmp_path / "a" / "C2.MP4").exists()                     # flagged, never deleted
