from datetime import datetime

from hypershutter.core import timecode as tc

SONY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20" lastUpdate="2026-10-11T13:16:56+03:00">
\t<Duration value="2088"/>
\t<CreationDate value="2026-10-11T13:16:14+03:00"/>
\t<Device manufacturer="Sony" modelName="ILCE-7M4" serialNo="01234567"/>
</NonRealTimeMeta>"""

SRT = """1
00:00:00,000 --> 00:00:00,020
<font size="28">FrameCnt: 1, DiffTime: 20ms
2026-09-06 22:37:28.293
[iso: 3090] [shutter: 1/100.0] </font>
"""


def test_dji_video_name():
    assert tc.parse_dji_video_name("DJI_20261011163207_0033_D") == datetime(2026, 10, 11, 16, 32, 7)
    assert tc.parse_dji_video_name("DJI_0001") is None


def test_recorder_name():
    assert tc.parse_recorder_name("DJI_02_20261004_120804") == datetime(2026, 10, 4, 12, 8, 4)
    assert tc.parse_recorder_name("DJI_20261011163207_0033_D") is None


def test_sony_xml_keeps_local_reading_and_device():
    meta = tc.parse_sony_xml(SONY_XML)
    assert meta["local"] == datetime(2026, 10, 11, 13, 16, 14)
    assert meta["model"] == "Sony ILCE-7M4" and meta["serial"] == "01234567"


def test_srt_start():
    assert tc.parse_srt_start(SRT) == datetime(2026, 9, 6, 22, 37, 28, 293000)


def test_creation_time_utc_to_greek_local_summer_and_winter():
    summer = tc.parse_creation_time("2026-10-11T14:00:46.000000Z")
    assert tc.utc_to_local(summer) == (datetime(2026, 10, 11, 17, 0, 46), 3 * 3600)
    winter = tc.parse_creation_time("2026-12-05T10:00:00Z")
    assert tc.utc_to_local(winter) == (datetime(2026, 12, 5, 12, 0, 0), 2 * 3600)
    assert tc.parse_creation_time("1904-01-01T00:00:00Z") is None


def test_source_priority():
    probe = {"creation_time": "2026-10-11T10:16:14Z"}
    r = tc.capture_reading("C6501", probe, {"C6501M01.XML": SONY_XML}, 0, 10)
    assert r[1] == "sony_xml" and r[2] == datetime(2026, 10, 11, 13, 16, 14)
    r = tc.capture_reading("DJI_20261011163207_0033_D", {"creation_time": "2026-10-11T13:32:08Z"}, {}, 0, 12)
    assert r[1] == "dji_name" and r[2] == datetime(2026, 10, 11, 16, 32, 7)
    r = tc.capture_reading("C4255", {"creation_time": "2026-10-11T02:59:15.000000Z"}, {}, 0, 134.88)
    assert r[1] == "creation_time"
    assert r[0] == datetime(2026, 10, 11, 2, 59, 15)          # raw reading, as the user's index counts it
    assert r[2] == datetime(2026, 10, 11, 5, 59, 15) and r[3] == 3 * 3600
