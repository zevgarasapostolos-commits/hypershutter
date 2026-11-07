"""Entry point of the packaged HyperShutter.app (the CLI's `hypershutter app` does the same).
`--browser [port]` serves the UI without a window (for checking a build)."""

import sys

from hypershutter.app.main import run

if __name__ == "__main__":
    if "--browser" in sys.argv:
        i = sys.argv.index("--browser")
        port = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 8767
        run(browser=True, port=port)
    else:
        run()
