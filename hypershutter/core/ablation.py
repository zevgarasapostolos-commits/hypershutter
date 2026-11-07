"""Ablation study and frame-density comparison (thesis §6.7).

Every condition runs the same read-only sorting on an organized event, with some signals switched
off, and is scored against the videographer's own folders with the grouping metrics of
`evaluate`. Pass 2 is not deterministic, so each condition repeats and reports mean ± sd.
Pass-1 descriptions and sound analysis are cached, so a repeat only costs the pass-2 call.
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from hypershutter.core import config, evaluate, frames, pipeline, structure
from hypershutter.core.project import Project

ALL = structure.SIGNALS
CONDITIONS: dict[str, dict] = {
    "offline: time gaps": {"offline": True, "signals": ("time", "camera")},
    "offline: time gaps + sound": {"offline": True, "signals": ("time", "camera", "audio")},
    "time": {"signals": ("time",)},
    "time + camera": {"signals": ("time", "camera")},
    "time + camera + sound": {"signals": ("time", "camera", "audio")},
    "time + camera + image": {"signals": ("time", "camera", "image")},
    "all (sound in pass 2 only)": {"signals": ALL, "audio_in_describe": False},
    "all": {"signals": ALL, "audio_in_describe": True},
}
KEYS = ("matched_accuracy", "pairwise_f1", "ari", "boundary_f1", "folders_pred")


def truth_of(p: Project) -> dict[str, str]:
    return evaluate.truth_from_folders({c.id: c.rel for c in p.clips.values() if c.kind == "video"})


def score(p: Project, truth: dict[str, str], st: structure.Structure, ids: list[str] | None = None) -> dict:
    pred = {cid: st.folder_of(cid) for cid in st.assignment if ids is None or cid in ids}
    t = {cid: f for cid, f in truth.items() if cid in pred}
    order = [c.id for _, c in p.timeline() if c.id in pred]
    m = evaluate.metrics(t, pred, order)
    return {"matched_accuracy": m["matched_accuracy"], "pairwise_f1": m["pairwise"]["f1"], "ari": m["ari"],
            "boundary_f1": m["boundaries"]["f1"], "folders_pred": m["folders_pred"], "folders_truth": m["folders_truth"]}


def summarize(runs: list[dict]) -> dict:
    out = {}
    for k in KEYS:
        xs = [r[k] for r in runs if k in r]
        if xs:
            out[k] = {"mean": round(statistics.fmean(xs), 4), "sd": round(statistics.stdev(xs), 4) if len(xs) > 1 else 0.0}
    out["cost"] = round(sum(r.get("cost", 0) for r in runs), 2)
    out["seconds"] = round(statistics.fmean([r.get("seconds", 0) for r in runs]), 1) if runs else 0
    out["n"] = len(runs)
    return out


def run_conditions(p: Project, base: pipeline.AnalyzeOptions, conditions: list[str], reps: int = 3,
                   ids: list[str] | None = None, workers: int = 4,
                   log: Callable[[str], None] = print) -> dict:
    """Every condition `reps` times (offline ones once: they are deterministic)."""
    truth = truth_of(p)
    by_clip = pipeline.prepare(p, base, ids=ids)
    by_clip = {cid: f for cid, f in by_clip.items() if cid in truth}
    needs_sound = any("audio" in CONDITIONS[n]["signals"] for n in conditions)
    audio = pipeline.prepare_audio(p, base, list(by_clip)) if needs_sound else {}
    heard = sum(1 for a in audio.values() if not a["tags"].get("missing"))
    log(f"{p.name.strip()}: {len(by_clip)} clips with ground truth, sound for {heard}")

    def one(job: tuple[str, int]) -> tuple[str, dict]:
        name, rep = job
        opts = replace(base, **CONDITIONS[name])
        t0 = time.time()
        res = pipeline.run(p, opts, by_clip, audio=audio, save=False)
        r = score(p, truth, res.structure, ids)
        r.update(cost=res.cost(), seconds=round(time.time() - t0, 1), rep=rep)
        log(f"  {name:28s} #{rep}: acc {r['matched_accuracy']:.1%} · F1 {r['pairwise_f1']:.3f} · "
            f"ARI {r['ari']:.3f} · folders {r['folders_pred']}/{r['folders_truth']} · ${r['cost']:.2f}")
        return name, r

    # pass 1 first, once per pass-1 variant, so that the parallel repeats only differ in pass 2
    for name in conditions:
        c = CONDITIONS[name]
        if "image" in c["signals"] and not c.get("offline"):
            opts = replace(base, **c)
            texts = pipeline.sound_texts(audio) if opts.audio_in_describe else None
            from hypershutter.core import describe
            fs = frames.FrameSettings(interval=opts.interval)
            _, u = describe.describe_all(p, by_clip, fs, opts.model, opts.effort_describe, opts.event_type, audio=texts)
            if u.calls:
                log(f"  pass 1 for «{name}»: {u.calls} new descriptions, ${u.cost():.2f}")
    jobs = [(n, k) for n in conditions for k in range(1, (1 if CONDITIONS[n].get("offline") else reps) + 1)]
    results: dict[str, list[dict]] = {n: [] for n in conditions}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for name, r in ex.map(one, jobs):
            results[name].append(r)
    return {"event": p.name.strip(), "clips": len(by_clip), "with_sound": heard, "reps": reps,
            "model": base.model, "conditions": {n: {"summary": summarize(rs), "runs": rs} for n, rs in results.items()}}


def subset(p: Project, size: int = 120) -> list[str]:
    """A stratified subset for the density study: every folder, in proportion, spread over time;
    ceremony masters (long main-camera takes) always in."""
    truth = truth_of(p)
    by_folder: dict[str, list] = {}
    for _, c in p.timeline():
        if c.id in truth:
            by_folder.setdefault(truth[c.id], []).append(c)
    total = sum(len(v) for v in by_folder.values())
    out: list[str] = []
    for f, cs in by_folder.items():
        k = min(len(cs), max(3, round(size * len(cs) / total)))
        step = len(cs) / k
        out += [cs[int(i * step)].id for i in range(k)]
        out += [c.id for c in cs if c.device == "A" and c.duration >= 2 * structure.FLOW_MIN_S and c.id not in out]
    return out


def density_study(p: Project, base: pipeline.AnalyzeOptions, intervals: tuple[float, ...] = (4.0, 2.0, 1.0),
                  reps: int = 3, size: int = 120, log: Callable[[str], None] = print) -> dict:
    """Pictures only (time + camera + image) on a subset, at several frame densities."""
    ids = subset(p, size)
    log(f"{p.name.strip()}: density subset of {len(ids)} clips")
    out = {"event": p.name.strip(), "clips": len(ids), "intervals": {}}
    for iv in intervals:
        opts = replace(base, interval=iv, signals=("time", "camera", "image"))
        fs = frames.FrameSettings(interval=iv)
        t0 = time.time()
        fr = frames.extract_all(Path(p.root), [p.clips[i] for i in ids], fs)
        n_frames = sum(len(v) for v in fr.values())
        log(f"  1 frame / {iv:g} s: {n_frames} frames ({time.time() - t0:.0f} s to extract)")
        r = run_conditions(p, opts, ["time + camera + image"], reps=reps, ids=ids, log=log)
        r["frames"] = n_frames
        r["extract_s"] = round(time.time() - t0)
        out["intervals"][f"{iv:g}"] = r
    return out


def save(result: dict, stem: str) -> Path:
    out = config.reports_dir("ablation")
    path = out / f"{stem}-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return path


def table_md(result: dict) -> str:
    rows = ["| Condition | Matched acc. | Pairwise F1 | ARI | Boundary F1 | Folders | Cost |", "|---|---|---|---|---|---|---|"]
    for name, c in result["conditions"].items():
        s = c["summary"]
        if "matched_accuracy" not in s:
            continue
        def f(k, pct=False):
            m, sd = s[k]["mean"], s[k]["sd"]
            return (f"{m:.1%} ± {sd:.1%}" if pct else f"{m:.3f} ± {sd:.3f}") if s["n"] > 1 else (f"{m:.1%}" if pct else f"{m:.3f}")
        rows.append(f"| {name} | {f('matched_accuracy', True)} | {f('pairwise_f1')} | {f('ari')} | {f('boundary_f1')} | "
                    f"{s['folders_pred']['mean']:.1f} | ${s['cost']:.2f} |")
    return "\n".join(rows)
