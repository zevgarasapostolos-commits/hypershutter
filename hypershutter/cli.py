"""Command line entry point. The GUI calls the same core functions."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

from hypershutter import __version__
from hypershutter.core import checks, config, cost, frames, scan, sheets, sync
from hypershutter.core.media import fmt_duration, fmt_offset
from hypershutter.core.project import Project

# Subcommands still to be built, with the milestone that delivers them.
PLANNED: dict[str, str] = {}


def cmd_doctor(_args) -> int:
    ok = True
    for name in ("ffmpeg", "ffprobe"):
        st = config.check_tool(name)
        if st.ok:
            print(f"  ok   {name:8} {st.version}  ({st.path})")
        else:
            ok = False
            print(f"  MISSING {name}: install with `brew install ffmpeg`")
    drawtext = config.ffmpeg_has_filter("drawtext")
    print(f"  info ffmpeg drawtext filter: {'yes' if drawtext else 'no (labels drawn with Pillow)'}")
    print(f"  info state dir: {config.app_support_dir()}")
    return 0 if ok else 1


def _progress(stage: str, done: int, total: int) -> None:
    if done == total or done % 25 == 0:
        print(f"  {stage}: {done}/{total}", file=sys.stderr)


def _print_devices(p: Project) -> None:
    print(f"{'dev':5}{'kind':10}{'pattern':16}{'clips':>6}{'length':>10}  {'time source':14}{'clock offset':>14}  status")
    for d in sorted(p.devices.values(), key=lambda d: (d.kind != "camera", d.id)):
        cs = p.device_clips(d.id)
        total = sum(c.duration for c in cs)
        tl = sorted((t, t + timedelta(seconds=c.duration)) for c in cs if (t := p.corrected(c)))
        span = f"{tl[0][0]:%d/%m %H:%M}–{max(e for _, e in tl):%H:%M}" if tl else "?"
        off = fmt_offset(d.raw_offset) if d.source == "creation_time" or d.drift else "0"
        model = f" [{d.model}]" if d.model else ""
        print(f"{d.id:5}{d.kind:10}{d.pattern[:15]:16}{len(cs):>6}{fmt_duration(total):>10}  {d.source:14}"
              f"{off:>14}  {d.drift_status} {span}{model}")


def _load_or_scan(folder: Path, rescan: bool, workers: int) -> Project:
    p = None if rescan else Project.load(folder)
    if p is None:
        print(f"scanning {folder} (read-only) …", file=sys.stderr)
        p = scan.scan(folder, workers=workers, progress=_progress)
        summary = checks.run_checks(folder, list(p.clips.values()))
        p.save()
        _print_checks(p, summary)
    return p


def _print_checks(p: Project, summary: dict) -> None:
    print(f"checks: {len(summary['corrupt'])} corrupt/unreadable, {len(summary['duplicates'])} duplicate groups, "
          f"{len(p.orphans)} orphan sidecars (nothing was changed)")
    for cid, reason in summary["corrupt"].items():
        print(f"  corrupt  {p.clips[cid].rel}: {reason}")
    for g in summary["duplicates"]:
        print("  duplicate " + " = ".join(p.clips[c].rel for c in g))
    for o in p.orphans[:20]:
        print(f"  orphan   {o}")


def cmd_scan(args) -> int:
    folder = Path(args.folder).expanduser()
    p = _load_or_scan(folder, rescan=True, workers=args.workers)
    kinds = {k: sum(c.kind == k for c in p.clips.values()) for k in ("video", "audio")}
    print(f"\n{p.name}: {kinds['video']} video + {kinds['audio']} audio clips, "
          f"{sum(len(c.sidecars) for c in p.clips.values())} sidecars, {len(p.ignored)} ignored entries")
    _print_devices(p)
    if args.json:
        Path(args.json).write_text(json.dumps(p.to_json(), ensure_ascii=False, indent=1))
    return 0


def cmd_sync(args) -> int:
    folder = Path(args.folder).expanduser()
    p = _load_or_scan(folder, rescan=args.rescan, workers=args.workers)
    for spec in args.set or []:
        dev, _, value = spec.partition("=")
        d = sync.set_manual(p, dev.strip(), sync.parse_offset(value))
        print(f"manual: {d.id} {fmt_offset(d.raw_offset)} vs its clock")
    if not args.manual_only:
        report = sync.auto_sync(p, folder, log=lambda s: print("  " + s, file=sys.stderr))
        print(f"anchor (trusted clock): {report['anchor']}")
    p.save()
    print()
    _print_devices(p)
    for d in p.devices.values():
        for e in d.evidence[:3]:
            n, h = p.clips[e["needle"]], p.clips[e["hay"]]
            inside = 0 <= e["at"] <= h.duration
            print(f"  evidence {d.id}: {e['needle']} {'falls inside' if inside else 'aligns with'} {e['hay']} "
                  f"at {fmt_duration(max(e['at'], 0))} (peak {e['psr']})")
    unresolved = [d.id for d in p.devices.values() if d.drift_status == "unresolved"]
    if unresolved:
        print(f"\nunresolved clocks: {', '.join(unresolved)} — set with --set DEV=+HH:MM")
    return 0


def cmd_frames(args) -> int:
    import shutil
    import time

    folder = Path(args.folder).expanduser()
    p = _load_or_scan(folder, rescan=False, workers=6)
    if not p.synced_at:
        print("note: clocks not synced yet (run `sync`); sheet times use the uncorrected clocks", file=sys.stderr)
    wanted = set(args.clips.split(",")) if args.clips else None
    clips = [c for c in p.clips.values() if wanted is None or c.id in wanted]
    fs = frames.FrameSettings(interval=args.interval, workers=args.workers)
    t0 = time.time()
    got = frames.extract_all(folder, clips, fs, progress=_progress)
    t1 = time.time()
    n_sheets = 0
    for cid, fr in got.items():
        paths = sheets.clip_sheets(p.clips[cid], fr, p.corrected(p.clips[cid]), fs)
        n_sheets += len(paths)
        if args.sample_out:
            out = Path(args.sample_out).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            for k, sp in enumerate(paths):
                shutil.copy(sp, out / f"{cid}_{k + 1:02d}.jpg")
    t2 = time.time()
    n_frames = sum(len(f) for f in got.values())
    n_scene = sum(x.scene for f in got.values() for x in f)
    footage = sum(p.clips[c].duration for c in got)
    print(f"\n{len(got)} clips, {fmt_duration(footage)} of footage → {n_frames} frames "
          f"({n_scene} at scene changes), {n_sheets} sheets")
    print(f"time: frames {t1 - t0:.0f}s, sheets {t2 - t1:.0f}s (cached clips are instant)")
    print("\nestimated cost of both AI passes for every clip (described clips are free on re-runs):")
    for model, info in cost.MODELS.items():
        e = cost.estimate([len(f) for f in got.values()], model)
        print(f"  {info['label']:26} ~{e.input_tokens / 1e6:.2f}M in + {e.output_tokens / 1e3:.0f}K out tokens"
              f" ≈ ${e.cost_usd:.2f}, ~{e.minutes:.0f} min")
    return 0


def _confirm(args):
    def ask(e: cost.Estimate) -> bool:
        print(f"\nAbout to describe {e.clips} clips ({e.sheets} sheets, {e.frames} frames; {e.cached} already "
              f"described) and build the structure with {e.model}: "
              f"~{e.input_tokens / 1e6:.2f}M input + {e.output_tokens / 1e3:.0f}K output tokens ≈ ${e.cost_usd:.2f}, "
              f"~{e.minutes:.0f} min.")
        if args.yes:
            return True
        return input("Continue? [y/N] ").strip().lower() in ("y", "yes", "ν", "ναι")
    return ask


def _options(args) -> "pipeline.AnalyzeOptions":
    from hypershutter.core import pipeline
    return pipeline.AnalyzeOptions(event_type=args.type, model=args.model, effort_describe=args.effort_describe,
                                   effort_structure=args.effort_structure, interval=args.interval,
                                   offline=getattr(args, "offline", False),
                                   signals=tuple(s.strip() for s in args.signals.split(",") if s.strip()),
                                   speech=not args.no_speech, elsewhere=tuple(args.elsewhere))


def structure_signals() -> tuple[str, ...]:
    from hypershutter.core.structure import SIGNALS
    return SIGNALS


def cmd_ablation(args) -> int:
    from hypershutter.core import ablation
    folder = Path(args.folder).expanduser()
    p = _synced(folder)
    base = _options(args)
    log = lambda s: print(s, flush=True)
    stem = p.name.strip().replace(" ", "_")
    if args.density:
        r = ablation.density_study(p, base, tuple(float(x) for x in args.density.split(",")), reps=args.reps,
                                   size=args.subset, log=log)
        print(f"saved: {ablation.save(r, stem + '-density')}")
        for iv, x in r["intervals"].items():
            print(f"\n1 frame / {iv} s ({x['frames']} frames):\n" + ablation.table_md(x))
        return 0
    names = [n.strip() for n in args.conditions.split(";")] if args.conditions else list(ablation.CONDITIONS)
    unknown = [n for n in names if n not in ablation.CONDITIONS]
    if unknown:
        print(f"unknown conditions: {unknown}; known: {list(ablation.CONDITIONS)}")
        return 2
    r = ablation.run_conditions(p, base, names, reps=args.reps, workers=args.workers, log=log)
    print(f"saved: {ablation.save(r, stem)}\n")
    print(ablation.table_md(r))
    return 0


def _synced(folder: Path, workers: int = 6) -> Project:
    p = _load_or_scan(folder, rescan=False, workers=workers)
    if not p.synced_at:
        sync.auto_sync(p, folder, log=lambda s: print("  " + s, file=sys.stderr))
        p.save()
    return p


def _print_structure(st) -> None:
    print(f"\n{len(st.categories)} folders ({st.source}), {len(st.needs_review)} clips need review")
    for c in sorted(st.categories, key=lambda c: (c.number, c.sub)):
        print(f"  {c.folder:48} {len(c.clips):4} clips  {c.description_el[:70]}")
    if st.notes:
        print(f"\nnotes: {st.notes[:600]}")


def cmd_structure(args) -> int:
    from hypershutter.core import pipeline
    folder = Path(args.folder).expanduser()
    p = _synced(folder)
    res = pipeline.analyze(p, _options(args), _confirm(args), progress=_progress)
    if res is None:
        print("cancelled")
        return 1
    _print_structure(res.structure)
    if res.usage:
        print(f"\ncost ≈ ${res.cost():.2f}, {res.usage.calls} describe calls, {res.usage.refusals} refusals")
    return 0


def cmd_eval(args) -> int:
    from hypershutter.core import evaluate
    folder = Path(args.folder).expanduser()
    p = _synced(folder)
    try:
        r = evaluate.run(p, _options(args), Path(args.index).expanduser() if args.index else None,
                         _confirm(args), progress=_progress)
    except RuntimeError as e:
        print(f"not evaluating: {e}")
        return 1
    if r is None:
        print("cancelled")
        return 1
    _print_structure(r["structure"])
    m = r["metrics"]
    pw = m["pairwise"]
    print(f"\nmatched accuracy {m['matched_accuracy']:.1%} · pairwise F1 {pw['f1']:.3f} · ARI {m['ari']:.3f} · "
          f"folders {m['folders_pred']} vs {m['folders_truth']} · boundaries F1 {m['boundaries']['f1']:.3f}")
    print(f"report: {r['md']}")
    return 0


def _reviewed(folder: Path):
    from hypershutter.core import review
    p = Project.load(folder)
    st = review.load(p) if p else None
    if st is None:
        print("no structure for this folder yet: run `structure` (or analyze in the app) first", file=sys.stderr)
    return p, st


def cmd_apply(args) -> int:
    from hypershutter.core import execute, index
    folder = Path(args.folder).expanduser()
    p, st = _reviewed(folder)
    if st is None:
        return 1
    try:
        execute.check_allowed(p, args.force)
    except PermissionError as e:
        print(f"refused: {e}")
        return 1
    pl = execute.plan(p, st, args.rename)
    by_folder: dict[str, int] = {}
    for m in pl.moves:
        if m.kind == "clip":
            by_folder[m.dst.split("/", 1)[0]] = by_folder.get(m.dst.split("/", 1)[0], 0) + 1
    print(f"{p.name}: {len(pl.moves)} files to move ({sum(m.kind == 'sidecar' for m in pl.moves)} sidecars), "
          f"{len(pl.folders)} new folders, {pl.in_place} already in place, {len(pl.unassigned)} stay where they are")
    for name, n in sorted(by_folder.items()):
        print(f"  {name:50} {n:4} clips")
    for c in pl.conflicts:
        print(f"  conflict: {c}")
    if pl.edited:
        print(f"  edited already: {', '.join(pl.edited)} use these clips; after the move relink in Premiere "
              "(Link Media → Locate → the event folder, Search subfolders + Relink others automatically)")
    if not pl.ok:
        return 1
    mirrors = [Path(m).expanduser() for m in args.mirror] if args.mirror else (None if not args.no_mirrors else [])
    others = execute.copies(p) if mirrors is None else mirrors
    if others:
        print(f"  the same organization on {len(others)} more copies: " + ", ".join(str(o) for o in others))
    if args.apply and pl.edited and not args.relink:
        print("refused: add --relink to confirm you will relink those Premiere files after the move")
        return 1
    if not args.apply:
        print("\ndry run: nothing moved. Add --apply to move the files (undo with `hypershutter undo`).")
        return 0
    preset = config.load_preset(p.event_type)
    if args.backup:
        r = execute.backup(p, Path(args.backup), progress=_progress)
        print(f"backup: {r['verified']} files verified in {r['dest']} ({r['copied']} copied)")
    r = execute.apply_everywhere(p, st, preset, mirrors=mirrors, rename=args.rename, progress=_progress,
                                 extras=index.generated_files, force=args.force)
    for c in r["copies"]:
        print(f"{c['root']}: moved {c['moved']} files ({c['status']}), journal {c['journal']}")
    return 0


def cmd_undo(args) -> int:
    from hypershutter.core import execute
    folder = Path(args.folder).expanduser()
    p = Project.load(folder)
    j = execute.last_applied(p) if p else None
    if j is None:
        print("nothing to undo")
        return 1
    print(f"last run {j['id']} ({j['status']}): {sum(m['status'] == 'moved' for m in j['moves'])} files moved")
    if not args.yes and input("Move every file back? [y/N] ").strip().lower() not in ("y", "yes", "ν", "ναι"):
        print("cancelled")
        return 1
    u = execute.undo_everywhere(p, None if not args.no_mirrors else [], progress=_progress)
    for c in u["copies"]:
        print(f"{c['root']}: {c['status']}")
        for prob in c["problems"]:
            print(f"  problem: {prob}")
    return 0 if all(c["status"] == "undone" for c in u["copies"]) else 1


def cmd_ingest(args) -> int:
    from hypershutter.core import cards, ingest
    if args.list or not args.card:
        found = cards.detect()
        if not found:
            print("no cards found under /Volumes")
        for c in found:
            print(f"{c.path}  {c.kind:10s} {len(c.media):4d} clips  {c.bytes / 1e9:7.2f} GB  "
                  f"{c.camera or c.identity}" + (f"  label: {c.label}" if c.label else ""))
        return 0
    card = cards.read_card(Path(args.card).expanduser())
    label = args.label or card.label
    if not label:
        print("give the source a label once, e.g. --label 'cam apos' (it is remembered for this camera)")
        return 2
    if not args.project or not args.dest:
        print("choose --project and at least one --dest")
        return 2
    dests = [Path(d).expanduser() for d in args.dest]
    jobs = ingest.plan(card, label)
    print(f"{card.kind} card {card.name} ({card.camera or card.identity}): {len(jobs)} files, "
          f"{card.bytes / 1e9:.2f} GB -> '{args.project}/{label}/' on {len(dests)} drive(s)")
    problems = ingest.preflight(card, jobs, dests, args.project, args.proxy)
    for pr in problems:
        print(f"  blocked: {pr}")
    if problems or args.dry_run:
        return 1 if problems else 0
    last = [0.0]

    def show(ev: dict) -> None:
        if ev["phase"] != "done" and time.time() - last[0] < 2:
            return
        last[0] = time.time()
        parts = " | ".join(f"{Path(d['root']).parent.name}: {d['written'] / 1e9:.2f}/{d['total'] / 1e9:.2f} GB "
                           f"{d['mb_s']} MB/s" + (f" ETA {d['eta_s']}s" if d.get("eta_s") else "") for d in ev["dests"])
        print(f"  {ev['phase']} {ev['done']}/{ev['total']}  {parts}", flush=True)

    q = None
    if args.proxy != "none" and not args.no_proxies:
        from hypershutter.core import proxies
        q = proxies.queue()
        q.start()                                   # background priority, while the card copies
        print(f"  proxies ({args.proxy}) start as soon as each clip is verified on {dests[0]}")
    on_verified = (lambda root, rel: proxies.enqueue(q, root, [rel], args.proxy)) if q else None
    r = ingest.ingest(card, args.project, label, dests, args.proxy, progress=show, on_verified=on_verified)
    for d in r.dests:
        print(f"  {d['root']}: {d['verified']}/{r.files} verified, write {d['write_mb_s']} MB/s, "
              f"verify {d['verify_mb_s']} MB/s, MHL {Path(d['mhl']).name}")
    for f in r.failed:
        print(f"  FAILED {f['dest']}: {f['file']} ({f['why']})")
    print("SAFE TO FORMAT: every file is verified on every drive" if r.safe_to_format
          else "NOT safe to format: keep the card and check the failed files")
    if q:
        print("  finishing proxies (Ctrl+C stops; they resume next time) …", flush=True)
        q.wait("proxy")
        q.stop()
        c = q.counts("proxy")
        print(f"  proxies: {c.get('done', 0)} done, {c.get('failed', 0)} failed")
    return 0 if r.safe_to_format else 1


def cmd_proxies(args) -> int:
    from hypershutter.core import jobs, proxies
    q = proxies.queue(workers=args.workers)
    if args.status or not args.folder:
        for kind in ("proxy",):
            print(kind, q.counts(kind))
        for j in [j for j in jobs.read_all() if j.status == jobs.FAILED][-10:]:
            print(f"  failed: {j.rel} ({j.error[:120]})")
        return 0
    folder = Path(args.folder).expanduser()
    p = _load_or_scan(folder, rescan=False, workers=6)
    rels = [c.rel for c in p.clips.values() if c.kind == "video"]
    n = proxies.enqueue(q, folder, rels, args.preset)
    print(f"{n} proxies queued ({args.preset}) -> {folder / proxies.PROXY_DIR}")
    if args.queue_only:
        return 0
    t0 = time.time()
    done = [0]
    total = q.counts("proxy").get("queued", 0)

    def run_all():
        while (job := q._next()) is not None:
            q.run_one(job)
            done[0] += 1
            print(f"  {done[0]}/{total} {job.rel}  ({time.time() - t0:.0f} s)", flush=True)

    run_all()
    c = q.counts("proxy")
    print(f"proxies: {c.get('done', 0)} done, {c.get('failed', 0)} failed")
    return 0


def cmd_export(args) -> int:
    from hypershutter.core import execute, export, review
    if args.list_presets or not args.folder:
        for k, pr in export.presets().items():
            print(f"{k:20s} {pr['name']}  (~{pr.get('mbps', 0)} Mb/s, .{pr['extension']})")
        return 0
    folder = Path(args.folder).expanduser()
    p = Project.load(folder)
    if p is None:
        print("scan this event first")
        return 1
    st = review.load(p)
    if args.dest is None:
        try:
            execute.check_allowed(p, force=True)
        except PermissionError:
            print("this is a read-only reference project: choose --dest outside it")
            return 1
    items = export.plan(p, st, args.preset, Path(args.dest).expanduser() if args.dest else None,
                        clips=args.clips.split(",") if args.clips else None,
                        folders=args.folders.split(",") if args.folders else None)
    gb = export.estimate_bytes(items, args.preset) / 1e9
    print(f"{len(items)} clips -> {items[0].out.parents[1] if items else '-'} ({args.preset}, about {gb:.1f} GB)")
    problems = export.check(items, args.preset)
    for pr in problems:
        print(f"  blocked: {pr}")
    if problems or args.dry_run:
        return 1 if problems else 0
    q = export.queue(workers=args.workers)
    n = export.enqueue(q, p, items, args.preset)
    print(f"{n} exports queued")
    if args.queue_only:
        return 0
    t0 = time.time()
    k = 0
    while (job := q._next()) is not None:
        q.run_one(job)
        k += 1
        print(f"  {k}/{n} {job.rel}  ({time.time() - t0:.0f} s)", flush=True)
    print(f"exports: {q.counts('export')}")
    return 0


def cmd_drives(args) -> int:
    from hypershutter.core import drives
    for d in drives.drives():
        flag = {"ok": "  ", "warn": "! ", "critical": "!!"}[d.status]
        print(f"{flag}{d.name:16s} {d.total / 1e9:7.0f} GB  used {d.used / 1e9:7.0f}  free {d.free / 1e9:7.1f} GB"
              + (f"  (after queued work {d.free_after / 1e9:.1f} GB)" if d.planned else "")
              + ("  [card]" if d.is_card else "") + (f"  {d.message}" if d.message else ""))
        for pu in d.projects:
            print(f"      {pu.name}: footage {pu.footage_bytes / 1e9:.1f} GB, proxies {pu.proxies_bytes / 1e9:.1f} GB")
    return 0


def cmd_key(args) -> int:
    import getpass

    from hypershutter.core import credentials

    if args.action == "set":
        key = getpass.getpass("Anthropic API key (input hidden): ").strip()
        if not key.startswith("sk-ant-"):
            print("That does not look like an Anthropic API key (sk-ant-…); nothing saved.")
            return 1
        credentials.set_api_key(key)
        print(f"saved to the macOS Keychain: {credentials.masked()}")
    elif args.action == "delete":
        credentials.delete_api_key()
        print("removed from the Keychain")
    else:
        print(f"API key: {credentials.masked()}")
    return 0


def cmd_app(args) -> int:
    from hypershutter.app.main import run
    run(browser=args.browser, port=args.port, debug=args.debug)
    return 0


def cmd_timeline(args) -> int:
    folder = Path(args.folder).expanduser()
    p = _load_or_scan(folder, rescan=False, workers=6)
    for t, c in p.timeline()[: args.limit or None]:
        end = t + timedelta(seconds=c.duration)
        flag = f"  [{'; '.join(c.flags)}]" if c.flags else ""
        print(f"{t:%H:%M:%S}–{end:%H:%M:%S}  {c.device:4} {c.id:34} {fmt_duration(c.duration):>8}  {c.rel}{flag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hypershutter", description="Organize event footage.")
    p.add_argument("--version", action="version", version=f"hypershutter {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check ffmpeg/ffprobe and paths").set_defaults(func=cmd_doctor)

    sp = sub.add_parser("scan", help="read an event folder: clips, sidecars, devices, checks (read-only)")
    sp.add_argument("folder"); sp.add_argument("--workers", type=int, default=6); sp.add_argument("--json")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("sync", help="measure per-device clock offsets from shared audio")
    sp.add_argument("folder"); sp.add_argument("--workers", type=int, default=6)
    sp.add_argument("--rescan", action="store_true", help="re-read the folder first")
    sp.add_argument("--set", action="append", metavar="DEV=+HH:MM", help="manual offset vs the device clock")
    sp.add_argument("--manual-only", action="store_true", help="only apply --set, skip audio matching")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("frames", help="extract frames and build contact sheets (cached)")
    sp.add_argument("folder"); sp.add_argument("--interval", type=float, default=2.0, help="seconds per frame")
    sp.add_argument("--clips", help="comma-separated clip ids (default: all)")
    sp.add_argument("--workers", type=int, default=6)
    sp.add_argument("--sample-out", help="also copy the sheets of these clips to a folder")
    sp.set_defaults(func=cmd_frames)

    def analysis_args(sp):
        sp.add_argument("folder")
        sp.add_argument("--type", default="baptism", choices=["baptism", "wedding", "event"])
        sp.add_argument("--model", default=cost.DEFAULT_MODEL, choices=list(cost.MODELS))
        sp.add_argument("--effort-describe", default="low", choices=["low", "medium", "high"])
        sp.add_argument("--effort-structure", default="high", choices=["low", "medium", "high", "xhigh", "max"])
        sp.add_argument("--interval", type=float, default=2.0)
        sp.add_argument("--offline", action="store_true", help="no API: time-gap (+ sound) segmentation")
        sp.add_argument("--yes", action="store_true", help="skip the cost confirmation")
        sp.add_argument("--signals", default=",".join(structure_signals()),
                        help="what the sorting may use, comma separated: time,camera,image,audio")
        sp.add_argument("--no-speech", action="store_true", help="skip Whisper cue words")
        sp.add_argument("--elsewhere", action="append", default=[], metavar="DIR",
                        help="a folder that holds clips moved off the event folder (read-only)")

    sp = sub.add_parser("structure", help="describe every clip and build the event's folder structure (dry run)")
    analysis_args(sp)
    sp.set_defaults(func=cmd_structure)

    sp = sub.add_parser("eval", help="accuracy against an organized event (read-only); report in reports/")
    analysis_args(sp)
    sp.add_argument("--index", help="use this shot index as ground truth instead of the folders")
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("ablation", help="ablation study: sorting accuracy per signal (read-only); JSON in reports/ablation/")
    analysis_args(sp)
    sp.add_argument("--reps", type=int, default=3, help="repeats per condition (pass 2 is not deterministic)")
    sp.add_argument("--conditions", help="';'-separated condition names (default: all)")
    sp.add_argument("--workers", type=int, default=4)
    sp.add_argument("--density", help="frame-density comparison instead, e.g. 4,2,1 (seconds per frame)")
    sp.add_argument("--subset", type=int, default=120, help="clips in the density subset")
    sp.set_defaults(func=cmd_ablation)

    sp = sub.add_parser("ingest", help="copy a card to several drives at once, verified by checksum (the card is only read)")
    sp.add_argument("card", nargs="?", help="the card (a mounted volume) or a folder copied from one")
    sp.add_argument("--list", action="store_true", help="list the cards found under /Volumes")
    sp.add_argument("--project", help="event folder name on the destination drives, e.g. '074 Γ15-11-2026'")
    sp.add_argument("--label", help="source label, e.g. 'cam apos' (remembered per camera)")
    sp.add_argument("--dest", action="append", default=[], help="a destination drive or folder (repeat for several)")
    sp.add_argument("--proxy", default="prores_proxy", choices=["prores_proxy", "h264", "none"],
                    help="proxy preset, for the space check")
    sp.add_argument("--dry-run", action="store_true", help="only show the plan and the space check")
    sp.add_argument("--no-proxies", action="store_true", help="do not make proxies after the copy")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("proxies", help="make proxies for an event's clips in the background queue (ProRes Proxy)")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--preset", default="prores_proxy", choices=["prores_proxy", "h264"])
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--status", action="store_true", help="show the queue")
    sp.add_argument("--queue-only", action="store_true", help="queue them for the app, do not run now")
    sp.set_defaults(func=cmd_proxies)

    sp = sub.add_parser("export", help="batch export (per-clip transcodes with a preset; no editing)")
    sp.add_argument("folder", nargs="?")
    sp.add_argument("--preset", default="h264_1080_review")
    sp.add_argument("--dest", help="output folder (default: <event>/Exports)")
    sp.add_argument("--folders", help="category numbers or keys, e.g. 05,08a (default: everything)")
    sp.add_argument("--clips", help="clip ids, comma separated")
    sp.add_argument("--workers", type=int, default=1)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--queue-only", action="store_true", help="queue them for the app, do not run now")
    sp.add_argument("--list-presets", action="store_true")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("drives", help="connected drives: space, projects, proxies, warnings")
    sp.set_defaults(func=cmd_drives)

    sp = sub.add_parser("key", help="store the Anthropic API key in the macOS Keychain")
    sp.add_argument("action", choices=["set", "status", "delete"], nargs="?", default="status")
    sp.set_defaults(func=cmd_key)

    sp = sub.add_parser("apply", help="move clips into the reviewed folders (dry run unless --apply)")
    sp.add_argument("folder")
    sp.add_argument("--apply", action="store_true", help="really move the files (journaled, undoable)")
    sp.add_argument("--backup", metavar="DIR", help="copy and verify every file to DIR first")
    sp.add_argument("--rename", metavar="PATTERN", help="rename files, e.g. '{num}_{n:03d}_{name}' (off by default)")
    sp.add_argument("--force", action="store_true", help="allow an event that looks organized by hand")
    sp.add_argument("--relink", action="store_true", help="the event has Premiere files: I will relink after the move")
    sp.add_argument("--mirror", action="append", default=[], metavar="DIR",
                    help="another drive's copy of this event (default: the copies ingest made)")
    sp.add_argument("--no-mirrors", action="store_true", help="organize only this copy")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("undo", help="move every file of the last apply back to where it was")
    sp.add_argument("folder"); sp.add_argument("--yes", action="store_true")
    sp.add_argument("--no-mirrors", action="store_true", help="undo only this copy")
    sp.set_defaults(func=cmd_undo)

    sp = sub.add_parser("app", help="open the HyperShutter window (Home, Scan & Analyze, Review)")
    sp.add_argument("--browser", action="store_true", help="no window: print a local URL for a browser (development)")
    sp.add_argument("--port", type=int, default=0)
    sp.add_argument("--debug", action="store_true", help="enable the web inspector")
    sp.set_defaults(func=cmd_app)

    sp = sub.add_parser("timeline", help="print every clip on the corrected timeline")
    sp.add_argument("folder"); sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_timeline)

    for name, milestone in PLANNED.items():
        sp = sub.add_parser(name, help=f"(not built yet, {milestone})")
        sp.set_defaults(func=lambda _a, n=name, m=milestone: print(f"`{n}` arrives in {m}.") or 2)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
