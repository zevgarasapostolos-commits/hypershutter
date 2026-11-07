# HyperShutter

**Ingest, archiving and automatic sorting of wedding videography footage** (undergraduate thesis,
Digital Systems, University of Thessaly).

HyperShutter copies memory cards to several drives at once with checksum verification and creates
proxies in the background. It sorts the footage automatically by moment of the wedding (groom and
bride getting ready, ceremony, reception …) using capture time, image and audio analysis and the
camera. The videographer reviews and corrects the sorting before the files are organized into
numbered Greeklish folders, with an undo journal, a shot index and per-folder contact sheets. It
also monitors drive space and does batch exports with presets. Weddings are the main target;
baptisms and other events work through presets.

> Status: sorting, review, apply / undo and evaluation work (CLI and window). Remaining: audio
> analysis in the sorting and the ablation study (T2), ingest (T3), proxies and drive monitoring
> (T4), multi-drive organize (T5), batch export (T6), the remaining screens (T7), design (T8) and
> packaging (T9). The earlier editing prototype (B-roll, Premiere XML) lives on the `edit-prep`
> branch and is out of the thesis scope.

## Usage

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
```

The AI model defaults to Claude Opus 5.5 (`--model claude-sonnet-5-5` or `claude-haiku-5-5` are
cheaper). A cost and time estimate is shown before any API call.

Clock offsets are stated like the shot index states them: relative to what the camera clock
wrote (e.g. "camera A is +14:00"). Each device gets an anchor/auto/manual/unresolved status.

## Safety rules

- Memory cards are read-only: ingest copies and verifies, it never moves, renames or formats.
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
          │  Home · Ingest · Analyze · Review · Export · Drives … │
          └───────────────────────────┬───────────────────────────┘
                                      │ same calls
                     CLI  hypershutter ingest|scan|sync|frames|structure|eval|apply|undo|export
                                      │
 core/  ingest (cards → N drives, verified) ─► proxies (background)
          │
        scan → checks → sync → frames + audio features → describe (Claude, per clip)
                                                        → structure (Claude, whole event)
                                                                         │
                         Review / approve ──► execute (journal, move, undo) → index + contact sheets
                                                                         │
                                                        batch export (presets) · drive monitoring
 state: SQLite + frame cache in ~/Library/Application Support/HyperShutter/
```

| Path | Contents |
|---|---|
| `hypershutter/core/` | pipeline: scan, checks, sync, frames, sheets, describe, structure, review, execute (apply/undo/backup), index, audio, transcribe, evaluate, pipeline |
| `hypershutter/app/` | `main.py` (pywebview window), `server.py` (local server on 127.0.0.1 with a per-run token), `bridge.py` (the API every screen calls) |
| `ui/` | plain HTML/CSS/JS: `css/tokens.css`, `css/app.css`, `js/`, `locales/en.json`, `locales/el.json` |
| `presets/` | category **hints** per event type (never fixed lists) |
| `docs/` | the user's workflows and findings |
| `tests/` | pytest |

## Docs

- [docs/workflow-organizing.md](docs/workflow-organizing.md): how footage is organized (user's export, Greek)
- [docs/workflow-baptism.md](docs/workflow-baptism.md): the user's full baptism guide (only its organizing part is in scope)
- [docs/m0-findings.md](docs/m0-findings.md): cameras, clocks, formats, evaluation targets
- [docs/m1-clock-sync.md](docs/m1-clock-sync.md): scan, devices, clock sync (NCC vs GCC-PHAT), results
- [docs/m2-frames.md](docs/m2-frames.md): frame extraction benchmark, contact sheet sizing, cost estimate
- [docs/m3-describe-structure.md](docs/m3-describe-structure.md): the two AI passes, validation rules, evaluation
- [docs/m5-apply.md](docs/m5-apply.md): plan, write-ahead journal, move, undo, backup, index, contact sheets

## Accuracy

Evaluation mode runs the pipeline read-only on an already-organized event and compares the
groupings with the user's own folders (details in [docs/m3](docs/m3-describe-structure.md)).

| Event | Run | Matched accuracy | Pairwise F1 | ARI | Folders (truth) | Cost |
|---|---|---|---|---|---|---|
| Baptism, 267 clips | offline (time gaps only) | 46.1% | 0.290 | 0.177 | 7 (17) | $0 |
| Baptism, 267 clips | Opus 5.5, first prompts | 89.1% | 0.872 | 0.862 | 20 (17) | $7.69 |
| Baptism, 267 clips | Opus 5.5, rules s2 | **97.8%** | **0.963** | **0.960** | **17 (17)** | +$0.38 |
| **Held-out baptism, 249 clips** | Opus 5.5, rules s2 | **95.6%** | **0.915** | **0.905** | 14 (13) | $6.02 |
| Second baptism, 249 clips | Opus 5.5, rules s4 | **96.0%** | **0.924** | **0.914** | 14 (13) | +$0.36 |
| Wedding + baptism, 507 clips | Opus 5.5, first prompts | 82.5% | 0.835 | 0.815 | 24 (18) | $13.71 |
| Wedding + baptism, 507 clips | Opus 5.5, rules s4 | **96.5%** | **0.952** | **0.947** | 19 (18) | +$0.68 |

The s2 rules were tuned on the first baptism; the second one was never used for tuning in s2. s3 added wedding hints, and s4 brought back a general rule after s3 lowered the second baptism (see [docs/m3](docs/m3-describe-structure.md)).
