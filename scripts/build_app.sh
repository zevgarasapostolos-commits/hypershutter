#!/bin/zsh
# Builds dist/HyperShutter.app (Apple silicon). FFmpeg is not bundled: the app checks for it at
# startup and the onboarding shows how to install it with Homebrew.
set -e
cd "$(dirname "$0")/.."
.venv/bin/python scripts/make_icon.py
.venv/bin/pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller scripts/HyperShutter.spec
echo "built: dist/HyperShutter.app"
