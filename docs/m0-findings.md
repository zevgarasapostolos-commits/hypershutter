# M0 findings: inputs, conventions and test targets

Written 2026-11-01 after reading the example baptism (read-only), the user's organizing
workflow export and the editing session's saved rules. No client names.

## Sources of truth

| What | Where |
|---|---|
| Organizing (scan, clocks, frames, categories, ΡΟΗ/B-ROLL, move, verify, index) | [workflow-organizing.md](workflow-organizing.md) — the user's own export |
| B-roll selection, highlights, ροή, Premiere XML, previews | out of the thesis scope; kept on the `edit-prep` branch |
| Category hints per event type | `presets/*.yaml` |

Earlier prototype scripts from those sessions (sync, motion, drone windows, XML writer, preview
renderer, prproj reader) are kept locally in `reference/legacy/` (git-ignored: they contain
client paths). They are the starting point for M1 and M6.

## Input layout

- Event folders live on two external drives **both named "T7"**; whichever mounts second becomes
  `T7 1`, so absolute paths swap between sessions. Never store `/Volumes/...` as identity; store
  paths relative to the event root and re-resolve.
- exFAT drives carry macOS `._*` AppleDouble files next to everything: always ignore them.
- Source folders vary (`camera`, `camera apos`, `cam apos`, `apos`, `CLIP`, `CLIP2`, `camera dim`,
  `cam dim`, `dim`, `camera dim/CLIP2/`, `drone`, `DRONE`, `DRONE2`, `Mavic`, `sound`, `Hxos/...`,
  `music`). Detect cameras by **file pattern + codec/resolution**, not folder name.
- Root may already hold `.prproj`, exported `… ροή.xml` / `… highlights.xml`, previews and
  `Adobe Premiere Pro *` folders: never touch them; if a project references the clips, moving
  breaks links → ask first and give relink instructions (file names never change, so
  Link Media → Locate → Search subfolders relinks everything).

## Cameras seen

| Source | Pattern | Format | Clock |
|---|---|---|---|
| Main camera (Sony) | `C3xxx`/`C4xxx.MP4` | H.264 4K50 8-bit 4:2:0, pcm_s16be stereo; dance clips sometimes 1080p25 | **wrong**, ~+14:00 vs raw `creation_time` |
| Second camera (Sony, incl. A7 IV) | `C6xxx.MP4` (+ `C6xxxM01.XML`) | 4K50 or 1080p, H.264 (A7 IV may be 4:2:2 10-bit) | UTC → +3 h summer |
| Drone (DJI) | `DJI_YYYYMMDDhhmmss_NNNN_D.MP4` (+ `.LRF`/`.SRT`) | H.264/HEVC 4K50 + mjpeg thumbnail stream | UTC → +3 h; file name = local time |
| Audio recorders | `DJI_0N_YYYYMMDD_hhmmss.WAV` in `sound/` | WAV | file name = local start |
| Wedding cams (one event) | Fx30 HEVC 10-bit 4K50; A7 IV 1080p50 4:2:2 | | each its own offset |

`CLIP2` is not necessarily a second camera: same numbering series + same codec = same camera,
another card/day. Two DJI number series can be two cards or two drones; they go to one folder.

## Clock convention (for M1)

Offsets are expressed against the **raw `creation_time` value** (as the user's index does):
`corrected_local = raw_creation_time + offset`. Correct-clock UTC cameras get the time-zone
offset (+03:00 in summer, +02:00 in winter, from Europe/Athens for that date).

**M1 test target (example baptism):** camera A `C4255` raw 02:59:15 → 16:59:15 ⇒ **A = +14:00:00**;
camera B `C6507` raw 14:00:46 ⇒ B = +03:00 plus a measured **+44 s** drift ⇒ **+03:00:44**;
drone = +03:00 (file name agrees). Confirmation pairs from the user's index: `C6507` falls inside
`C4255`; `C6512` (immersion close-up) falls inside `C4288` (immersion wide).

## Example output format (the finished baptism)

- 17 category folders, 267 clips (A 241, B 7, DJI 19), source folders left empty.
- `00 CONTACT SHEETS/NN.jpg`: one per folder, 7 columns, ~280 px tiles, black background, yellow
  label `clip HH:MM dur` (corrected time), chronological. ffmpeg here has **no drawtext** →
  labels must be drawn with Pillow.
- Shot index: see §9.2 of workflow-organizing.md (title, bold summary, camera legend, clock note,
  Χρονολόγιο, pointer to sheets, per folder: description, `**N πλάνα · X λεπτά**`, table).
- Drone folder is numbered where the first drone clip falls in the day (05 here, 02 elsewhere).
- Premiere XMLs: xmeml v4, 25 fps, markers in Greek; previews 960×540.

## Evaluation ground truth (for M3)

- Baptism example: folder membership of each clip.
- Older organized events (067–071) also have indexes and folders → more evaluation data.
- The 25-07 wedding (folder `gamos 25-07` on the T7, confirmed by the user) currently has its clips back in `CLIP`/`CLIP2`/`CLIP3`/`DRONE*`, but its
  `00 ΕΥΡΕΤΗΡΙΟ ΠΛΑΝΩΝ.md` still lists every clip's category → the evaluator must also accept the
  **index file as ground truth**. That event is a wedding + baptism on the same day.

## Organizing method actually used (vs. the brief)

The user's sessions used **3 frames per clip at 15/50/85 %** (never the first second) and one
long pass of a human-like reading of all sheets. The brief asks for dense frames (1 per 2 s +
scene changes) for accuracy; M2/M3 will compare densities on a subset (university report).
The first 3–6 s of most clips show the floor; descriptions must not be dominated by them.
