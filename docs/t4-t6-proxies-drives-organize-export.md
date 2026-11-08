# T4–T6: proxies, drive monitoring, multi-drive organize, batch export

## T4a: background proxies

Code: `core/jobs.py` (the queue), `core/proxies.py`; presets in `presets/proxy/*.yaml`.
CLI: `hypershutter proxies`. App: the Drives screen and the sidebar.

- **Queue.**
  - A SQLite job queue in Application Support, shared by proxies and exports.
  - It survives a crash or a restart: running jobs go back to the queue, and partial outputs
    (hidden `.hspart` files) are written again.
  - It can be paused and resumed. One bad clip fails its own job only.
- **Priority.** ffmpeg runs under `taskpolicy -b` (macOS background QoS: throttled CPU and disk),
  one proxy at a time, so ingest and the app stay responsive.
- **Presets.**
  - ProRes Proxy 1080p (default). It runs on the Apple silicon ProRes engine
    (`prores_videotoolbox`), with `prores_ks` as the fallback.
  - H.264 720p for a laptop.
  - Each preset keeps every audio stream and the source metadata (timecode), as Premiere's
    *Attach Proxies* needs.
- **Place.** `<event>/Proxies/<the clip's folder>/<clip name>.mov`.
  - The scan skips `Proxies/` and `Exports/`, so proxies are never sorted as footage.
  - When the event is organized, each proxy moves with its clip.
- **Use.** Frame extraction and the sound analysis read the proxy when it exists (1080p instead
  of 4K). The caches are keyed by the original clip, so the results are the same.
- **Trigger.** During ingest, each clip verified on the first drive is queued at once.

Measured (docs/t3-ingest.md): 4K 10-bit 4:2:2 → ProRes Proxy at 0.36× real time under
background priority, at 36% of the source size.

## T4b: drive monitoring

Code: `core/drives.py`. CLI: `hypershutter drives`. App: the Drives screen, plus warnings in the
sidebar.

- **What it shows.** Every mounted drive with:
  - total, used and free space;
  - the known events on it, with the size of their footage (from the project) and of their
    proxies;
  - the bytes the queued proxy and export jobs will still write there;
  - the free space left after that work.
- **Never walks a drive.** Sizes come from what Wigroom already knows.
- **Volumes listed once.** Volumes of the same APFS container are shown once.
- **Status.** `ok` / `warn` / `critical`, from thresholds in Settings: warn under 50 GB or 10%,
  critical under 10 GB.
- **Checks before work.** Ingest checks space before it starts (pre-flight), and so does export
  (`drives.check_space`).

## T5: multi-drive organize

Code: `core/execute.py` (`apply_everywhere`, `undo_everywhere`, `copies`, `check_same`).
Tests: `tests/test_multidrive.py`.

- **Which copies.**
  - Ingest records every destination of an event (Application Support `copies.json`, keyed by
    the event folder name).
  - Organize and undo act on the main copy and on every connected copy, or on `--mirror` folders.
- **All or nothing.**
  - Every copy gets its own plan, and every plan must be free of conflicts.
  - Every file to move must be on each copy with the same size and the same xxHash64 as on the
    main drive. The hashes come from the two ingest manifests; without manifests the files are
    hashed now.
  - If one copy differs, **nothing moves on any drive**.
- **Journals.** Each drive has its own journal, written before the first move:
  - one in Application Support, matched by root;
  - one in `<event>/.hypershutter/journal.json`, which still identifies the drive after it
    re-mounts under another name.
  - `undo_everywhere` reverses each drive's last run.
- **Proxies and manifests follow.**
  - Proxies move with their clips, and nested folders (`Proxies/05 …`) are created level by level.
  - The ingest manifest records where each card file is now, and undo resets it.
- **Generated files.** The shot index and the contact sheets are written on every copy, so the
  drives stay identical.

Tests:
- Organize on two drives, then undo: both drives end with the same files at the same places, the
  proxy followed its clip, the manifest knows the new places, there is one journal per drive, and
  both drives come back byte-for-byte to the snapshot from before.
- A copy whose checksum disagrees stops the whole organize, and nothing moves anywhere.

## T6: batch export with presets

Code: `core/export.py`; presets in `presets/export/*.yaml`. CLI: `hypershutter export`. App: the
Export screen. Tests: `tests/test_export.py`.

- **No editing.** Each output is one clip, transcoded at full length.
- **Choice.** Single clips, whole categories (by number or key), or the whole event.
- **Presets** (editable YAML):

  | Preset | Video | Audio |
  |---|---|---|
  | H.264 1080p review copy | 12 Mb/s | AAC |
  | HEVC 4K archive | 45 Mb/s | PCM |
  | ProRes 422 LT | source size | PCM |

  Each preset can also set an optional `.cube` LUT and a naming pattern (`{name}`, `{folder}`,
  `{n}`). Hardware encoders are used first, with software fallbacks.
- **Output.** `<destination>/<preset>/<category folder>/<name>.<ext>`.
  - The default destination is `<event>/Exports`, which the scan ignores.
  - A read-only reference event must be exported elsewhere.
- **Safety.**
  - The space needed (from the preset's bitrate and the clip lengths) is checked first.
  - Nothing is overwritten: a new name gets « (2)».
  - Exports run on the shared background queue, with pause and resume.

Tests:
- The output folders mirror the categories.
- An output keeps the clip's length (3.0 s in, 3.0 s out).
- An existing file is left alone, and the export gets « (2)».
- Nothing is written next to the camera files.
- The space check refuses when needed.
- A paused queue runs nothing until it is resumed.
