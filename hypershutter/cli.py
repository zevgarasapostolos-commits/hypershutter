"""Command line entry point. The GUI calls the same core functions."""

from __future__ import annotations

import argparse
import sys

from hypershutter import __version__
from hypershutter.core import config

# Subcommands still to be built, with the milestone that delivers them.
PLANNED = {
    "scan": "M1", "sync": "M1", "frames": "M2", "describe": "M3", "structure": "M3",
    "eval": "M3", "apply": "M5", "undo": "M5", "premiere": "M6",
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hypershutter", description="Organize event footage.")
    p.add_argument("--version", action="version", version=f"hypershutter {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check ffmpeg/ffprobe and paths").set_defaults(func=cmd_doctor)
    for name, milestone in PLANNED.items():
        sp = sub.add_parser(name, help=f"(not built yet, {milestone})")
        sp.set_defaults(func=lambda _a, n=name, m=milestone: print(f"`{n}` arrives in {m}.") or 2)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
