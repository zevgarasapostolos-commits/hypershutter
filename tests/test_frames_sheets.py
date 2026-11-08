import subprocess
from datetime import datetime

import pytest
from PIL import Image

from hypershutter.core import config, cost, frames, sheets
from hypershutter.core.media import Clip


def test_sample_times_are_centred_and_cover_short_clips():
    assert frames.sample_times(5.0, 2.0) == [1.5, 3.5]
    assert frames.sample_times(1.0, 2.0) == [0.5]
    assert frames.sample_times(10.0, 2.0) == [1.0, 3.0, 5.0, 7.0, 9.0]
    assert frames.sample_times(0.0, 2.0) == []


def test_sheet_fits_vision_limits_and_matches_shape_estimate(tmp_path):
    img = tmp_path / "f.jpg"
    Image.new("RGB", (640, 360), (40, 90, 160)).save(img)
    layout = sheets.SheetLayout()
    for n in (1, 5, 6, 7, 24):
        w, h = sheets.render([(str(img), "0:12 · 16:59:27")] * n, layout, tmp_path / f"s{n}.jpg")
        assert (w, h) == sheets.sheet_shapes(n, layout)[0]
        assert w <= sheets.MAX_EDGE and w * h <= sheets.MAX_PIXELS
    assert len(sheets.sheet_shapes(50, layout)) == 3                 # 24 + 24 + 2


def test_estimate_scales_with_frames():
    small = cost.estimate([3, 3], "claude-opus-5-5")
    big = cost.estimate([300, 300], "claude-opus-5-5")
    assert big.sheets == 2 * 13 and big.cost_usd > small.cost_usd > 0


@pytest.fixture
def cut_video(tmp_path):
    """6 s at 25 fps, red for 3 s then blue: one hard cut, a keyframe every 12 frames."""
    out = tmp_path / "ev" / "cam" / "C0001.MP4"
    out.parent.mkdir(parents=True)
    ffmpeg = config.find_tool("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=red:s=320x180:d=3:r=25",
                    "-f", "lavfi", "-i", "color=blue:s=320x180:d=3:r=25", "-filter_complex", "[0][1]concat=n=2:v=1",
                    "-c:v", "libx264", "-g", "12", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def test_extract_all_samples_and_adds_scene_frame(cut_video, tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSHUTTER_HOME", str(tmp_path / "hs"))
    root = cut_video.parents[1]
    st = cut_video.stat()
    clip = Clip(id="C0001", rel="cam/C0001.MP4", kind="video", size=st.st_size, mtime=st.st_mtime,
                probe={"duration": 6.0, "vcodec": "h264"})
    fs = frames.FrameSettings(interval=2.0, width=160, workers=2)
    got = frames.extract_all(root, [clip], fs)["C0001"]
    assert [f.t for f in got if not f.scene] == [1.0, 3.0, 5.0]
    assert [f.t for f in got if f.scene] == [2.0, 4.0] or [f.t for f in got if f.scene] == [2.0]
    colours = [Image.open(f.path).convert("RGB").getpixel((80, 45)) for f in got if not f.scene]
    assert colours[0][0] > 200 and colours[-1][2] > 200                # red first, blue last
    # second call is served from the cache
    assert frames.load_cached(clip, fs) is not None
    paths = sheets.clip_sheets(clip, got, datetime(2026, 10, 11, 16, 59, 15), fs)
    assert len(paths) == 1 and paths[0].exists()
