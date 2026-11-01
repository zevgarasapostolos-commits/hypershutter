"""The analysis pipeline shared by the CLI and the app: frames -> describe -> structure."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from hypershutter.core import config, cost, describe, frames, store, structure
from hypershutter.core.project import Project


@dataclass
class AnalyzeOptions:
    event_type: str = "baptism"
    model: str = cost.DEFAULT_MODEL
    effort_describe: str = "low"
    effort_structure: str = "high"
    interval: float = 2.0
    offline: bool = False


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


def analyze(p: Project, opts: AnalyzeOptions, confirm: Callable[[cost.Estimate], bool] = lambda e: True,
            progress: Callable[[str, int, int], None] | None = None) -> AnalyzeResult | None:
    root = Path(p.root)
    fs = frames.FrameSettings(interval=opts.interval)
    video = [c for c in p.clips.values() if c.kind == "video"]
    by_clip = frames.extract_all(root, video, fs, progress=progress)
    preset = config.load_preset(opts.event_type)
    if opts.offline:
        st = structure.offline_structure(p, list(by_clip), preset)
        return AnalyzeResult(st)
    est = cost.estimate([len(f) for f in by_clip.values()], opts.model)
    if not confirm(est):
        return None
    t0 = time.time()
    descs, usage = describe.describe_all(p, by_clip, fs, opts.model, opts.effort_describe, opts.event_type,
                                         progress=progress)
    usage.wall = time.time() - t0
    raw, su = structure.ai_structure(p, descs, opts.event_type, opts.model, opts.effort_structure)
    st = structure.finalize(p, raw, descs, preset)
    st.usage = su
    structure_path(p).write_text(json.dumps({"structure": st.to_json(), "raw": raw}, ensure_ascii=False))
    return AnalyzeResult(st, descs, usage, su)
