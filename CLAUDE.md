# HyperShutter — Project Brief for Claude Code

This file is the single source of truth for the project. Read it fully at the start of every session.

## 1. What we are building

**HyperShutter** is a macOS app for wedding / baptism / event videographers. You drop in the raw footage folder of an event and it reproduces the user's own organizing workflow automatically:

1. scans every clip from every camera and syncs the camera clocks,
2. extracts many frames from each clip and builds contact sheets,
3. uses AI vision (Claude API) plus capture time, duration and camera to understand what happens in every clip,
4. **builds the category structure for that specific event** (every event is different — there is no fixed list), assigns every clip, and shows a review screen where the user can correct anything,
5. after approval, moves the files into numbered Greeklish category folders, writes the shot index and per-category contact sheets, keeps an undo journal,
6. continues with the rest of the user's workflow (B-roll selection, Premiere sequences) as documented in the workflow docs (section 4).

Owner and only user right now: **Apostolos**, professional wedding/event videographer and Digital Systems student (University of Thessaly). This is also his university project, so measured accuracy and clean architecture matter.

**Deadline: the whole project must be done within one month — build as fast as possible.**
**Priority order: 1) it works and the result is correct, 2) then the design.**

## 2. Talking to the user

- Talk to Apostolos **in Greek**. Code, commits, comments and docs in English.
- Work autonomously and fast. Do not ask for approval of every step.
- Stop and ask only for: (a) any operation that moves/renames files in a real event folder, (b) showing the first contact sheets and the first accuracy report, (c) decisions that change scope or add a big dependency, (d) missing workflow docs (section 4).
- At the end of each milestone: a short Greek summary (what works, what to test, any open issue), then commit + push and continue.

## 3. Golden rules (never break these)

- **Do not open, list, read or analyze the project `059 baftisi alexia` in any way**, and do not reuse anything about it from old sessions.
- **Reference projects are strictly read-only**: no moves, renames, new files, caches or metadata writes inside them. Caches go to Application Support, reports to the repo.
- **Never delete footage.** Duplicates and corrupt files are flagged, never deleted.
- **Never modify source files** (no re-encode, no metadata writes).
- **Dry run first.** Nothing moves until the user approves in the Review screen (or with an explicit `--apply` in the CLI).
- **Undo must always work.** Every move/rename is written to a journal *before* it happens; undo restores exact original paths and names.
- **Sidecars travel with their clip** (Sony `.XML`, DJI `.SRT` / `.LRF`, `.THM`, etc.).
- During development, test move/rename/undo **only on a small test copy** (20–40 clips copied to a separate folder outside any real project, e.g. `~/HyperShutter-test/`), never on a real project.
- Never send file names or folder paths to the AI model (in already-sorted projects folder names reveal the answer).
- Never commit footage, frames, caches, client names, logs with personal data, `.env`, or API keys.

## 4. The workflow to reproduce

### 4.1 Source of truth: the user's two existing workflows

The app must do what the user already does with Claude in two places:
1. a chat called **"βαφτιση b roll επιλογη"** (baptism: organizing footage and selecting B-roll from frames), and
2. a **Claude Code session where he organizes baptisms**, which also has a thread for **weddings**.

How to get them:
- The user will export each workflow as a Markdown file: `docs/workflow-baptism.md` and `docs/workflow-wedding.md`. Read them first; they override any default in this file.
- Also search previous local Claude Code sessions (`.jsonl` files under `~/.claude/projects/`) read-only for the baptism/wedding organizing sessions and extract the method. **Skip anything about `059 baftisi alexia`.**
- If neither the docs nor the sessions are available, ask the user for the docs before building the categorization (M3). Summarize what you learned to the user in Greek before building on it.

Extract from them: how capture times and camera clocks were handled, how frames and contact sheets were made (density, grid, size), how the event's parts were decided and named, how ΡΟΗ vs B-ROLL was split, how B-roll was selected, how the index and contact sheets were written, how the Premiere sequences (ροή / highlights) and previews were built, and every rule or correction the user gave.

### 4.2 Categories are dynamic — every event is different

There is **no fixed category list** for a baptism or a wedding. Each event gets its own structure, built from what is actually in the footage, following the user's workflow:
- numbered in chronological order of the day (`01`, `02` …), with sub-letters when a part is split (e.g. `08` / `08a`),
- names describe what is in that part of this specific event,
- a ceremony part can be split into **ΡΟΗ** (the few long continuous takes that cover it start to end) and **B-ROLL** (short cutaways — faces, details, close-ups, often from the second camera),
- drone clips usually get their own category,
- unusable/unknown clips go to `99 AXRISTA` (only if there are any).

`presets/*.yaml` are **hints only**: typical parts of a baptism / wedding / event, the naming style, and the rules above — never a fixed list. In Review the user can rename, merge, split and reorder categories.

### 4.3 Naming: Greeklish

All folder names and the index file name are **Greeklish** (Latin characters), regardless of the UI language — e.g. `01 STOLISMOS & CANDY BAR`, `08 KATIXISI - ROI`, `08a KATIXISI - B-ROLL`, `99 AXRISTA`. Take the exact transliteration style and the index/contact-sheet file names from the workflow docs; if they don't specify, ask the user once and store the answer in the preset.

### 4.4 Example of a finished project (example only — not a template)

`/Volumes/T7/073 Β11-10-2026 Γ ` (note: the folder name **ends with a space**; always quote paths). It shows the kind of output the workflow produces — its exact categories are specific to that baptism and must not be hard-coded:

```
00 CONTACT SHEETS/          one contact sheet per category (01.jpg … 15.jpg, 08a.jpg, 09a.jpg)
00 ΕΥΡΕΤΗΡΙΟ ΠΛΑΝΩΝ.md      shot index
01 … 15                     17 category folders, incl. 08/08a (catechism ΡΟΗ / B-ROLL),
                            09/09a (ceremony ΡΟΗ / B-ROLL), a DRONE folder, …
cam apos/ cam dim/ drone/   original source folders, empty after the move
music/                      music track for the edit
073 B11-10-2026 ροή.xml, 073 B11-10-2026 highlights.xml     Premiere sequences
073 ροή - preview (για έλεγχο).mp4, 073 highlights - preview (για έλεγχο).mp4
```

(This example still has Greek folder names; new output uses Greeklish per 4.3.) 267 clips: camera A `C41xx–C43xx` (main, from `cam apos`), camera B `C65xx` (from `cam dim`), drone `DJI_YYYYMMDDhhmmss_NNNN_D.MP4`. Original camera file names are kept. The index notes that camera A's clock was wrong (by +14:00) and that this was confirmed by finding camera-B clips showing the same moment inside camera-A clips.

Source folder names vary between projects (`cam apos`, `apos`, `dim`, `drone`, `sound`, `music` …): detect cameras by file pattern and metadata, not only folder name. Sidecars may be missing.

### 4.5 Shot index format (as in the example; file name in Greeklish)

- Title `# <project folder name> — ευρετήριο πλάνων` (or as the workflow docs say).
- Bold one-line summary (event type, name if the user entered one, date, time of day) + total clips and folders.
- Camera legend with file patterns and clip counts; clock-correction note when an offset was applied.
- **Χρονολόγιο**: one line with the time range of each part of the day.
- Pointer to the contact sheets folder.
- Per category: `## <folder name>`, one Greek sentence describing what is in it, `**N πλάνα · X λεπτά**`, then the table `| clip | κάμ. | ώρα | διάρκεια |` sorted by corrected time.
- ⭐ optional.

### 4.6 Reference projects for testing

- **Baptism:** `073 Β11-10-2026 Γ` (above).
- **Wedding:** the wedding of **25 July** — find its folder on the T7 and confirm the exact name with the user. The user will give detailed wedding instructions when we reach it.

## 5. Tech stack

- **Python 3.12+**, virtualenv, dependencies pinned in `requirements.txt`.
- **pywebview** for a native macOS window (WKWebView) with an HTML/CSS/JS interface. Plain JS or a very light library — no heavy frontend framework unless clearly needed.
- **ffmpeg / ffprobe** from Homebrew (check on startup; guide installation if missing). Use `-hwaccel videotoolbox` where it helps.
- **Anthropic Python SDK** for vision. Model configurable in Settings (default a Sonnet-class model, cheaper Haiku-class option). Check the current model names and image limits in the official docs before coding.
- **SQLite** for project state and frame cache index, stored in `~/Library/Application Support/HyperShutter/`.
- API key stored in the **macOS Keychain** (`keyring`), never in files or the repo.
- Packaging into **HyperShutter.app** with py2app or PyInstaller; `.icns` icon built with `iconutil`.
- The core must also run as a **CLI** (`hypershutter scan | sync | frames | describe | structure | eval | apply | undo | premiere`) — the GUI calls the same core. This makes testing and the university report easy.

Suggested layout:

```
hypershutter/
  core/      scan.py checks.py timecode.py sync.py frames.py describe.py structure.py
             execute.py (backup / move / rename / undo) index.py broll.py premiere.py
             evaluate.py config.py
  app/       main.py (pywebview bootstrap, JS bridge, menus)
  ui/        index.html  css/tokens.css  css/app.css  js/  locales/en.json  locales/el.json
  presets/   baptism.yaml wedding.yaml event.yaml   (hints, not fixed lists)
  docs/      workflow-baptism.md workflow-wedding.md (from the user)
  assets/    branding/ (logo + icon — placeholders until provided)
  tests/     pytest: journal/undo, move, time parsing, sidecar grouping, clock sync, metrics
  scripts/   build_app.sh
```

## 6. Processing pipeline

### 6.1 Scan and clock sync
- Walk the source folders; detect video, audio and sidecar files; group sidecars with their clip.
- ffprobe: duration, resolution, fps, codec, `creation_time`.
- Capture time, best source first: Sony XML sidecar, DJI file-name timestamp and `.SRT`, container `creation_time`, file mtime as last resort. Handle time zones correctly (Greece).
- **Per-camera clock offset**: detect automatically by finding the same moment on two cameras (frame similarity and/or audio cross-correlation of overlapping clips), propose the offset, let the user confirm or edit it. Test case: camera A in the example (+14:00).
- Audio-only files are assigned by time overlap with video clips.

### 6.2 Checks
- Duplicates: size → partial hash → full hash. Flag only.
- Corrupt / unreadable / zero-length files: flag only.

### 6.3 Frames — dense by design
The user wants **as many frames as possible** for accuracy.
- Default density: **1 frame every 2 seconds** plus extra frames at scene changes (ffmpeg scene detection). No artificial per-clip cap. Density is a setting (e.g. 1/4 s, 1/2 s, 1/1 s). Follow the workflow docs if they used a different method.
- One ffmpeg decode pass per clip (fps filter + scene select + downscale), clips processed in parallel. Use DJI `.LRF` low-res files when present (much faster).
- Tile frames into **contact sheets** (e.g. 6×4 = 24 frames per sheet, each labeled with its timestamp), sized around the API's optimal image size. Long clips (e.g. 90+ minutes of dancing) produce several sheets.
- Cache frames and sheets in Application Support; never re-extract unless settings change.
- Before calling the API, show an **estimate of cost and time**; the user confirms.

### 6.4 Understanding and structuring (two passes)
- **Pass 1 — describe every clip** (per clip, in parallel): send its contact sheets, corrected time, duration and camera. Get structured JSON: what/who/where, shot type (wide / close-up / detail / portrait / aerial), continuous take vs cutaway, notable moments, quality issues (blur, black, accidental), optional star suggestion.
- **Pass 2 — build the event structure** (one call over the whole event): send all clip descriptions on the corrected timeline (text only, plus a few representative sheets if useful), the preset hints and the workflow rules. Get back: the event's parts in chronological order with Greeklish folder names and numbers, ΡΟΗ / B-ROLL splits where they apply, the drone folder, `99 AXRISTA` if needed, a Greek one-line description per part, and the assignment of every clip with a confidence.
- **Smoothing / validation**: fix isolated outliers that contradict their neighbors in time; every clip assigned exactly once; numbering follows the timeline.
- Low confidence → "Needs review".
- **Offline fallback**: time-gap segmentation of the timeline (big gaps = new part) with generic names, when there is no internet or API key.

### 6.5 Evaluation mode (correctness proof — do this early)
- Input: an already-organized project (baptism `073`, later the 25 July wedding). Ground truth = the folder each clip is in.
- Run the full pipeline **read-only** (no moves), hiding names/paths from the model.
- Because category names differ between runs, use **grouping metrics**, not name matching:
  - match predicted folders to ground-truth folders by overlap (Hungarian matching) → matched accuracy and per-folder precision/recall,
  - pairwise precision / recall / F1 (do clips the user put together end up together?),
  - Adjusted Rand Index,
  - number of folders predicted vs ground truth, and how well part boundaries line up on the timeline,
  - whether the clock offset was detected correctly,
  - cost and runtime.
- Save as Markdown + JSON in `reports/` (git-ignored if it contains client names). Compare frame densities (1/4 s vs 1/2 s vs 1/1 s) on a subset — this goes into the university report.
- Iterate on prompts and rules until the numbers are clearly good, and report them to the user.

### 6.6 Review → Apply
- Review screen: categories with thumbnails; hover to scrub through frames; drag a clip to another category; rename / merge / split / reorder categories; filter "Needs review"; toggle ⭐.
- Optional **backup** to a second drive with checksum verification (xxhash) before any move.
- **Move** into the numbered folders, sidecars included. Source folders stay (empty). Renaming files is **off by default** (camera file names are kept); optional pattern.
- Journal written to Application Support **and** to `<project>/.hypershutter/journal.json`; one-click **Undo**.
- Generate the shot index (4.5) and the contact sheets folder (one sheet per category, named by category number).

### 6.7 Rest of the workflow (core — as in the workflow docs and the example)
- **B-roll selection** exactly as done in the "βαφτιση b roll επιλογη" workflow.
- **Premiere sequences**: a **ροή** (full flow) and a **highlights** sequence as Premiere-importable XML, with music from the project's music folder if present, plus low-res preview renders for checking — modeled on the two XMLs and previews in the example project.

## 7. The app (sections like a real Mac app)

- **First-run onboarding**: welcome, language choice, ffmpeg check, API key (to Keychain), default backup drive.
- **Projects / Home**: recent projects, drag & drop an event folder, event type selection, optional event name and day schedule.
- **Scan & Analyze**: progress for scan, clock sync, checks, frames, description, structure; cost estimate and confirm.
- **Review**: the main screen (6.6).
- **Edit prep**: B-roll selection and Premiere export (6.7).
- **Accuracy Lab**: run evaluation mode and view reports.
- **Settings**: language, AI model, frame density, preset hints and naming style, per-camera clock offsets, rename pattern, backup destination, API key.
- **Features** — "What HyperShutter can do": a clear page presenting the capabilities.
- **Help & Support**: FAQ, "Contact support" (opens Mail with a pre-filled message to a support address set in config — placeholder until the user gives one), "Report a bug" (GitHub Issues link), "Export diagnostics" (logs and settings only — never footage, never the API key).
- **About**: version, credits, licenses.
- Standard macOS menu bar (HyperShutter, File, Edit, View, Window, Help) and keyboard shortcuts.

### Languages
- **English (default) and Greek**, switchable in Settings and onboarding.
- Every UI string goes through `locales/en.json` / `locales/el.json` — no hard-coded text. Folder names on disk are always Greeklish (4.3).

## 8. Design (polish AFTER the core works — but put the tokens in place from day one)

Look and feel: **professional, calm, luxurious**, like a premium native Mac app.

- **Fonts**: the Apple system font through the CSS stack `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui`. Optional elegant serif for large headings via `ui-serif` (Apple's New York). Do **not** bundle Apple font files (license); use the system fonts.
- **Colors** (CSS variables in `ui/css/tokens.css`):
  - `--hs-white: #FFFFFF` — main background
  - `--hs-gold: #A59769` — accent
  - `--hs-slate: #405366` — primary color, text, primary buttons
  - Tints/shades of these may be derived (e.g. a warm off-white surface, a deep slate for text).
- **Accessibility**: gold on white has a contrast of about 2.8:1, too low for text. Use gold only for hairlines, icons, focus rings, active states and very large display elements. Text and buttons use slate (~8:1 on white).
- Luxury cues: generous whitespace, thin 1px gold hairlines, refined small uppercase labels with letter spacing, large thumbnails, restrained 200–300 ms animations, no emoji, no loud gradients, sidebar navigation that feels native.
- Imagery: at most one or two photos in the whole app (e.g. onboarding). Ask the user for them only in the design phase.
- Logo and app icon: will be provided by the user in `assets/branding/` (SVG + 1024px PNG). Use a simple text placeholder until then.

## 9. GitHub

- Check `gh` is installed and authenticated (`gh auth status`). If not, install with Homebrew and ask the user to run `gh auth login` himself (he enters his own credentials).
- Create a **private** repository named `hypershutter` (it can be made public later for the CV) and push.
- `.gitignore`: venv, caches, frames, `reports/` with client data, `.env`, `*.app` build output, macOS junk.
- **Commit and push after every working change** with clear English messages — the user wants every change pushed. Tag `v0.1.0` when the first `.app` is packaged.
- Keep `README.md` current: what it is, screenshots (later), how to install and run, architecture diagram, accuracy results.

## 10. Milestones (no calendar — do them back to back)

- **M0 — Setup & learning**: repo + GitHub, venv, ffmpeg check, this file in the repo root, README skeleton. Read the workflow docs / old sessions (4.1) and the example project read-only (index, contact sheets, Premiere XMLs, a few ffprobes). Write the preset hints. Report findings in Greek.
- **M1 — Scan, clock sync & checks (CLI)**: timeline with corrected capture times (must find the camera-A offset in the example), duplicates, corrupt files.
- **M2 — Frames & contact sheets**: dense extraction + cache. **Show the user 2–3 contact sheets for approval.**
- **M3 — Describe + structure + evaluation**: the two passes, smoothing, offline fallback, Accuracy Lab report on the baptism example. **Show the first accuracy report.** Iterate.
- **M4 — App shell**: pywebview window, Home, Scan & Analyze, Review (functional, tokens applied, minimal styling).
- **M5 — Apply**: backup, move, journal, undo, shot index, contact sheets folder. Unit tests. Verified on the test copy, including undo.
- **M6 — Rest of the workflow**: B-roll selection and Premiere ροή / highlights XML + previews (6.7). Wedding support per the user's instructions and the wedding workflow doc, evaluated on the 25 July wedding.
- **M7 — Complete app**: onboarding, Settings, EN/EL, Features, Help & Support, About, menus.
- **M8 — Design pass**: luxury polish, logo and icon integration.
- **M9 — Ship**: package `HyperShutter.app`, README with architecture and accuracy numbers, tag release.
- **Stretch (only if time remains)**: drone clips grouped by GPS location; proxies; AI star suggestions.
