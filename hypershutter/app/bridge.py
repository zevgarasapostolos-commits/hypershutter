"""The app's API: every screen calls these methods (as JSON over the local server).

Long work (scan, sync, frames, the AI passes) runs as one background job at a time; the UI
polls `poll()` for progress events. Nothing here moves or writes footage: Review edits are
saved to Application Support; files move only through Apply (with its journal and Undo).
"""

from __future__ import annotations

import subprocess
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Callable

from hypershutter import __version__
from hypershutter.core import (checks, config, cost, describe, execute, frames, index, pipeline, review, scan,
                               store, sync)
from hypershutter.core.media import fmt_duration, fmt_offset
from hypershutter.core.project import Project
from hypershutter.core.structure import Structure

EVENT_TYPES = ("baptism", "wedding", "event")
SCRUB_FRAMES = 16                      # frames per clip sent to the Review grid for hover scrubbing
STAGE = {"probe": "scan", "frames": "frames", "scene": "frames", "describe": "describe", "structure": "structure",
         "backup": "backup", "move": "move", "undo": "undo"}


class Bridge:
    def __init__(self, media_url: Callable[[str], str], pick_folder: Callable[[], str | None] | None = None):
        self._media_url = media_url
        self._pick = pick_folder or _osascript_folder
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._job: dict | None = None
        self._p: Project | None = None
        self._by_clip: dict[str, list[frames.Frame]] | None = None
        self._st: Structure | None = None

    # ---------- events and jobs ----------

    def _emit(self, **event) -> None:
        with self._lock:
            self._events.append(event)

    def poll(self) -> dict:
        with self._lock:
            events, self._events = self._events, []
            job = dict(self._job) if self._job else None
        return {"events": events, "job": job}

    def _start(self, name: str, work: Callable[[], dict]) -> dict:
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise RuntimeError("another task is still running")
            self._job = {"name": name, "status": "running", "stage": "", "done": 0, "total": 0, "started": time.time()}

        def run():
            try:
                result = work()
                with self._lock:
                    self._job.update(status="done", result=result)
                self._emit(type="job_done", name=name, result=result)
            except Exception as e:                      # surfaced in the UI, details in the terminal
                traceback.print_exc()
                with self._lock:
                    self._job.update(status="error", error=str(e))
                self._emit(type="job_error", name=name, error=str(e))

        threading.Thread(target=run, daemon=True).start()
        return {"started": name}

    def _progress(self, stage: str, done: int, total: int) -> None:
        stage = STAGE.get(stage, stage)
        with self._lock:
            if self._job:
                self._job.update(stage=stage, done=done, total=total)
        self._emit(type="progress", stage=stage, done=done, total=total)

    # ---------- Home ----------

    def info(self) -> dict:
        return {"version": __version__, "event_types": list(EVENT_TYPES),
                "models": [{"id": k, "label": v["label"]} for k, v in cost.MODELS.items()],
                "default_model": cost.DEFAULT_MODEL, "ffmpeg": bool(config.find_tool("ffmpeg"))}

    def recent(self) -> list[dict]:
        out = []
        for r in store.recent_projects():
            out.append({**r, "available": Path(r["root"]).is_dir()})
        return out

    def pick_folder(self) -> str | None:
        return self._pick()

    def open_project(self, path: str) -> dict:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError("not a folder")
        p = Project.load(root)
        self._p, self._by_clip, self._st = p, None, None
        return {"root": str(root), "name": root.name, "known": p is not None,
                "event_type": p.event_type if p else "baptism", "event_name": p.event_name if p else "",
                "schedule": p.schedule if p else "", "has_structure": bool(p and review.load(p))}

    # ---------- Scan & Analyze ----------

    def start_scan(self, path: str, event_type: str = "baptism", event_name: str = "", schedule: str = "",
                   rescan: bool = False) -> dict:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError("not a folder")
        if event_type not in EVENT_TYPES:
            raise ValueError("unknown event type")

        def work() -> dict:
            p = None if rescan else Project.load(root)
            if p is None:
                self._progress("scan", 0, 1)
                p = scan.scan(root, progress=self._progress)
                checks.run_checks(root, list(p.clips.values()))
                p.save()
            self._progress("scan", 1, 1)
            if not p.synced_at:
                self._progress("sync", 0, 1)
                sync.auto_sync(p, root, log=lambda s: None)
            self._progress("sync", 1, 1)
            p.event_type, p.event_name, p.schedule = event_type, event_name.strip(), schedule.strip()
            p.save()
            self._p = p
            self._progress("frames", 0, 1)
            self._by_clip = pipeline.prepare(p, self._options(), self._progress)
            self._progress("frames", 1, 1)
            return self.scan_summary()

        return self._start("scan", work)

    def _options(self, model: str | None = None, offline: bool = False) -> pipeline.AnalyzeOptions:
        p = self._require()
        return pipeline.AnalyzeOptions(event_type=p.event_type, model=model or cost.DEFAULT_MODEL,
                                       offline=offline, schedule=p.schedule)

    def _require(self) -> Project:
        if self._p is None:
            raise RuntimeError("no project open")
        return self._p

    def scan_summary(self) -> dict:
        p = self._require()
        clips = list(p.clips.values())
        corrupt = [{"clip": c.name, "why": f} for c in clips for f in c.flags if f.startswith("corrupt")]
        dups = [{"clip": c.name, "why": f} for c in clips for f in c.flags if f.startswith("duplicate")]
        est = []
        if self._by_clip is not None:
            for model, info in cost.MODELS.items():
                e = pipeline.estimate(p, self._by_clip, model)
                est.append({"model": model, "label": info["label"], "cost": round(e.cost_usd, 2),
                            "minutes": max(1, round(e.minutes)), "clips": e.clips, "cached": e.cached,
                            "sheets": e.sheets, "frames": e.frames})
        return {"name": p.name, "videos": sum(c.kind == "video" for c in clips),
                "audio": sum(c.kind == "audio" for c in clips), "devices": self._devices(),
                "corrupt": corrupt, "duplicates": dups, "estimates": est,
                "has_structure": review.load(p) is not None}

    def _devices(self) -> list[dict]:
        p = self._require()
        out = []
        for d in sorted(p.devices.values(), key=lambda d: (d.kind != "camera", d.id)):
            cs = p.device_clips(d.id)
            out.append({"id": d.id, "kind": d.kind, "pattern": d.pattern, "model": d.model, "clips": len(cs),
                        "length": fmt_duration(sum(c.duration for c in cs)), "offset": fmt_offset(d.raw_offset),
                        "status": d.drift_status})
        return out

    def set_offset(self, device: str, text: str) -> dict:
        p = self._require()
        if device not in p.devices:
            raise KeyError(device)
        sync.set_manual(p, device, sync.parse_offset(text))
        p.save()
        return {"devices": self._devices()}

    def start_analyze(self, model: str | None = None, offline: bool = False) -> dict:
        p = self._require()
        if self._by_clip is None:
            raise RuntimeError("scan first")
        if model and model not in cost.MODELS:
            raise ValueError("unknown model")
        opts = self._options(model, offline)

        def work() -> dict:
            res = pipeline.run(p, opts, self._by_clip, self._progress)
            review.reset(p)                     # a new proposal replaces earlier review edits
            self._st = None
            return {"folders": len(res.structure.categories), "needs_review": len(res.structure.needs_review),
                    "cost": res.cost(), "refusals": res.usage.refusals if res.usage else 0,
                    "source": res.structure.source}

        return self._start("analyze", work)

    # ---------- Review ----------

    def _structure(self) -> Structure:
        p = self._require()
        if self._st is None:
            self._st = review.load(p)
        if self._st is None:
            raise RuntimeError("no structure yet: analyze first")
        return self._st

    def review(self) -> dict:
        p = self._require()
        st = self._structure()
        fs = frames.FrameSettings()
        clips = {}
        for cat in st.categories:
            for cid in cat.clips:
                c = p.clips[cid]
                t = p.corrected(c)
                fr = frames.load_cached(c, fs) or []
                pick = fr if len(fr) <= SCRUB_FRAMES else [fr[round(i * (len(fr) - 1) / (SCRUB_FRAMES - 1))]
                                                           for i in range(SCRUB_FRAMES)]
                clips[cid] = {"id": cid, "name": c.name, "device": c.device, "duration": fmt_duration(c.duration),
                              "seconds": round(c.duration, 1),
                              "time": f"{t:%H:%M:%S}" if t else "", "end": f"{t + timedelta(seconds=c.duration):%H:%M:%S}" if t else "",
                              "confidence": round(st.confidence.get(cid, 0), 2), "flags": c.flags,
                              "frames": [self._media_url(f.path) for f in pick]}
        descs = self._descriptions(st)
        for cid, d in descs.items():
            if cid in clips:
                clips[cid]["desc"] = d
        return {"name": p.name, "event_type": p.event_type, "source": st.source, "edited": st.edited,
                "notes": st.notes, "needs_review": st.needs_review, "stars": st.stars,
                "categories": [{"key": c.key, "folder": c.folder, "label": c.label_el, "number": c.number,
                                "sub": c.sub, "kind": c.kind, "description": c.description_el, "clips": c.clips,
                                "minutes": round(sum(p.clips[x].duration for x in c.clips) / 60, 1)}
                               for c in st.categories],
                "clips": clips}

    def _descriptions(self, st: Structure) -> dict[str, str]:
        """Greek one-liners from pass 1 when they are cached (never re-requested here)."""
        p = self._require()
        fs = frames.FrameSettings()
        model = (st.usage or {}).get("model") or cost.DEFAULT_MODEL
        out = {}
        for cid in st.assignment:
            d = describe.cached(p, p.clips[cid], model, fs)
            if d and not d.get("refused"):
                out[cid] = d.get("description_el") or d.get("description", "")
        return out

    def review_edit(self, op: str, args: dict) -> dict:
        p = self._require()
        st = self._structure()
        preset = config.load_preset(p.event_type)
        result = None
        if op == "move":
            review.move_clips(p, st, preset, args["clips"], args["to"])
        elif op == "rename":
            review.rename(p, st, preset, args["key"], args["label"])
        elif op == "describe":
            review.set_description(st, args["key"], args["text"])
        elif op == "merge":
            review.merge(p, st, preset, args["src"], args["dst"])
        elif op == "split":
            result = review.split(p, st, preset, args["key"], args["clips"], args.get("label", ""))
        elif op == "move_group":
            review.move_group(p, st, preset, args["key"], int(args["delta"]))
        elif op == "star":
            result = review.toggle_star(st, args["clip"])
        elif op == "resolve":
            review.resolve(st, args["clips"])
        else:
            raise ValueError(f"unknown edit {op!r}")
        review.save(p, st)
        return {"result": result, "review": self.review()}

    def review_reset(self) -> dict:
        p = self._require()
        self._st = review.reset(p)
        return self.review()


    # ---------- Apply / Undo ----------

    def apply_plan(self) -> dict:
        """The dry run shown before anything moves."""
        p = self._require()
        st = self._structure()
        blocked = None
        try:
            execute.check_allowed(p)
        except PermissionError as e:
            blocked = str(e)
        pl = execute.plan(p, st)
        clips = [m for m in pl.moves if m.kind == "clip"]
        return {"blocked": blocked, "moves": len(pl.moves), "clips": len(clips),
                "sidecars": len(pl.moves) - len(clips), "new_folders": len(pl.folders),
                "folders": len({m.dst.split("/", 1)[0] for m in pl.moves}), "in_place": pl.in_place,
                "unassigned": len(pl.unassigned), "conflicts": pl.conflicts, "edited": pl.edited,
                "gb": round(sum(m.size for m in pl.moves) / 1e9, 2), "last": self._last_run()}

    def _last_run(self) -> dict | None:
        j = execute.last_applied(self._require())
        if not j:
            return None
        return {"id": j["id"], "status": j["status"], "created": j["created"][:16].replace("T", " "),
                "moved": sum(m["status"] == "moved" for m in j["moves"])}

    def start_apply(self, backup_dest: str | None = None, relink_ok: bool = False) -> dict:
        p = self._require()
        st = self._structure()
        execute.check_allowed(p)
        if execute.plan(p, st).edited and not relink_ok:
            raise RuntimeError("this event already has Premiere files that use these clips: confirm relinking first")

        def work() -> dict:
            pl = execute.plan(p, st)
            if not pl.ok:
                raise RuntimeError("; ".join(pl.conflicts[:3]))
            result = {}
            if backup_dest:
                result["backup"] = execute.backup(p, Path(backup_dest), progress=self._progress)
            j = execute.apply(p, st, pl, config.load_preset(p.event_type), progress=self._progress,
                              extras=index.generated_files)
            result.update(moved=sum(m["status"] == "moved" for m in j["moves"]), files=len(j["files_created"]),
                          journal=j["id"], last=self._last_run())
            return result

        return self._start("apply", work)

    def start_undo(self) -> dict:
        p = self._require()
        if not execute.last_applied(p):
            raise RuntimeError("nothing to undo")

        def work() -> dict:
            j = execute.undo(p, progress=self._progress)
            return {"status": j["status"], "back": sum(m["status"] == "undone" for m in j["moves"]),
                    "problems": j.get("problems", [])}

        return self._start("undo", work)



def _osascript_folder() -> str | None:
    """Folder chooser when the UI runs in a normal browser (development)."""
    r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Event folder")'],
                       capture_output=True, text=True)
    return r.stdout.strip().rstrip("/") or None if r.returncode == 0 else None
