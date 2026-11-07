"""The analysis pipeline shared by the CLI and the app: frames + sound -> describe -> structure.

`AnalyzeOptions.signals` chooses what the sorting may use about each clip (time, camera, image,
audio); the default is everything, the ablation study switches signals off one by one."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hypershutter.core import audio_tags, config, cost, describe, frames, store, structure
from hypershutter.core.project import Project

Progress = Callable[[str, int, int], None]


@dataclass
class AnalyzeOptions:
    event_type: str = "baptism"
    model: str = cost.DEFAULT_MODEL
    effort_describe: str = "low"
    effort_structure: str = "high"
    interval: float = 2.0
    offline: bool = False
    schedule: str = ""              # the videographer's day schedule, passed to pass 2 as a hint
    signals: tuple[str, ...] = structure.SIGNALS
    audio_in_describe: bool = True  # pass 1 hears the clip too (else the sound only reaches pass 2)
    speech: bool = True             # Whisper cue words on clips with speech or chanting
    elsewhere: tuple[str, ...] = () # folders holding clips that were moved off the event folder


@dataclass
class AnalyzeResult:
    structure: structure.Structure
    descriptions: dict[str, dict] = field(default_factory=dict)
    usage: describe.Usage | None = None
    structure_usage: dict = field(default_factory=dict)
    audio: dict[str, dict] = field(default_factory=dict)

    def cost(self) -> float:
        total = self.usage.cost() if self.usage else 0.0
        if self.structure_usage:
            pin, pout = cost.MODELS.get(self.structure_usage["model"], cost.MODELS[cost.DEFAULT_MODEL])["price"]
            total += self.structure_usage["input"] / 1e6 * pin + self.structure_usage["output"] / 1e6 * pout
        return round(total, 2)


def structure_path(p: Project) -> Path:
    return config.cache_dir("structure", store.project_id(Path(p.root))) / "latest.json"


def prepare(p: Project, opts: AnalyzeOptions, progress: Progress | None = None,
            ids: list[str] | None = None) -> dict[str, list[frames.Frame]]:
    """Frames (cached after the first run) for every readable video clip, or only for `ids`."""
    fs = frames.FrameSettings(interval=opts.interval)
    wanted = set(ids) if ids is not None else None
    video = [c for c in p.clips.values() if c.kind == "video" and (wanted is None or c.id in wanted)]
    return frames.extract_all(Path(p.root), video, fs, progress=progress)


def prepare_audio(p: Project, opts: AnalyzeOptions, ids: list[str], progress: Progress | None = None) -> dict[str, dict]:
    """Sound tags and cue words for every clip (local models, cached; no API cost)."""
    clips = [p.clips[i] for i in ids]
    return audio_tags.analyze_all(p, clips, opts.event_type, speech=opts.speech, progress=progress,
                                  elsewhere=[Path(d) for d in opts.elsewhere])


def sound_lines(audio: dict[str, dict]) -> dict[str, str]:
    return {cid: audio_tags.short_line(a["tags"], a["heard"]) for cid, a in audio.items()}


def sound_texts(audio: dict[str, dict]) -> dict[str, str]:
    return {cid: audio_tags.timeline_text(a["tags"], a["heard"]) for cid, a in audio.items()}


def estimate(p: Project, by_clip: dict[str, list[frames.Frame]], model: str, interval: float = 2.0,
             audio: dict[str, dict] | None = None) -> cost.Estimate:
    """Cost of both passes; clips already described with this model and these frames are free."""
    fs = frames.FrameSettings(interval=interval)
    texts = sound_texts(audio) if audio else {}
    todo = [len(f) for cid, f in by_clip.items() if describe.cached(p, p.clips[cid], model, fs, texts.get(cid, "")) is None]
    return cost.estimate(todo, model, total_clips=len(by_clip))


def run(p: Project, opts: AnalyzeOptions, by_clip: dict[str, list[frames.Frame]],
        progress: Progress | None = None, audio: dict[str, dict] | None = None,
        save: bool = True) -> AnalyzeResult:
    """Pass 1 + pass 2 (or the offline segmentation); the proposal is saved for Review."""
    preset = config.load_preset(opts.event_type)
    signals = frozenset(opts.signals) | {"time"}
    ids = list(by_clip)
    if "audio" in signals and audio is None:
        audio = prepare_audio(p, opts, ids, progress)
    audio = audio if "audio" in signals else {}
    if opts.offline:
        st = structure.offline_structure(p, ids, preset, sound=audio or None)
        if save:
            structure_path(p).write_text(json.dumps({"structure": st.to_json(), "raw": {}}, ensure_ascii=False))
        return AnalyzeResult(st, audio=audio)
    descs: dict[str, dict] = {}
    usage = None
    if "image" in signals:
        fs = frames.FrameSettings(interval=opts.interval)
        t0 = time.time()
        texts = sound_texts(audio) if audio and opts.audio_in_describe else None
        descs, usage = describe.describe_all(p, by_clip, fs, opts.model, opts.effort_describe, opts.event_type,
                                             progress=progress, audio=texts)
        usage.wall = time.time() - t0
    if progress:
        progress("structure", 0, 1)
    notes = f"Day schedule given by the videographer: {opts.schedule.strip()}\n" if opts.schedule.strip() else ""
    raw, su = structure.ai_structure(p, descs, opts.event_type, opts.model, opts.effort_structure, notes,
                                     signals=signals, sound=sound_lines(audio) if audio else None, ids=ids)
    st = structure.finalize(p, raw, descs, preset, signals=signals)
    st.usage = su
    if progress:
        progress("structure", 1, 1)
    if save:
        structure_path(p).write_text(json.dumps({"structure": st.to_json(), "raw": raw}, ensure_ascii=False))
    return AnalyzeResult(st, descs, usage, su, audio)


def analyze(p: Project, opts: AnalyzeOptions, confirm: Callable[[cost.Estimate], bool] = lambda e: True,
            progress: Progress | None = None) -> AnalyzeResult | None:
    by_clip = prepare(p, opts, progress)
    audio = prepare_audio(p, opts, list(by_clip), progress) if "audio" in opts.signals else None
    if not opts.offline and "image" in opts.signals and not confirm(
            estimate(p, by_clip, opts.model, opts.interval, audio if opts.audio_in_describe else None)):
        return None
    return run(p, opts, by_clip, progress, audio)
