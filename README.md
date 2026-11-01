# HyperShutter

A macOS app for wedding, baptism and event videographers. Drop in the raw footage folder of an
event and HyperShutter reproduces the videographer's own organizing workflow: it syncs the camera
clocks, builds contact sheets, uses Claude vision to understand every clip, proposes an
event-specific category structure (numbered, Greeklish folder names, ΡΟΗ / B-ROLL splits), and
after review moves everything into place with a full undo journal, a shot index and per-category
contact sheets. It then prepares B-roll selections and Premiere sequences.

> Status: **M1 — scan, clock sync & checks** (CLI). `scan`, `sync` and `timeline` work read-only;
> later stages are stubs.

## Usage (so far)

```bash
hypershutter scan "/Volumes/T7/<event>/"        # clips, sidecars, devices, duplicate/corrupt checks
hypershutter sync "/Volumes/T7/<event>/"        # clock offsets from shared audio
hypershutter sync "/Volumes/T7/<event>/" --set A=+14:00 --manual-only   # manual override
hypershutter timeline "/Volumes/T7/<event>/"    # every clip on the corrected timeline
```

Clock offsets are stated like the shot index states them: relative to what the camera clock
wrote (e.g. "camera A is +14:00"). Each device gets an anchor/auto/manual/unresolved status.

## Safety rules

- Source files are never modified, re-encoded or deleted. Duplicates and corrupt files are only flagged.
- Dry run first: nothing moves until the user approves in Review (or passes `--apply` in the CLI).
- Every move is journaled before it happens; undo restores exact original paths.
- Sidecars (`.XML`, `.SRT`, `.LRF`, `.THM`) always travel with their clip.
- File names and folder paths are never sent to the AI model.
- Caches live in `~/Library/Application Support/HyperShutter/`, never inside event folders.

## Install (development)

Requires macOS, Python 3.12+ and ffmpeg (`brew install ffmpeg`).

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/hypershutter doctor
.venv/bin/python -m pytest
```

## Architecture

```
          ┌──────────── GUI (pywebview + HTML/CSS/JS) ────────────┐
          │  Home · Scan & Analyze · Review · Edit prep · Lab …   │
          └───────────────────────────┬───────────────────────────┘
                                      │ same calls
                     CLI  hypershutter scan|sync|frames|describe|structure|eval|apply|undo|premiere
                                      │
 core/  scan → checks → sync → frames → describe (Claude, per clip) → structure (Claude, whole event)
                                                                         │
                         Review / approve ──► execute (journal, move, undo) → index + contact sheets
                                                                         │
                                                       broll → premiere (XML + previews)
 state: SQLite + frame cache in ~/Library/Application Support/HyperShutter/
```

| Path | Contents |
|---|---|
| `hypershutter/core/` | pipeline modules (config, greeklish so far) |
| `hypershutter/app/` | pywebview bootstrap (M4) |
| `ui/` | HTML/CSS/JS, `css/tokens.css`, `locales/en.json`, `locales/el.json` |
| `presets/` | category **hints** per event type (never fixed lists) |
| `docs/` | the user's workflows and findings |
| `tests/` | pytest |

## Docs

- [docs/workflow-organizing.md](docs/workflow-organizing.md): how footage is organized (user's export, Greek)
- [docs/workflow-editing.md](docs/workflow-editing.md): B-roll, highlights, ροή, Premiere XML rules
- [docs/m0-findings.md](docs/m0-findings.md): cameras, clocks, formats, evaluation targets

## Accuracy

Evaluation mode (M3) runs the pipeline read-only on already-organized events and reports
grouping metrics (Hungarian-matched accuracy, pairwise F1, Adjusted Rand Index, boundary
alignment, clock-offset error, cost, runtime). Results will be published here.
