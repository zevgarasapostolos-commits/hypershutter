# HyperShutter

A macOS app for wedding, baptism and event videographers. Drop in the raw footage folder of an
event and HyperShutter reproduces the videographer's own organizing workflow: it syncs the camera
clocks, builds contact sheets, uses Claude vision to understand every clip, proposes an
event-specific category structure (numbered, Greeklish folder names, ΡΟΗ / B-ROLL splits), and
after review moves everything into place with a full undo journal, a shot index and per-category
contact sheets. It then prepares B-roll selections and Premiere sequences.

> Status: **M6 — edit prep** (baptism). The window (`hypershutter app`) has Projects, Scan & Analyze,
> Review with Apply / Undo, and Edit prep (B-roll lists, highlights + ροή as Premiere XML with previews).
> Wedding-specific rules are pending the user's instructions.

## Usage (so far)

```bash
hypershutter app                                # the window: Projects → Scan & Analyze → Review
hypershutter app --browser                      # same UI in a normal browser (development)
hypershutter scan "/Volumes/T7/<event>/"        # clips, sidecars, devices, duplicate/corrupt checks
hypershutter sync "/Volumes/T7/<event>/"        # clock offsets from shared audio
hypershutter sync "/Volumes/T7/<event>/" --set A=+14:00 --manual-only   # manual override
hypershutter timeline "/Volumes/T7/<event>/"    # every clip on the corrected timeline
hypershutter frames "/Volumes/T7/<event>/"      # frames (1 per 2 s + scene changes), contact sheets, cost estimate
hypershutter key set                            # store the Anthropic API key in the macOS Keychain
hypershutter structure "/Volumes/T7/<event>/"   # pass 1 (describe) + pass 2 (structure), dry run
hypershutter eval "/Volumes/T7/<organized event>/"   # accuracy against the user's own folders
hypershutter apply "/Volumes/T7/<event>/"       # dry run: what would move where
hypershutter apply "/Volumes/T7/<event>/" --apply [--backup /Volumes/Backup]   # move (journaled)
hypershutter undo "/Volumes/T7/<event>/"        # every file back to its exact original path
hypershutter broll "/Volumes/T7/<event>/"       # B-roll lists per ceremony, strongest first
hypershutter premiere "/Volumes/T7/<event>/"    # highlights + ροή Premiere XML and previews
```

The AI model defaults to Claude Opus 5.5 (`--model claude-sonnet-5-5` or `claude-haiku-5-5` are
cheaper). A cost and time estimate is shown before any API call.

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
| `hypershutter/core/` | pipeline: scan, checks, sync, frames, sheets, describe, structure, review, execute (apply/undo/backup), index, edit (B-roll, highlights, ροή), music, xmeml, preview, premiere, evaluate, pipeline |
| `hypershutter/app/` | `main.py` (pywebview window), `server.py` (local server on 127.0.0.1 with a per-run token), `bridge.py` (the API every screen calls) |
| `ui/` | plain HTML/CSS/JS: `css/tokens.css`, `css/app.css`, `js/`, `locales/en.json`, `locales/el.json` |
| `presets/` | category **hints** per event type (never fixed lists) |
| `docs/` | the user's workflows and findings |
| `tests/` | pytest |

## Docs

- [docs/workflow-organizing.md](docs/workflow-organizing.md): how footage is organized (user's export, Greek)
- [docs/workflow-editing.md](docs/workflow-editing.md): B-roll, highlights, ροή, Premiere XML rules
- [docs/m0-findings.md](docs/m0-findings.md): cameras, clocks, formats, evaluation targets
- [docs/m1-clock-sync.md](docs/m1-clock-sync.md): scan, devices, clock sync (NCC vs GCC-PHAT), results
- [docs/m2-frames.md](docs/m2-frames.md): frame extraction benchmark, contact sheet sizing, cost estimate
- [docs/m3-describe-structure.md](docs/m3-describe-structure.md): the two AI passes, validation rules, evaluation
- [docs/m5-apply.md](docs/m5-apply.md): plan, write-ahead journal, move, undo, backup, index, contact sheets
- [docs/m6-edit.md](docs/m6-edit.md): B-roll lists, highlights and ροή rules, Premiere XML, previews

## Accuracy

Evaluation mode runs the pipeline read-only on an already-organized event and compares the
groupings with the user's own folders (details in [docs/m3](docs/m3-describe-structure.md)).

| Event | Run | Matched accuracy | Pairwise F1 | ARI | Folders (truth) | Cost |
|---|---|---|---|---|---|---|
| Baptism, 267 clips | offline (time gaps only) | 46.1% | 0.290 | 0.177 | 7 (17) | $0 |
| Baptism, 267 clips | Opus 5.5, first prompts | 89.1% | 0.872 | 0.862 | 20 (17) | $7.69 |
| Baptism, 267 clips | Opus 5.5, rules s2 | **97.8%** | **0.963** | **0.960** | **17 (17)** | +$0.38 |

The s2 rules were tuned on this event; a held-out event is still to be evaluated.
