"""The analysis pipeline shared by the CLI and the app: frames -> describe -> structure."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hypershutter.core import config, cost, describe, frames, store, structure
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


@dataclass
class AnalyzeResult:
    structure: structure.Structure
    descriptions: dict[str, dict] = field(default_factory=dict)
    usage: describe.Usage | None = None
    structure_usage: dict = field(default_factory=dict)

    def cost(self) -> float:
        total = self.usage.cost() if self.usage else 0.0
        if self.structure_usage:
            pin, pout = cost.MODELS.get(self.structure_usage["model"], cost.MODELS[cost.DEFAULT_MODEL])["price"]
            total += self.structure_usage["input"] / 1e6 * pin + self.structure_usage["output"] / 1e6 * pout
        return round(total, 2)


def structure_path(p: Project) -> Path:
    return config.cache_dir("structure", store.project_id(Path(p.root))) / "latest.json"


def prepare(p: Project, opts: AnalyzeOptions, progress: Progress | None = None) -> dict[str, list[frames.Frame]]:
    """Frames (cached after the first run) for every readable video clip."""
    fs = frames.FrameSettings(interval=opts.interval)
    video = [c for c in p.clips.values() if c.kind == "video"]
    return frames.extract_all(Path(p.root), video, fs, progress=progress)


def estimate(by_clip: dict[str, list[frames.Frame]], model: str) -> cost.Estimate:
    return cost.estimate([len(f) for f in by_clip.values()], model)


def run(p: Project, opts: AnalyzeOptions, by_clip: dict[str, list[frames.Frame]],
        progress: Progress | None = None) -> AnalyzeResult:
    """Pass 1 + pass 2 (or the offline segmentation); the proposal is saved for Review."""
    preset = config.load_preset(opts.event_type)
    if opts.offline:
        st = structure.offline_structure(p, list(by_clip), preset)
        structure_path(p).write_text(json.dumps({"structure": st.to_json(), "raw": {}}, ensure_ascii=False))
        return AnalyzeResult(st)
    fs = frames.FrameSettings(interval=opts.interval)
    t0 = time.time()
    descs, usage = describe.describe_all(p, by_clip, fs, opts.model, opts.effort_describe, opts.event_type,
                                         progress=progress)
    usage.wall = time.time() - t0
    if progress:
        progress("structure", 0, 1)
    notes = f"Day schedule given by the videographer: {opts.schedule.strip()}\n" if opts.schedule.strip() else ""
    raw, su = structure.ai_structure(p, descs, opts.event_type, opts.model, opts.effort_structure, notes)
    st = structure.finalize(p, raw, descs, preset)
    st.usage = su
    if progress:
        progress("structure", 1, 1)
    structure_path(p).write_text(json.dumps({"structure": st.to_json(), "raw": raw}, ensure_ascii=False))
    return AnalyzeResult(st, descs, usage, su)


def analyze(p: Project, opts: AnalyzeOptions, confirm: Callable[[cost.Estimate], bool] = lambda e: True,
            progress: Progress | None = None) -> AnalyzeResult | None:
    by_clip = prepare(p, opts, progress)
    if not opts.offline and not confirm(estimate(by_clip, opts.model)):
        return None
    return run(p, opts, by_clip, progress)
