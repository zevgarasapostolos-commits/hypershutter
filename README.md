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

> Status: all five parts of the thesis work, in the CLI and in the app (HyperShutter.app,
> Apple silicon): verified multi-drive ingest, background proxies, sorting from time + camera +
> image + sound, review with apply / undo on every drive copy, drive monitoring and batch
> export, plus the Accuracy Lab and the ablation study. Waiting for the real logo and icon
> (a placeholder is in assets/branding/). The earlier editing prototype (B-roll, Premiere XML)
> lives on the `edit-prep` branch and is out of the thesis scope.

## Usage

```bash
hypershutter app                                # the window (Projects, Ingest, Analyze, Review, Export, Drives, Lab …)
hypershutter ingest --list                      # cards found under /Volumes
hypershutter ingest /Volumes/<card> --project "074 Γ15-11-2026" --label "cam apos" --dest /Volumes/A --dest /Volumes/B
hypershutter proxies "/Volumes/A/<event>/"      # ProRes Proxy for every clip (background queue)
hypershutter drives                             # space, events and proxies per drive, warnings
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
hypershutter export "/Volumes/T7/<event>/" --preset h264_1080_review --folders 05,08a
hypershutter ablation "/Volumes/T7/<organized event>/" --type wedding   # accuracy per signal (thesis)
```

`apply` and `undo` act on every copy of the event that ingest made (or `--mirror DIR`), after
checking that each copy matches the main one; `--signals time,camera,image,audio` chooses what the
sorting may use, and `--offline` sorts without the API (time gaps + sound).

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

## Build the app

```bash
scripts/build_app.sh            # dist/HyperShutter.app (PyInstaller, Apple silicon, ~510 MB)
```

FFmpeg is not bundled (`brew install ffmpeg`; the onboarding checks for it). The Whisper and
CED-mini models are downloaded on first use. On the first launch macOS asks to let the app read
its API key from the Keychain.

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
| `hypershutter/core/` | cards, ingest, manifest, jobs, proxies, drives, export; scan, checks, sync, frames, sheets, audio, audio_tags, transcribe, describe, structure, pipeline, review, execute (apply/undo on every copy), index, evaluate, ablation, settings |
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
- [docs/t2-sound-and-ablation.md](docs/t2-sound-and-ablation.md): sound analysis and the ablation study (thesis results)
- [docs/t3-ingest.md](docs/t3-ingest.md): verified multi-drive ingest, manifests, MHL, benchmark
- [docs/t4-t6-proxies-drives-organize-export.md](docs/t4-t6-proxies-drives-organize-export.md): proxies, drives, multi-drive organize, export

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

### Ablation study (thesis): what each signal adds

Matched accuracy (%), mean ± sd over 3–5 repeats; details and the other metrics in
[docs/t2](docs/t2-sound-and-ablation.md).

| Signals | Wedding + baptism (507) | Baptism 073 (267) | Baptism 071 (249) |
|---|---|---|---|
| offline: time gaps | 45.4 | 46.1 | 20.5 |
| offline: time gaps + sound | 60.6 | 56.5 | 40.6 |
| time | 73.2 ± 1.1 | 70.7 ± 6.6 | 60.5 ± 4.3 |
| time + camera | 75.2 ± 0.5 | 73.9 ± 12.6 | 62.4 ± 2.2 |
| time + camera + sound | 75.6 ± 0.7 | 75.0 ± 5.4 | 63.9 ± 2.1 |
| time + camera + image | 93.2 ± 1.1 | 97.8 ± 0.0 | 95.7 ± 0.3 |
| all signals | **94.1 ± 0.0** | **98.4 ± 0.2** | 94.2 ± 1.1 |

The image is the decisive signal. Sound helps without the API (+10 to +20 points). Next to the
pictures it adds +0.9 and +0.6 points on the wedding and on 073, and −0.4 to −1.5 on 071; all of
that is within the run-to-run spread. Frame density: one frame every 2 s (94.4%) beats every 4 s
(92.7%) and every 1 s (93.4%) on a 136-clip subset.

### Ingest benchmark

3.09 GB from a fake card on the internal SSD, verified on every drive:

| Drives | Card read | Total written | Verify share of the time |
|---|---|---|---|
| 1 USB SSD | 203 MB/s | 203 MB/s | 26% |
| + USB hard disk | 81 MB/s | 163 MB/s | 47% |
| + second USB SSD | 49 MB/s | 148 MB/s | 46% |

The slowest drive sets the pace (details in [docs/t3](docs/t3-ingest.md)).
