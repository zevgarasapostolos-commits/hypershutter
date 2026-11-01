# M1: scan, clock sync and checks

## What it does

1. **Scan** (`core/scan.py`, read-only): walks the event folder, ignores `._*` files, the event
   root (project files, exported XMLs, previews), `music/` and Premiere folders. Video and audio
   files become clips; `.XML` (Sony `CxxxxM01.XML`), `.SRT`, `.LRF`, `.THM` become sidecars of
   the clip with the same stem in the same folder. ffprobe runs in parallel (6 workers) and is
   cached in SQLite by (file name, size, mtime), so a re-mounted drive or a moved file is not
   probed again.
2. **Devices**: DJI video → `DJI`; recorders (`DJI_0N_…WAV` or other audio) → `REC…`; cameras are
   grouped by Sony serial number when an XML sidecar exists, otherwise by file-number series
   (a gap of more than 500 numbers = another camera; a continuation within 50 = the same camera on
   another card). The camera with most clips is `A`, then `B`, …
3. **Capture time**, best source first: Sony XML `CreationDate` (local) → DJI file name (local) →
   recorder file name (local) → DJI `.SRT` (local) → container `creation_time` (UTC, converted
   with Europe/Athens incl. DST) → file mtime. All sources have 1 s resolution.
4. **Checks** (`core/checks.py`): zero-length, unreadable, no duration, missing stream → corrupt;
   duplicates by size → xxh3 hash of first+last MiB → full xxh3 hash. Flags only.
5. **Clock sync** (`core/sync.py`):
   - The **anchor** is the audio device with the most trusted clock (DJI/GPS > Sony XML >
     creation_time > recorder file name), weighted by how plausible its times are next to the
     drone's GPS-based times (± 2 h), or, without a drone, by whether its median clip falls after
     09:00. DJI Mic recorders rank last: their clocks were 24 and 46 min off in the two events checked.
   - Every other audio device is matched against the anchor (or an already synced device):
     up to 16 "needles" (≤ 30 s segments, one every 5 min of long recordings, spread over the day)
     from the device with less audio are searched with **normalized cross-correlation** (4 kHz
     mono) inside the other device's audio, concatenated in 10-min blocks. Masters (20 s – 15 min)
     are searched first; all clips only if that is not decisive.
   - Each needle votes for a relative offset; votes within 2 s agree (creation_time has 1 s
     resolution); a decision needs two agreeing votes with peak-to-sidelobe ratio (PSR) ≥ 9, or
     one ≥ 25. The agreeing pairs are kept as evidence ("C6512 falls inside C4288") for the index.
   - Offsets are shown as the user states them: relative to what the camera clock wrote.
     Manual override: `hypershutter sync <folder> --set A=+14:00 --manual-only`.

## Correlation method: NCC vs GCC-PHAT

GCC-PHAT is the textbook choice for time-delay estimation, so it was tried first. On real
footage it failed: the needles of camera B (Sony A7 IV on-camera mic) against camera A masters
in a reverberant church. Comparison over every B needle against the A masters (correct = within
2 s of the true offset; PSR of the best peak):

| Method | 071 correct | PSR correct | worst false PSR | 073 correct | PSR correct | worst false PSR |
|---|---|---|---|---|---|---|
| GCC-PHAT | 0/6 | – | 16.3 | 4/7 | 36, 19, 16, 13 | 10.1 |
| PHAT β = 0.7 | 1/6 | 27 | 17.3 | 4/7 | 46, 25, 24, 16 | 10.4 |
| PHAT β = 0.5 | 2/6 | 33, 17 | 14.1 | 4/7 | 50, 31, 26, 19 | 11.1 |
| plain cross-correlation | 2/6 | 26, 19 | 16.5 | 4/7 | 49, 39, 24, 21 | 14.9 |
| **NCC (chosen)** | **3/6** | **50, 19, 17** | **10.6** | 4/7 | 41, 27, 27, 16 | 11.9 |
| NCC + 150–1800 Hz band-pass | 3/6 | 48, 22, 18 | 11.0 | 4/7 | 40, 26, 26, 15 | 12.0 |

Full whitening amplifies exactly what differs between two cameras (room reverb, hiss, mic
colouration); NCC keeps the loud shared events (voice, bells, crying) and normalizes for the
loudness of each haystack window. The remaining misses are needles that only partly overlap a
master or fall in clips shorter than 20 s. With PSR ≥ 9 and two agreeing votes, no false offset
was accepted in either event.

## Results

| Event | Devices | Anchor | Measured | Expected | Evidence |
|---|---|---|---|---|---|
| Example baptism (073), no mic | A 241, B 7, DJI 19 | B (creation_time) | **A +13:59:16** | A +14:00 with B +03:00:44 (index + editing session) → same A−B difference | C6512 ⊂ C4288 (the immersion, as in the index) PSR 41; C6513 ⊂ C4288 27; C6509 ↔ C4259 27 |
| Second baptism (071), same day, with mic | A 232, B 6 (A7 IV, XML), DJI 11, REC 2 | B (Sony XML) | **A +13:59:16**, REC +00:24:08 | A ≈ +14:00 (index) | C6505, C6506 ⊂ C4088 (PSR 18–19); REC: C6501, C6503, C6506 ⊂ DJI_03/04 (PSR 51, 24, 25) |

Camera A is the same camera on the same day in both events, and the two independent measurements
agree to the second (+13:59:16). The 44 s difference to the user's "+14:00" is not an error:
the index fixed camera A at exactly +14:00 and shifted B by 44 s; we keep B (Sony clock with
zone, or true UTC) as the anchor and shift A. The relative alignment, which is what
categorization and multicam cutting need, is identical. The drone (GPS time) has no audio, so it
cannot arbitrate which of A/B is exact to the second.

The lapel recorder of 071 was 24 min behind. An early version trusted recorder file names over
cameras and produced a wrong B offset; recorders now rank last.

Runtime on the USB-C SSD: scan 10 s (267 clips, ffprobe ×6 in parallel), first sync 5–10 s, then
instant (probe results and 4 kHz audio are cached in Application Support).

Read-only check: names, sizes and mtimes of every entry in both event folders were identical
before and after scan + sync. The 071 scan also flagged a real duplicate (`C4090.MP4` exists in
two folders), as a flag only.
