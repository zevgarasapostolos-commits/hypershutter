"""FCP7 XML (xmeml v4) for Premiere, modelled on the sequences the videographer imports today.

Sequence 25 fps 3840x2160. Plain clips: in/out in sequence frames. Slowed clips (Time Remap):
in/out in source frames at the clip's own rate. 1080p clips get Basic Motion scale 200 %.
Audio fades are Constant Power transition items. Every file must exist and every in/out must
lie inside its clip; `Sequence.check()` verifies both before anything is written.
"""

from __future__ import annotations

import os
import zlib
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

FPS = 25
WIDTH, HEIGHT = 3840, 2160


@dataclass(frozen=True)
class Media:
    path: str                  # absolute path on disk
    duration: float            # seconds
    fps: float = 25.0
    width: int = 3840
    height: int = 2160
    has_video: bool = True
    audio_channels: int = 2

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def rate(self) -> int:
        return max(1, round(self.fps))


@dataclass
class Item:
    media: Media
    start: int                 # sequence frames
    end: int
    src_in: float              # seconds inside the source
    speed: float = 1.0         # 0.5 = half speed (video only)
    channel: int = 1           # audio: which source channel (1 or 2)
    fade_in: int = 0           # audio: Constant Power frames at the start
    fade_out: int = 0
    enabled: bool = True
    gain_db: float = 0.0       # audio: clip level (Audio Levels), 0 = unchanged

    @property
    def frames(self) -> int:
        return self.end - self.start

    @property
    def src_out(self) -> float:
        return self.src_in + self.frames / FPS * self.speed


@dataclass
class Marker:
    name: str
    at: int                    # sequence frame
    comment: str = ""


@dataclass
class Sequence:
    name: str
    video: list[list[Item]] = field(default_factory=lambda: [[]])
    audio: list[list[Item]] = field(default_factory=lambda: [[]])
    markers: list[Marker] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return max([i.end for tr in self.video + self.audio for i in tr] or [0])

    def check(self) -> list[str]:
        problems = []
        for kind, tracks in (("V", self.video), ("A", self.audio)):
            for n, tr in enumerate(tracks, start=1):
                last = 0
                for it in sorted(tr, key=lambda i: i.start):
                    where = f"{kind}{n} {it.media.name} @{it.start}"
                    if not os.path.exists(it.media.path):
                        problems.append(f"{where}: file missing")
                    if it.end <= it.start:
                        problems.append(f"{where}: empty")
                    if it.start < last:
                        problems.append(f"{where}: overlaps the previous item")
                    if it.src_in < -1e-6 or it.src_out > it.media.duration + 1 / FPS + 1e-6:
                        problems.append(f"{where}: in/out {it.src_in:.2f}-{it.src_out:.2f} outside 0-{it.media.duration:.2f}")
                    last = it.end
        return problems


def pathurl(path: str) -> str:
    """file://localhost + path with spaces, parentheses and URL-special characters escaped."""
    out = path
    for ch, rep in (("%", "%25"), (" ", "%20"), ("(", "%28"), (")", "%29"), ("#", "%23"), ("?", "%3F")):
        out = out.replace(ch, rep)
    return "file://localhost" + out


def _rate(tb: int) -> str:
    return f"<rate><timebase>{tb}</timebase><ntsc>FALSE</ntsc></rate>"


class _Writer:
    def __init__(self):
        self.files_done: set[str] = set()
        self.n = 0

    def file(self, m: Media) -> str:
        fid = f"f-{escape(m.name)}-{zlib.crc32(m.path.encode()) % 10**6}"
        if fid in self.files_done:
            return f'<file id="{fid}" />'
        self.files_done.add(fid)
        frames = round(m.duration * m.rate)
        video = (f"<video><samplecharacteristics>{_rate(m.rate)}<width>{m.width}</width><height>{m.height}</height>"
                 f"<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></video>") if m.has_video else ""
        audio = (f"<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>"
                 f"<channelcount>{m.audio_channels}</channelcount></audio>") if m.audio_channels else ""
        return (f'<file id="{fid}"><name>{escape(m.name)}</name><pathurl>{escape(pathurl(m.path))}</pathurl>'
                f"{_rate(m.rate)}<duration>{frames}</duration><media>{video}{audio}</media></file>")

    def clip(self, it: Item, track_id: str, audio: bool) -> str:
        self.n += 1
        m = it.media
        seq_len = round(m.duration * FPS)
        if not audio and abs(it.speed - 1.0) > 1e-6:
            # Time Remap: in/out in source frames at the source rate, as Premiere writes them
            src_in, src_out = round(it.src_in * m.rate), round(it.src_out * m.rate)
            filt = ("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid><effectcategory>motion</effectcategory>"
                    "<effecttype>motion</effecttype><mediatype>video</mediatype>"
                    '<parameter authoringApp="PremierePro"><parameterid>variablespeed</parameterid><name>variablespeed</name>'
                    "<valuemin>0</valuemin><valuemax>1</valuemax><value>0</value></parameter>"
                    '<parameter authoringApp="PremierePro"><parameterid>speed</parameterid><name>speed</name>'
                    f"<valuemin>-100000</valuemin><valuemax>100000</valuemax><value>{it.speed * 100:.4f}</value></parameter>"
                    '<parameter authoringApp="PremierePro"><parameterid>reverse</parameterid><name>reverse</name><value>FALSE</value></parameter>'
                    '<parameter authoringApp="PremierePro"><parameterid>frameblending</parameterid><name>frameblending</name>'
                    "<value>FALSE</value></parameter></effect></filter>")
        else:
            src_in, src_out = round(it.src_in * FPS), round(it.src_in * FPS) + it.frames
            filt = ""
        if not audio and m.has_video and m.width < WIDTH:
            scale = WIDTH / m.width * 100
            filt += ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>"
                     "<effecttype>motion</effecttype><mediatype>video</mediatype>"
                     '<parameter authoringApp="PremierePro"><parameterid>scale</parameterid><name>Scale</name>'
                     f"<valuemin>0</valuemin><valuemax>1000</valuemax><value>{scale:.1f}</value></parameter></effect></filter>")
        if audio and abs(it.gain_db) > 0.05:
            gain = 10 ** (it.gain_db / 20)
            filt += ("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid>"
                     "<effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype>"
                     "<mediatype>audio</mediatype><parameter authoringApp=\"PremierePro\"><parameterid>level</parameterid>"
                     f"<name>Level</name><valuemin>0</valuemin><valuemax>3.98109</valuemax><value>{gain:.5f}</value>"
                     "</parameter></effect></filter>")
        source = (f"<sourcetrack><mediatype>audio</mediatype><trackindex>{it.channel}</trackindex></sourcetrack>"
                  if audio else "")
        return (f'<clipitem id="{track_id}-{self.n}"><name>{escape(m.name)}</name>'
                f"<enabled>{'TRUE' if it.enabled else 'FALSE'}</enabled><duration>{seq_len}</duration>{_rate(FPS)}"
                f"<start>{it.start}</start><end>{it.end}</end><in>{src_in}</in><out>{src_out}</out>"
                f"{self.file(m)}{filt}{source}</clipitem>")

    @staticmethod
    def fade(start: int, end: int, alignment: str) -> str:
        return (f"<transitionitem>{_rate(FPS)}<start>{start}</start><end>{end}</end><alignment>{alignment}</alignment>"
                "<effect><name>Constant Power</name><effectid>KGAudioTransCrossFade3dB</effectid>"
                "<effectcategory>Dissolve</effectcategory><effecttype>transition</effecttype><mediatype>audio</mediatype>"
                "</effect></transitionitem>")


def to_xml(seq: Sequence) -> str:
    w = _Writer()
    markers = "".join(f"<marker><name>{escape(mk.name)}</name><comment>{escape(mk.comment)}</comment>"
                      f"<in>{mk.at}</in><out>-1</out></marker>" for mk in seq.markers)
    vtracks = []
    for n, tr in enumerate(seq.video, start=1):
        items = "".join(w.clip(it, f"v{n}", False) for it in sorted(tr, key=lambda i: i.start))
        vtracks.append(f"<track>{items}</track>")
    atracks = []
    for n, tr in enumerate(seq.audio, start=1):
        parts = []
        for it in sorted(tr, key=lambda i: i.start):
            if it.fade_in:
                parts.append(w.fade(it.start, it.start + it.fade_in, "start-black"))
            parts.append(w.clip(it, f"a{n}", True))
            if it.fade_out:
                parts.append(w.fade(it.end - it.fade_out, it.end, "end-black"))
        atracks.append(f"<track>{''.join(parts)}<outputchannelindex>{1 if n % 2 else 2}</outputchannelindex></track>")
    fmt = (f"<format><samplecharacteristics>{_rate(FPS)}<width>{WIDTH}</width><height>{HEIGHT}</height>"
           "<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics></format>")
    afmt = "<format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="seq-1"><name>{escape(seq.name)}</name><duration>{seq.duration}</duration>{_rate(FPS)}{markers}'
            f"<media><video>{fmt}{''.join(vtracks)}</video>"
            f"<audio><numOutputChannels>2</numOutputChannels>{afmt}{''.join(atracks)}</audio></media>"
            "</sequence></xmeml>\n")
