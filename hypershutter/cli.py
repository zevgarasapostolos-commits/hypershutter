"""Command line entry point. The GUI calls the same core functions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from hypershutter import __version__
from hypershutter.core import checks, config, scan, sync
from hypershutter.core.media import fmt_duration, fmt_offset
from hypershutter.core.project import Project

# Subcommands still to be built, with the milestone that delivers them.
PLANNED = {
    "frames": "M2", "describe": "M3", "structure": "M3", "eval": "M3",
    "apply": "M5", "undo": "M5", "premiere": "M6",
}


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
