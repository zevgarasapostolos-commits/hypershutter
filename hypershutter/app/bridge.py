"""The app's API: every screen calls these methods (as JSON over the local server).

Long work (scan, sync, frames, the AI passes) runs as one background job at a time; the UI
polls `poll()` for progress events. Nothing here moves or writes footage: Review edits are
saved to Application Support; files move only through Apply (with its journal and Undo).
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Callable

from hypershutter import __version__
from hypershutter.core import (cards, checks, config, cost, credentials, describe, drives, evaluate, execute, export, forget,
                               frames, index, ingest, jobs, pipeline, proxies, review, scan, settings, store, sync)
from hypershutter.core.media import fmt_duration, fmt_offset
from hypershutter.core.project import Project
from hypershutter.core.structure import Structure

EVENT_TYPES = ("baptism", "wedding", "event")
SCRUB_FRAMES = 16                      # frames per clip sent to the Review grid for hover scrubbing
STAGE = {"probe": "scan", "frames": "frames", "scene": "frames", "audio": "audio", "speech": "audio",
         "describe": "describe", "structure": "structure",
         "backup": "backup", "move": "move", "undo": "undo"}


def public_error(e: Exception) -> str:
    """What the app shows for a failed task: a locale key or plain text. The interface never names
    the service behind the sorting."""
    if isinstance(e, credentials.NotSetUp):
        return "err.not_set_up"
    text = str(e).lower()
    if type(e).__module__.startswith("anthropic") or "anthropic" in text or "claude" in text:
        if "credit" in text or "billing" in text:
            return "err.no_credit"
        if "connection" in text or "timeout" in text or "timed out" in text:
            return "err.unreachable"
        return "err.service"
    return str(e)


class Bridge:
    def __init__(self, media_url: Callable[[str], str], pick_folder: Callable[[], str | None] | None = None,
                 start_queue: bool = True):
        self._media_url = media_url
        self._pick = pick_folder or _osascript_folder
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._job: dict | None = None
        self._p: Project | None = None
        self._by_clip: dict[str, list[frames.Frame]] | None = None
        self._audio: dict[str, dict] | None = None
        self._ingest: dict | None = None            # the ingest runs beside the analysis jobs
        self._queue = jobs.JobQueue({"proxy": proxies.runner, "export": export.runner}, workers=1)
        if start_queue:
            self._queue.start()
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
                message = public_error(e)
                with self._lock:
                    self._job.update(status="error", error=message)
                self._emit(type="job_error", name=name, error=message)

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
        s = settings.load()
        return {"version": __version__, "event_types": list(EVENT_TYPES),
                "ffmpeg": bool(config.find_tool("ffmpeg")),
                "onboarded": s["onboarded"], "language": s["language"]}       # the Keychain is read only where the key is needed

    def recent(self) -> list[dict]:
        out = []
        for r in store.recent_projects():
            now = store.locate(r["root"])
            out.append({**r, "root": now or r["root"], "available": now is not None})
        return out

    def project_data_size(self, path: str) -> dict:
        return {"bytes": forget.size(Path(path))}

    def remove_project(self, path: str, delete_data: bool = False) -> dict:
        """Off the list, and optionally the analysis data too. Nothing on any drive changes."""
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise RuntimeError("another task is still running")
        root = Path(path)
        if self._p is not None and store.project_id(Path(self._p.root)) == store.project_id(root):
            self._p, self._by_clip, self._audio, self._st = None, None, None, None
        freed = 0
        if delete_data:
            freed = forget.forget(root)
        else:
            store.hide_project(root)
        return {"freed": freed, "recent": self.recent()}

    def pick_folder(self) -> str | None:
        return self._pick()

    def open_project(self, path: str) -> dict:
        root = Path(path).expanduser()
        if not root.is_dir():
            raise ValueError("not a folder")
        p = Project.load(root)
        store.show_project(root)                        # opened again: back on the list
        self._p, self._by_clip, self._audio, self._st = p, None, None, None
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
            self._progress("audio", 0, 1)
            self._audio = pipeline.prepare_audio(p, self._options(), list(self._by_clip), self._progress)
            self._progress("audio", 1, 1)
            return self.scan_summary()

        return self._start("scan", work)

    def _options(self, offline: bool = False) -> pipeline.AnalyzeOptions:
        p = self._require()
        s = settings.load()
        signals = ("time", "camera", "image", "audio") if s["use_sound"] else ("time", "camera", "image")
        return pipeline.AnalyzeOptions(event_type=p.event_type, model=cost.DEFAULT_MODEL,
                                       offline=offline, schedule=p.schedule, interval=float(s["frame_interval"]),
                                       signals=signals)

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
                e = pipeline.estimate(p, self._by_clip, model, audio=self._audio)
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

    def start_analyze(self, offline: bool = False) -> dict:
        p = self._require()
        if self._by_clip is None:
            raise RuntimeError("scan first")
        opts = self._options(offline)

        def work() -> dict:
            res = pipeline.run(p, opts, self._by_clip, self._progress, audio=self._audio)
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
                "copies": [str(c) for c in execute.copies(p)],
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
            r = execute.apply_everywhere(p, st, config.load_preset(p.event_type), progress=self._progress,
                                         extras=index.generated_files)
            main = r["copies"][0]
            result.update(moved=main["moved"], journal=main["journal"], copies=r["copies"], last=self._last_run())
            return result

        return self._start("apply", work)

    def start_undo(self) -> dict:
        p = self._require()
        if not execute.last_applied(p):
            raise RuntimeError("nothing to undo")

        def work() -> dict:
            u = execute.undo_everywhere(p, progress=self._progress)
            main = u["copies"][0] if u["copies"] else {"status": "undone", "problems": [], "back": 0}
            return {"status": main["status"], "back": main["back"], "copies": u["copies"],
                    "problems": [x for c in u["copies"] for x in c["problems"]]}

        return self._start("undo", work)



    # ---------- Ingest ----------

    def cards(self) -> list[dict]:
        out = []
        for c in cards.detect():
            out.append({"path": c.path, "name": c.name, "kind": c.kind, "camera": c.camera, "identity": c.identity,
                        "label": c.label, "clips": len(c.media), "files": len(c.files), "gb": round(c.bytes / 1e9, 2)})
        return out

    def pick_dest(self) -> str | None:
        return self._pick()

    def read_folder_as_card(self, path: str) -> dict:
        c = cards.read_card(Path(path).expanduser())
        return {"path": c.path, "name": c.name, "kind": c.kind, "camera": c.camera, "identity": c.identity,
                "label": c.label, "clips": len(c.media), "files": len(c.files), "gb": round(c.bytes / 1e9, 2)}

    def ingest_preflight(self, card: str, project: str, label: str, dests: list[str]) -> dict:
        c = cards.read_card(Path(card))
        jobs_ = ingest.plan(c, label or "card")
        s = settings.load()
        proxy = s["proxy_preset"] if s["make_proxies"] else "none"
        detail = ingest.check(c, jobs_, [Path(d) for d in dests], project or "_", proxy)
        if not project:
            detail["problems"] = [p for p in detail["problems"] if p["code"] != "space"]
        return {"files": len(jobs_), "gb": round(c.bytes / 1e9, 2), **detail, "make_proxies": s["make_proxies"],
                "targets": [str(Path(d) / project / (label or "card")) for d in dests] if project else []}

    def eject_card(self, path: str) -> dict:
        """Eject the card from macOS once it is safe; never formats or writes to it."""
        st = self._ingest or {}
        rep = st.get("report") or {}
        if not rep.get("safe") or st.get("card_path") != path:
            raise RuntimeError("the card is not verified on every drive yet")
        r = subprocess.run(["diskutil", "eject", path], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "could not eject")
        return {"ejected": path}

    def start_ingest(self, card: str, project: str, label: str, dests: list[str]) -> dict:
        if self._ingest and self._ingest.get("status") == "running":
            raise RuntimeError("an ingest is already running")
        s = settings.load()
        proxy = s["proxy_preset"] if s["make_proxies"] else "none"
        c = cards.read_card(Path(card))
        self._ingest = {"status": "running", "card": c.name, "card_path": c.path, "project": project, "label": label}

        def progress(ev: dict) -> None:
            self._emit(type="ingest", **ev)

        def on_verified(root: Path, rel: str) -> None:
            if proxy != "none":
                proxies.enqueue(self._queue, root, [rel], proxy)

        def run() -> None:
            proxies.INGESTING.set()
            try:
                r = ingest.ingest(c, project, label, [Path(d) for d in dests], proxy, progress=progress,
                                  on_verified=on_verified)
                self._ingest.update(status="done", report={"safe": r.safe_to_format, "files": r.files,
                                                           "copied": r.copied, "skipped": r.skipped,
                                                           "failed": r.failed, "dests": r.dests,
                                                           "seconds": r.seconds, "gb": round(r.bytes / 1e9, 2)})
                self._emit(type="ingest_done", report=self._ingest["report"], card_path=c.path)
            except Exception as e:
                traceback.print_exc()
                self._ingest.update(status="error", error=str(e))
                self._emit(type="ingest_error", error=str(e))
            finally:
                proxies.INGESTING.clear()

        threading.Thread(target=run, daemon=True).start()
        return {"started": True}

    def ingest_state(self) -> dict | None:
        return self._ingest

    def ingest_history(self) -> list[dict]:
        import json
        d = config.app_support_dir() / "ingest"
        out = []
        for f in sorted(d.glob("*.json"), reverse=True)[:20] if d.exists() else []:
            try:
                r = json.loads(f.read_text())
                out.append({"session": r["session"], "card": r["card"]["name"], "project": r["project"], "label": r["label"],
                            "files": r["files"], "gb": round(r["bytes"] / 1e9, 2), "safe": r["safe_to_format"]})
            except (OSError, KeyError, ValueError):
                continue
        return out

    # ---------- Drives ----------

    def drives(self) -> list[dict]:
        return [drives.as_dict(d) for d in drives.drives()]

    # ---------- Background jobs (proxies, exports) ----------

    def jobs_status(self) -> dict:
        all_ = jobs.read_all()
        running = [{"kind": j.kind, "rel": j.rel, "progress": j.progress, "out": j.out} for j in all_ if j.status == jobs.RUNNING]
        counts: dict[str, dict] = {}
        for j in all_:
            counts.setdefault(j.kind, {}).setdefault(j.status, 0)
            counts[j.kind][j.status] += 1
        recent = [{"id": j.id, "kind": j.kind, "rel": j.rel, "status": j.status, "progress": j.progress,
                   "error": j.error[:160], "out": j.out} for j in all_[-60:]]
        return {"counts": counts, "running": running, "paused": self._queue.paused, "recent": recent[::-1]}

    def jobs_pause(self) -> dict:
        self._queue.pause()
        return self.jobs_status()

    def jobs_resume(self) -> dict:
        self._queue.resume()
        return self.jobs_status()

    def jobs_retry(self) -> dict:
        self._queue.retry_failed()
        return self.jobs_status()

    def make_proxies(self) -> dict:
        p = self._require()
        n = proxies.enqueue(self._queue, Path(p.root), [c.rel for c in p.clips.values() if c.kind == "video"],
                            settings.load()["proxy_preset"])
        return {"queued": n}

    # ---------- Export ----------

    def export_presets(self) -> list[dict]:
        return [{"id": k, "name": v["name"], "mbps": v.get("mbps", 0), "ext": v["extension"]} for k, v in export.presets().items()]

    def _export_items(self, preset: str, folders: list[str] | None, dest: str | None):
        p = self._require()
        st = review.load(p)
        if not dest and execute.read_only_name(p):
            raise RuntimeError("read-only reference project: choose a destination outside it")
        return p, export.plan(p, st, preset, Path(dest) if dest else None, folders=folders or None)

    def export_plan(self, preset: str, folders: list[str] | None = None, dest: str | None = None) -> dict:
        p, items = self._export_items(preset, folders, dest)
        return {"clips": len(items), "gb": round(export.estimate_bytes(items, preset) / 1e9, 1),
                "problems": export.check(items, preset), "space": export.space(items, preset),
                "base": str(items[0].out.parents[1]) if items else "",
                "folders": [{"key": c.key, "folder": c.folder, "clips": len(c.clips)} for c in (review.load(p).categories if review.load(p) else [])]}

    def start_export(self, preset: str, folders: list[str] | None = None, dest: str | None = None) -> dict:
        p, items = self._export_items(preset, folders, dest)
        problems = export.check(items, preset)
        if problems:
            raise RuntimeError("; ".join(problems))
        return {"queued": export.enqueue(self._queue, p, items, preset)}

    # ---------- Accuracy Lab ----------

    def lab_reports(self) -> list[dict]:
        import json
        out = []
        for f in sorted(config.reports_dir().glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:40]:
            try:
                d = json.loads(f.read_text())
                m, r = d["metrics"], d["run"]
                out.append({"name": f.stem, "accuracy": m["matched_accuracy"], "f1": m["pairwise"]["f1"], "ari": m["ari"],
                            "folders": f"{m['folders_pred']}/{m['folders_truth']}", "cost": r.get("cost", 0),
                            "model": r.get("model", ""), "when": r.get("when", "")})
            except (OSError, KeyError, ValueError):
                continue
        return out

    def lab_report(self, name: str) -> str:
        f = config.reports_dir() / f"{Path(name).name}.md"
        return re.sub(r" · model .*$", "", f.read_text(), count=1, flags=re.M) if f.exists() else ""   # on screen: no model name

    def start_eval(self, offline: bool = False) -> dict:
        p = self._require()
        opts = self._options(offline=offline)

        def work() -> dict:
            r = evaluate.run(p, opts, progress=self._progress)
            m = r["metrics"]
            return {"name": r["stem"], "accuracy": m["matched_accuracy"], "f1": m["pairwise"]["f1"], "ari": m["ari"],
                    "cost": r["run"]["cost"]}

        return self._start("eval", work)

    # ---------- Settings, onboarding, help ----------

    def settings(self) -> dict:
        s = settings.load()
        return {**s, "proxy_presets": [{"id": k, "name": v["name"]} for k, v in proxies.presets().items()],
                "export_presets": self.export_presets(), "ffmpeg": bool(config.find_tool("ffmpeg"))}

    def save_settings(self, changes: dict) -> dict:
        settings.save(changes)
        return self.settings()

    def open_link(self, kind: str) -> dict:
        s = settings.load()
        if kind == "mail":
            from urllib.parse import quote
            body = quote(f"HyperShutter {__version__}\nmacOS\n\nWhat happened:\n")
            url = f"mailto:{s['support_email']}?subject={quote('HyperShutter support')}&body={body}"
        elif kind == "issues":
            url = s["issues_url"]
        else:
            raise ValueError(kind)
        subprocess.run(["open", url], check=False)
        return {"opened": url}

    def export_diagnostics(self) -> dict:
        """Settings, versions and logs only: never footage, frames, transcripts or the API key."""
        import json
        import platform
        import zipfile
        out = Path.home() / "Desktop" / f"HyperShutter diagnostics {time.strftime('%Y-%m-%d %H%M')}.zip"
        s = settings.load()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("about.json", json.dumps({"version": __version__, "macos": platform.mac_ver()[0],
                                                 "python": platform.python_version(),
                                                 "ffmpeg": config.find_tool("ffmpeg") or "missing"}, indent=1))
            z.writestr("settings.json", json.dumps(s, indent=1))
            z.writestr("jobs.json", json.dumps([{"kind": j.kind, "status": j.status, "error": j.error[:300]}
                                                for j in jobs.read_all()[-200:]], indent=1))
            log = config.app_support_dir() / "hypershutter.log"
            if log.exists():
                z.write(log, "hypershutter.log")
        return {"path": str(out)}


def _osascript_folder() -> str | None:
    """Folder chooser when the UI runs in a normal browser (development)."""
    r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Event folder")'],
                       capture_output=True, text=True)
    return r.stdout.strip().rstrip("/") or None if r.returncode == 0 else None
