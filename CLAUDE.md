# HyperShutter — Project Brief for Claude Code

This file is the single source of truth for the project. Read it fully at the start of every session.

## 0. Thesis — this defines the scope

HyperShutter is the user's **undergraduate thesis**. Official title and description (the scope contract — build exactly this, nothing more):

> **Σύστημα εισαγωγής, αρχειοθέτησης και αυτόματης ταξινόμησης υλικού βιντεοσκόπησης γάμων**
>
> Αντιγράφει κάρτες μνήμης με επαλήθευση checksum σε πολλούς δίσκους ταυτόχρονα και δημιουργεί proxies στο παρασκήνιο. Ταξινομεί αυτόματα το υλικό ανά στιγμή του γάμου (ετοιμασία γαμπρού και νύφης, μυστήριο, δεξίωση κ.ά.), με βάση την ώρα λήψης, την ανάλυση εικόνας και ήχου και την κάμερα. Ο χρήστης ελέγχει και διορθώνει την ταξινόμηση πριν την τελική οργάνωση των αρχείων. Παρακολουθεί τον χώρο στους δίσκους και κάνει μαζική εξαγωγή με presets.

English: *An ingest, archiving and automatic sorting system for wedding videography footage. It copies memory cards to several drives at once with checksum verification and creates proxies in the background. It automatically sorts the footage by moment of the wedding (groom and bride getting ready, ceremony, reception, etc.) using capture time, image and audio analysis, and the camera. The user reviews and corrects the sorting before the final organization of the files. It monitors drive space and does batch export with presets.*

**Out of scope — do not build:** B-roll selection for the edit, Premiere XML / sequences, preview edits, music, any automatic editing or cutting.

Weddings are the primary target (thesis). The same engine also works for baptisms and other events through presets (secondary).

Owner and only user: **Apostolos**, professional wedding/event videographer and Digital Systems student (University of Thessaly). Measured results and clean architecture matter — they go into the thesis.

**Deadline: within one month — build as fast as possible. Priority: 1) it works and the results are correct, 2) then the design.**

## 1. Features (the five parts of the thesis)

1. **Ingest** — copy memory cards to several destination drives at the same time, with checksum verification.
2. **Background proxies** — generate proxies while the user keeps working.
3. **Automatic sorting** — group clips by moment of the wedding using capture time, image analysis, audio analysis and camera.
4. **Review & correct → organize** — the user checks and fixes the sorting; only then are the files organized into folders.
5. **Drive space monitoring + batch export with presets** — live free-space view and warnings; batch transcode/export of clips or whole categories using editable presets (per-clip transcodes only — no editing).

## 2. Talking to the user

- Talk to Apostolos **in Greek**. Code, commits, comments and docs in English.
- Work autonomously and fast. Do not ask for approval of every step.
- Stop and ask only for: (a) any operation that moves/renames files in a real event folder or touches a real memory card, (b) showing the first contact sheets and the first accuracy report, (c) decisions that change scope or add a big dependency, (d) missing workflow docs (section 4).
- **Never stop to ask about API cost** during development, evaluation or the ablation study — just run (the cost estimate and confirmation are a feature of the app's UI for end users, not a stop for you). Report the total cost in the milestone summary.
- At the end of each milestone: a short Greek summary (what works, what to test, any open issue), then commit + push and continue.

## 3. Golden rules (never break these)

- **Memory cards are read-only.** Never write to, rename on, format or erase a card. Ingest is copy + verify, never move.
- A card counts as safely offloaded only when **every** destination copy is verified by checksum.
- **Do not open, list, read or analyze the project `059 baftisi alexia` in any way**, and do not reuse anything about it from old sessions.
- **Reference projects are strictly read-only**: no moves, renames, new files, caches or metadata writes inside them. Caches go to Application Support, reports to the repo.
- **Never delete footage.** Duplicates and corrupt files are flagged, never deleted.
- **Never modify source files** (no re-encode in place, no metadata writes).
- **Dry run first.** Nothing is organized until the user approves in the Review screen (or with an explicit `--apply` in the CLI).
- **Undo must always work.** Every move/rename is written to a journal *before* it happens; undo restores exact original paths and names.
- **Sidecars travel with their clip** (Sony `.XML`, DJI `.SRT` / `.LRF`, `.THM`, etc.); proxies follow their clip.
- During development, test ingest with a **fake card** (a folder copied from a real card) and test move/undo on a **small test copy** (20–40 clips in a separate folder such as `~/HyperShutter-test/`), never on a real card or project.
- Never send file names or folder paths to the AI model (in sorted projects folder names reveal the answer).
- Never commit footage, frames, caches, client names, logs with personal data, `.env`, or API keys.

## 4. The organizing workflow to reproduce

### 4.1 Source of truth: the user's existing workflows

The sorting must follow how the user already organizes events with Claude:
1. the chat **"βαφτιση b roll επιλογη"**, and
2. a **Claude Code session where he organizes baptisms**, with a thread for **weddings**.

- They are already captured in the repo: `docs/workflow-organizing.md`, `docs/workflow-baptism.md` and the milestone docs `docs/m0-findings.md` … `docs/m5-apply.md`. They override defaults in this file. **Skip anything about `059 baftisi alexia`.**
- Use **only the organizing part**: capture times and clock correction, frames and contact sheets, how the event's parts are decided and named, ΡΟΗ vs B-ROLL folders, the index and contact sheets, and every organizing rule or correction the user gave. `docs/workflow-editing.md`, `docs/wedding-reference-edit.md` and `docs/m6-edit.md` describe editing — out of scope on `main`.

### 4.2 Categories are dynamic — every event is different

There is **no fixed category list**. Each event gets its own structure, built from what is in the footage:
- numbered in chronological order of the day (`01`, `02` …), with sub-letters when a part is split (`08` / `08a`),
- names describe that part of this specific event,
- a ceremony can be split into **ΡΟΗ** (the few long continuous takes that cover it) and **B-ROLL** (short cutaways — faces, details, close-ups, often from the second camera),
- drone clips usually get their own category,
- unusable/unknown clips go to `99 AXRISTA` (only if there are any).

`presets/wedding.yaml` (primary), `baptism.yaml`, `event.yaml` are **hints only** — typical moments, naming style, rules. Typical wedding moments as hints: groom getting ready, bride getting ready, details (rings, dress, shoes), church exterior/interior, arrivals, bride's arrival/entrance, ceremony (ΡΟΗ / B-ROLL), exit & wishes, couple shoot, reception venue, couple's entrance, first dance, dancing, cake, drone. In Review the user can rename, merge, split and reorder categories.

### 4.3 Naming: Greeklish

Folder names and the index file name are **Greeklish** (Latin characters), regardless of UI language — e.g. `01 ETOIMASIA GAMPROU`, `05 MYSTIRIO - ROI`, `05a MYSTIRIO - B-ROLL`, `99 AXRISTA`. Take the exact style from the workflow docs; if they don't specify, ask the user once and store it in the preset.

### 4.4 Example of a finished project (example only — not a template)

`/Volumes/T7/073 Β11-10-2026 Γ ` — a baptism; the folder name **ends with a space** (always quote paths):

```
00 CONTACT SHEETS/          one contact sheet per category (01.jpg … 15.jpg, 08a.jpg, 09a.jpg)
00 ΕΥΡΕΤΗΡΙΟ ΠΛΑΝΩΝ.md      shot index
01 … 15                     17 category folders, incl. 08/08a and 09/09a (ΡΟΗ / B-ROLL), a DRONE folder, …
cam apos/ cam dim/ drone/   original source folders, empty after the move
```

The root also contains `music/`, Premiere XMLs and preview MP4s from editing — out of scope, ignore them (also in evaluation). Folder names here are still Greek; new output uses Greeklish (4.3). 267 clips: camera A `C41xx–C43xx` (main, `cam apos`), camera B `C65xx` (`cam dim`), drone `DJI_YYYYMMDDhhmmss_NNNN_D.MP4`. Camera file names are kept. The index notes camera A's clock was wrong (+14:00), confirmed by camera-B clips showing the same moment inside camera-A clips.

Source folder names vary (`cam apos`, `apos`, `dim`, `drone`, `sound` …): detect cameras by file pattern and metadata, not only folder name. Sidecars may be missing.

### 4.5 Shot index format (file name in Greeklish)

- Title `# <project folder name> — ευρετήριο πλάνων` (or as the workflow docs say).
- Bold one-line summary (event type, names if the user entered them, date, time of day) + total clips and folders.
- Camera legend with file patterns and clip counts; clock-correction note when an offset was applied.
- **Χρονολόγιο**: one line with the time range of each part of the day.
- Pointer to the contact sheets folder.
- Per category: `## <folder name>`, one Greek sentence describing it, `**N πλάνα · X λεπτά**`, then `| clip | κάμ. | ώρα | διάρκεια |` sorted by corrected time.
- ⭐ optional.

### 4.6 Reference projects for testing

- **Wedding (primary — the thesis is about weddings):** `gamos 25-07` (507 clips, 18 folders; wedding and baptism on the same day).
- **Baptisms:** `073 Β11-10-2026 Γ` (used for tuning) and `071` (held-out — never tune on it).
- Current results (pass-2 rules s4, Claude Opus 5.5): wedding 96.5 % matched accuracy, 073 97.8 %, 071 96.0 % — see `docs/m3-describe-structure.md`.

## 5. Tech stack

- **Python 3.12+**, virtualenv, dependencies pinned in `requirements.txt`.
- **pywebview** for a native macOS window (WKWebView) with an HTML/CSS/JS interface. Plain JS or a very light library.
- **ffmpeg / ffprobe** from Homebrew (check on startup; guide installation if missing). Use VideoToolbox hardware encode/decode where it helps.
- **Ingest**: `xxhash` (xxh3-64 or xxh64; MD5 optional for compatibility), threads for parallel destination writes, per-destination checksum manifest (ASC MHL if practical, otherwise a simple hash list + JSON report).
- **Audio analysis**: ffmpeg for loudness/silence (`ebur128`, `silencedetect`); a small pretrained **local** audio-event classifier (e.g. PANNs / YAMNet / CLAP via onnxruntime — pick what runs well on Apple Silicon) for tags like speech, singing/chanting, music, applause, crowd, bells; and the existing local Whisper (`core/transcribe.py`, large-v3-turbo on mlx) for ritual phrases and speech.
- **Anthropic Python SDK** for vision. Default model **Claude Opus 5.5** (the user's choice); Sonnet / Haiku as cheaper options.
- **SQLite** for state and caches in `~/Library/Application Support/HyperShutter/`.
- API key in the **macOS Keychain** (`keyring`), never in files or the repo.
- Packaging into **HyperShutter.app** with py2app or PyInstaller; `.icns` icon via `iconutil`.
- Everything also runs as a **CLI** (the existing commands plus `ingest`, `proxies`, `drives`, `export`) — the GUI calls the same core.

Keep the existing repo layout. New modules for the missing thesis parts: `core/ingest.py`, `cards.py`, `manifest.py`, `proxies.py`, `drives.py`, `audio_tags.py`, `export.py`, `jobs.py`; presets in `presets/export/*.yaml` and `presets/proxy/*.yaml`; tests for hashing/verify (incl. simulated corruption), resume, multi-drive apply and export.

## 6. Pipeline

### 6.1 Ingest (cards → several drives at once)
- Detect inserted cards by watching `/Volumes`; recognize the card type by structure (Sony `PRIVATE/M4ROOT/CLIP`, generic `DCIM`, DJI `DCIM/DJI_*` / `DCIM/100MEDIA`, audio recorders). The user labels the source once (e.g. `cam apos`, `cam dim`, `drone`, `sound`); remember the label by camera/card identity.
- The user picks a project (new or existing) and 1–N destination drives. Each destination gets the same structure: `<project>/<source label>/…`.
- **Pre-flight**: check free space on every destination ≥ card data + proxy estimate + margin; block with a clear message if not.
- **Read once, write many**: read each file from the card once, hash while reading, write to all destinations in parallel. Then **verify** every destination copy by re-reading and hashing. Mismatch → retry that file on that destination, then flag clearly.
- **Resumable**: skip files already ingested and verified (same relative path, size and hash); safe to re-insert a card or resume after a crash.
- Write a checksum manifest + ingest report per destination (files, sizes, hashes, verify status, time, throughput).
- Live progress per destination (MB/s, ETA), and a final "safe to format" status only when everything verified (the app never formats the card itself).
- Prove it in tests: a fake card, two destination folders, and a deliberately corrupted copy that verification must catch.

### 6.2 Proxies (background)
- Start a proxy job as soon as a file is verified; low priority; never slows ingest noticeably (limit concurrency).
- Presets: ProRes Proxy (default) or H.264, with resolution presets; hardware encoding where possible.
- Stored as `<project>/Proxies/<same relative path>/<same base name>.mov` so Premiere's "Attach Proxies" works; proxies follow their clip when files are organized.
- Resumable queue with status in the UI. Frame extraction and audio analysis use proxies when available (much faster).

### 6.3 Scan, clock sync, checks
- Walk the source folders; group sidecars with their clip; ffprobe duration, resolution, fps, codec, `creation_time`.
- Capture time, best source first: Sony XML sidecar, DJI file-name timestamp / `.SRT`, container `creation_time`, file mtime last. Handle time zones (Greece).
- **Per-camera clock offset**: detect automatically by finding the same moment on two cameras (**audio cross-correlation** first, frame similarity as backup), propose the offset, the user confirms or edits. Test case: camera A in the baptism example (+14:00).
- Duplicates (size → partial hash → full hash) and corrupt / zero-length files: flag only.

### 6.4 Frames — dense by design
- Default **1 frame every 2 s** plus extra frames at scene changes; no per-clip cap; density is a setting. Follow the workflow docs if they used a different method.
- One decode pass per clip, parallel, from proxies / DJI `.LRF` when present.
- Tile into **contact sheets** (e.g. 6×4, timestamp labels) sized for the API; long clips get several sheets.
- Cache everything; show an **estimate of API cost and time** before calling the API; the user confirms.

### 6.5 Audio analysis
- Per clip, over time: loudness and silence profile, audio-event tags (speech, singing/chanting, music, applause, cheering, crowd, bells, …) with timestamps.
- Summarize as compact text features for the model (e.g. "0–40 s chanting, organ; 40–55 s applause") — no raw audio to the API.
- Also used for clock sync (6.3). Reuse `core/audio.py` (cached mono audio) and `core/transcribe.py` (local Whisper).

### 6.6 Automatic sorting (two passes)
- **Pass 1 — describe every clip** (parallel): contact sheets + corrected time + duration + camera + audio features → JSON: what/who/where, shot type (wide / close-up / detail / portrait / aerial), continuous take vs cutaway, notable moments, audio context, quality issues, optional star suggestion.
- **Pass 2 — build the event structure** (one call over the whole event): all clip descriptions on the corrected timeline, the preset hints and the workflow rules → the event's moments in chronological order with Greeklish folder names and numbers, ΡΟΗ / B-ROLL splits where they apply, drone folder, `99 AXRISTA` if needed, a Greek one-line description per moment, and the assignment of every clip with a confidence.
- **Smoothing / validation**: fix isolated outliers that contradict their time neighbors; every clip assigned once; numbering follows the timeline. Low confidence → "Needs review".
- **Offline fallback**: time-gap + audio segmentation with generic names when there is no internet or API key.

### 6.7 Evaluation (the thesis results — do this early)
- Input: an already-organized project (wedding 25 July primary, baptism 073 secondary). Ground truth = the folder each clip is in. Run read-only, hiding names/paths from the model.
- Category names differ between runs, so use **grouping metrics**: Hungarian matching of predicted to true folders → matched accuracy and per-folder precision/recall; pairwise precision / recall / F1; Adjusted Rand Index; number of folders predicted vs true; boundary alignment on the timeline; clock-offset detection; cost and runtime.
- **Ablation study** (key thesis result): time only vs time + camera vs + image vs + audio vs all signals; and frame density (1/4 s vs 1/2 s vs 1/1 s) on a subset.
- **Ingest benchmark**: throughput with 1 / 2 / 3 destinations, verify overhead, proxy background impact.
- Save Markdown + JSON in `reports/` (git-ignored if it contains client names). Iterate until the numbers are clearly good; report them to the user.

### 6.8 Review → organize
- Review screen: categories with thumbnails; hover to scrub frames; play the proxy; drag clips between categories; rename / merge / split / reorder categories; filter "Needs review"; toggle ⭐.
- After approval: **apply the same organization on every destination copy** so all drives stay identical (verify hash before moving), sidecars and proxies included. Source folders stay (empty). File renaming **off by default** (camera names kept).
- Journal per drive (Application Support + `<project>/.hypershutter/journal.json`); one-click **Undo**.
- Generate the shot index (4.5) and the contact sheets folder (one sheet per category, named by number).

### 6.9 Drive monitoring
- Live view of connected drives: capacity, used, free, project size, proxies size, projected space after ingest/proxies/export.
- Warnings at configurable thresholds; ingest and export check space before starting.

### 6.10 Batch export with presets
- Select clips, whole categories or the whole project → export queue (per-clip transcodes; **no cutting or editing**).
- Editable presets in `presets/export/*.yaml`, e.g. H.264 1080p review copies, HEVC 4K archive, ProRes 422 LT; optional LUT, resolution, bitrate, audio settings, naming.
- Output mirrors the category structure; queue with progress, pause/resume, free-space check first.

## 7. The app (sections like a real Mac app)

- **First-run onboarding**: welcome, language, ffmpeg check, API key (Keychain), default destination drives.
- **Projects / Home**: recent projects, new project (event type, names, date, optional day schedule).
- **Ingest**: detected cards, source labels, destinations, pre-flight, live progress, verify status, reports.
- **Analyze**: progress for scan, clock sync, checks, frames, audio, sorting; cost estimate and confirm.
- **Review**: the main screen (6.8).
- **Export**: batch export queue and presets (6.10).
- **Drives**: drive monitoring (6.9); a compact drive status also visible in the sidebar.
- **Background jobs** indicator (proxies, exports).
- **Accuracy Lab**: evaluation runs and reports (6.7).
- **Settings**: language, AI model, frame density, sorting preset hints and naming style, per-camera clock offsets, hash algorithm, proxy preset, export presets, warning thresholds, API key.
- **Features** — "What HyperShutter can do".
- **Help & Support**: FAQ, "Contact support" (Mail with a pre-filled message to a support address from config — placeholder until given), "Report a bug" (GitHub Issues), "Export diagnostics" (logs and settings only — never footage or the API key).
- **About**: version, credits, licenses.
- Standard macOS menu bar and keyboard shortcuts.

### Languages
- **English (default) and Greek**, switchable in Settings and onboarding. Every UI string goes through `locales/en.json` / `locales/el.json`. Folder names on disk are always Greeklish (4.3).

## 8. Design (polish AFTER the core works — tokens in place from day one)

Look and feel: **professional, calm, luxurious**, like a premium native Mac app.

- **Fonts**: system stack `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui`; optional `ui-serif` (New York) for large headings. Do **not** bundle Apple font files.
- **Colors** (`ui/css/tokens.css`): `--hs-white: #FFFFFF` background · `--hs-gold: #A59769` accent · `--hs-slate: #405366` primary, text, primary buttons. Derived tints/shades allowed.
- **Accessibility**: gold on white ≈ 2.8:1 — too low for text. Gold only for hairlines, icons, focus rings, active states, very large display elements. Text and buttons in slate (~8:1).
- Luxury cues: generous whitespace, 1px gold hairlines, small uppercase labels with letter spacing, large thumbnails, restrained 200–300 ms animations, no emoji, no loud gradients, native-feeling sidebar.
- Imagery: at most one or two photos (e.g. onboarding); ask the user only in the design phase.
- Logo and icon: provided later in `assets/branding/` (SVG + 1024px PNG); text placeholder until then.

## 9. GitHub

- Check `gh auth status`; if needed install with Homebrew and ask the user to run `gh auth login` himself.
- **Private** repository `hypershutter` (can go public later for the CV).
- `.gitignore`: venv, caches, frames, proxies, `reports/` with client data, `.env`, `*.app` build output, macOS junk.
- **Commit and push after every working change** (clear English messages). Tag `v0.1.0` at the first packaged `.app`.
- Keep `README.md` current: what it is, install/run, architecture diagram, evaluation and benchmark results.

## 10. Status and remaining work

**Done before the scope change (7 Nov 2026) — keep it:** scan, clock sync from audio, checks; dense frames and contact sheets with cost estimate; two-pass sorting with offline fallback and evaluation (results in 4.6); app shell with Projects, Scan & Analyze, Review (move / rename / merge / split / reorder / stars), Accuracy Lab; apply with write-ahead journal, undo, verified backup, shot index and per-folder contact sheets.

**Remaining, back to back** (Greek summary + commit + push after each):

- **T1 — Scope cleanup**: create branch `edit-prep` from the current `main` to keep the editing work. On `main`, remove everything for editing: `core/edit.py`, `edit_wedding.py`, `premiere.py`, `xmeml.py`, `preview.py`, `music.py`, `library.py`, `prproj.py`, the CLI commands `broll` / `premiere`, the Edit prep screen, their tests and preset keys (e.g. `highlights`). Keep `transcribe.py` and `audio.py` (audio analysis). Replace CLAUDE.md with this file; update README. Tests green.
- **T2 — Audio analysis in sorting + ablation study** (6.5, 6.6, 6.7): audio tags and Whisper phrases as text features in pass 1 / pass 2; then the ablation on the wedding and both baptisms (time only / + camera / + image / + audio / all) and the frame-density comparison. Reuse cached results where possible; run all of it without stopping to ask about cost. Write the results in `docs/` — this is the core of the thesis.
- **T3 — Ingest engine** (6.1), building on the verified-copy code already in `execute.py`; tests incl. simulated corruption; throughput benchmark with 1 / 2 / 3 destinations.
- **T4 — Background proxies + drive monitoring** (6.2, 6.9).
- **T5 — Multi-drive organize**: the same apply / undo on every destination copy (6.8).
- **T6 — Batch export with presets** (6.10).
- **T7 — App**: Ingest, Drives and Export screens, background-jobs indicator; finish onboarding, Settings, EN/EL, Features, Help & Support, About, menus.
- **T8 — Design pass** (section 8), logo and icon.
- **T9 — Ship**: package `HyperShutter.app`, README with architecture, evaluation and benchmarks, tag `v0.1.0`.
- **Stretch (only if time remains)**: drone clips grouped by GPS location; AI star suggestions.
