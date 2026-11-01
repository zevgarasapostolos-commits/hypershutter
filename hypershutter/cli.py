"""Command line entry point. The GUI calls the same core functions."""

from __future__ import annotations

import argparse
import json
import sys
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
                                   offline=getattr(args, "offline", False))


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
    import time as _time
    from datetime import datetime as _dt

    from hypershutter.core import describe, evaluate, pipeline, structure
    folder = Path(args.folder).expanduser()
    p = _synced(folder)
    if args.index:
        truth = evaluate.truth_from_index(Path(args.index).expanduser())
        truth = {cid: truth[cid.split("~")[0]] for cid in p.clips if cid.split("~")[0] in truth}
    else:
        truth = evaluate.truth_from_folders({c.id: c.rel for c in p.clips.values() if c.kind == "video"})
    if not truth:
        print("no ground truth: the clips are not in category folders and no --index was given")
        return 1
    t0 = _time.time()
    res = pipeline.analyze(p, _options(args), _confirm(args), progress=_progress)
    if res is None:
        print("cancelled")
        return 1
    st = res.structure
    pred = {cid: st.folder_of(cid) for cid in st.assignment}
    order = [c.id for _, c in p.timeline() if c.id in pred]
    m = evaluate.metrics(truth, pred, order)
    for e in m["errors"]:
        e["desc"] = (res.descriptions.get(e["clip"]) or {}).get("description", "")[:140]
    clocks = ", ".join(f"{d.id} {fmt_offset(d.raw_offset)} ({d.drift_status})" for d in p.devices.values()
                       if d.kind == "camera")
    run = {"when": _dt.now().isoformat(timespec="minutes"), "model": args.model, "effort_describe": args.effort_describe,
           "effort_structure": args.effort_structure, "interval": args.interval, "prompt": f"{describe.PROMPT_VERSION}/{structure.PROMPT_VERSION}",
           "clocks": clocks, "cost": res.cost(), "refusals": res.usage.refusals if res.usage else 0,
           "describe_s": res.usage.wall if res.usage else 0,
           "structure_s": st.usage.get("seconds", 0) if st.usage else 0, "total_s": round(_time.time() - t0)}
    out_dir = config.REPO_ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    stem = f"{p.name.strip().replace(' ', '_')}-{_dt.now():%Y%m%d-%H%M}" + ("-offline" if args.offline else "")
    (out_dir / f"{stem}.md").write_text(evaluate.report_md(p.name.strip(), m, run))
    (out_dir / f"{stem}.json").write_text(json.dumps({"run": run, "metrics": m, "structure": st.to_json()},
                                                     ensure_ascii=False, indent=1))
    _print_structure(st)
    pw = m["pairwise"]
    print(f"\nmatched accuracy {m['matched_accuracy']:.1%} · pairwise F1 {pw['f1']:.3f} · ARI {m['ari']:.3f} · "
          f"folders {m['folders_pred']} vs {m['folders_truth']} · boundaries F1 {m['boundaries']['f1']:.3f}")
    print(f"report: reports/{stem}.md")
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
    if not pl.ok:
        return 1
    if not args.apply:
        print("\ndry run: nothing moved. Add --apply to move the files (undo with `hypershutter undo`).")
        return 0
    preset = config.load_preset(p.event_type)
    if args.backup:
        r = execute.backup(p, Path(args.backup), progress=_progress)
        print(f"backup: {r['verified']} files verified in {r['dest']} ({r['copied']} copied)")
    j = execute.apply(p, st, pl, preset, progress=_progress, extras=index.generated_files, force=args.force)
    print(f"moved {sum(m['status'] == 'moved' for m in j['moves'])} files; wrote {len(j['files_created'])} files "
          f"(index + contact sheets). Journal {j['id']} in {folder / execute.JOURNAL_DIR}.")
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
    u = execute.undo(p, j, progress=_progress)
    print(f"{u['status']}: {sum(m['status'] == 'undone' for m in u['moves'])} files back in place")
    for prob in u.get("problems", []):
        print(f"  problem: {prob}")
    return 0 if u["status"] == "undone" else 1


def cmd_premiere(args) -> int:
    from hypershutter.core import premiere
    folder = Path(args.folder).expanduser()
    p, st = _reviewed(folder)
    if st is None:
        return 1
    which = (args.only,) if args.only else ("highlights", "flow")
    r = premiere.export(p, st, Path(args.song).expanduser() if args.song else None, not args.no_preview, which,
                        progress=_progress)
    print(f"song: {r['song']}")
    for key in which:
        x = r[key]
        print(f"{key}: {x['xml']}  ({fmt_duration(x['seconds'])}, {x['clips']} clips)" +
              (f"\n  preview: {x['preview']}" if x.get("preview") else ""))
    for w in r["warnings"]:
        print(f"  note: {w}")
    return 0


def cmd_broll(args) -> int:
    from hypershutter.core import edit, premiere
    folder = Path(args.folder).expanduser()
    p, st = _reviewed(folder)
    if st is None:
        return 1
    descs = premiere.descriptions(p, st)
    groups = edit.ceremony_groups(st)
    if args.folder_number:
        cats = [c for c in st.categories if f"{c.number:02d}{c.sub}".startswith(args.folder_number.zfill(2))]
        groups = [(cats[0].label_el, cats)] if cats else []
    for name, cats in groups:
        print(edit.broll_markdown(name, edit.broll_list(p, st, descs, [c.key for c in cats])))
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
        sp.add_argument("--offline", action="store_true", help="no API: time-gap segmentation")
        sp.add_argument("--yes", action="store_true", help="skip the cost confirmation")

    sp = sub.add_parser("structure", help="describe every clip and build the event's folder structure (dry run)")
    analysis_args(sp)
    sp.set_defaults(func=cmd_structure)

    sp = sub.add_parser("eval", help="accuracy against an organized event (read-only); report in reports/")
    analysis_args(sp)
    sp.add_argument("--index", help="use this shot index as ground truth instead of the folders")
    sp.set_defaults(func=cmd_eval)

    sp = sub.add_parser("key", help="store the Anthropic API key in the macOS Keychain")
    sp.add_argument("action", choices=["set", "status", "delete"], nargs="?", default="status")
    sp.set_defaults(func=cmd_key)

    sp = sub.add_parser("apply", help="move clips into the reviewed folders (dry run unless --apply)")
    sp.add_argument("folder")
    sp.add_argument("--apply", action="store_true", help="really move the files (journaled, undoable)")
    sp.add_argument("--backup", metavar="DIR", help="copy and verify every file to DIR first")
    sp.add_argument("--rename", metavar="PATTERN", help="rename files, e.g. '{num}_{n:03d}_{name}' (off by default)")
    sp.add_argument("--force", action="store_true", help="allow an event that looks organized by hand")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("undo", help="move every file of the last apply back to where it was")
    sp.add_argument("folder"); sp.add_argument("--yes", action="store_true")
    sp.set_defaults(func=cmd_undo)

    sp = sub.add_parser("premiere", help="highlights + ροή as Premiere XML, with low-res previews")
    sp.add_argument("folder"); sp.add_argument("--song", help="song for the highlights (default: the event's music/)")
    sp.add_argument("--no-preview", action="store_true"); sp.add_argument("--only", choices=["highlights", "flow"])
    sp.set_defaults(func=cmd_premiere)

    sp = sub.add_parser("broll", help="B-roll lists per ceremony (or one folder), strongest first")
    sp.add_argument("folder"); sp.add_argument("--folder-number", help="e.g. 08 or 09a")
    sp.set_defaults(func=cmd_broll)

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
