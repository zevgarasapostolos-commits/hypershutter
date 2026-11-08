# T3: Ingest (cards to several drives at once, verified)

Code: `hypershutter/core/cards.py`, `ingest.py`, `manifest.py`. Tests: `tests/test_ingest.py`.
CLI: `hypershutter ingest`. App: the Ingest screen. Benchmark: `scripts/bench_ingest.py`.

## Cards

- **Detection by structure only.** A volume counts as a card when it has the card's own folders:
  - `DCIM` (generic, and DJI drones when the files are `DJI_*`);
  - `PRIVATE/M4ROOT` (Sony XAVC), `PRIVATE/XDROOT` (XDCAM) or `PRIVATE/AVCHD`;
  - recorder folders (`ZOOM`, `FOLDER01`, `MUSIC`, `SOUND`, `RECORD…`);
  - or WAVs at the root of a volume smaller than 512 GB.

  A working drive full of event folders is never taken for a card and never walked. An early
  version used "any loose audio file at the root" and walked whole drives; that rule was removed.
- **What is copied.** Media and sidecars (`.MP4 .MOV .MXF .MTS`, audio, `.XML .SRT .LRF .THM`).
  The camera's own low-res proxies (Sony `SUB/`) and thumbnails are left out.
- **Identity and labels.**
  - Sony cards are identified by camera model and serial, read from the clip XML.
  - Other cards are identified by the volume UUID.
  - The source label the videographer gives a camera once (e.g. `cam apos`, `cam dim`, `drone`)
    is remembered for that camera.

## Copy and verify

1. **Plan.**
   - Card files go to `<drive>/<event>/<label>/`, flat. Camera folders like
     `PRIVATE/M4ROOT/CLIP` and `DCIM/100MEDIA` are dropped.
   - When two files share a name, they keep their card sub-folders.
2. **Pre-flight**, per physical drive, so two destinations on one drive add up:
   - the space must cover the card data not yet there, plus the proxies on the first
     destination (35% of the source for ProRes Proxy), plus a margin (1 GB + 1%);
   - every destination must be writable;
   - no destination may sit on the card.
3. **Read once, write many.**
   - Each file is read from the card once, in 8 MB chunks.
   - The chunks are hashed (xxHash64) while reading.
   - The same chunks go to one writer thread per drive, through bounded queues (4 chunks each).
   - Each copy is written to a hidden temporary file, then `fsync`, then renamed. It gets the
     card file's modification time, so the caches keyed by name, size and time work on every copy.
4. **Verify.**
   - When all files are copied, every drive is read back in parallel and the hashes compared
     with the card's.
   - The reads use `F_NOCACHE`, so the check reads the disk and not the copy still in the page cache.
5. **Retry.**
   - A mismatch is copied again from the card and verified again, up to 2 times.
   - The bad copy is set aside, never deleted.
   - If the card reads differently twice, the file is flagged.
6. **Verdict.** The card is *safe to format* only when every file is verified on every drive.
   HyperShutter never formats a card.

Nothing is overwritten. A different file already at a place (e.g. a second card whose camera
counter started again, another `C0001.MP4`) sends the card's file to `<label>/<card name>/` on
every drive, so the drives stay identical. A source is identified by its card path and its
modification time.

## Manifests and reports (on every destination)

- **`<event>/.hypershutter/ingest/manifest.json`**
  - Records every file with its size, xxHash64 and status (`copied` → `verified`), and where it
    is now (`now`, after organizing).
  - Makes ingest resumable: verified files are skipped, files copied but not verified are only
    verified, and the space check counts only what must still be written. A whole file the
    manifest had not yet recorded is compared with the card the same way.
  - Re-inserting a card after the event was organized copies nothing.
- **`<event>/<label>/<label>_<session>.mhl`** — an ASC MHL v1.1 hash list (`xxhash64be`), readable
  by Silverstack, ShotPut Pro, Hedge and `mhl verify`.
- **`<event>/.hypershutter/ingest/<session>-<label>.json`** — the report: files, hashes, status,
  times, write and verify throughput, the verdict. A copy also goes to Application Support for
  the app's history.

## Tests (all pass)

| Test | What it proves |
|---|---|
| Fake Sony / DJI / recorder cards | recognized by structure; Sony camera proxies left out |
| Ingest to two drives | identical copies with the card's times, sidecars next to their clips, manifests all verified, MHL and report written, **the card byte-for-byte unchanged** (sizes, times, MD5 of every file) |
| A copy corrupted once on drive B | caught by verification, copied again, verified; the bad copy kept aside |
| A copy corrupted every time | flagged with its drive and file; **not safe to format** |
| Interrupted before verifying one file | the second run copies that one file only (1 copied, 5 skipped) |
| A second card with the same names | goes to `<label>/card2/`; the first card's files untouched |
| Pre-flight | refuses a destination on the card, and a drive without space |
| A big drive with loose audio at the root | not a card; a small one with WAVs is a recorder |

## Benchmark (fake card on the internal SSD, 38 files, 3.09 GB)

Run with `scripts/bench_ingest.py`. The drives were: T7 (USB SSD, 92% full), Expansion (USB hard
disk), T7 1 (USB SSD, 99% full). Whisper and frame extraction were reading from T7 1 at the same
time, so the 3-drive row is pessimistic.

| Destinations | Card read (MB/s) | Total written (MB/s) | Copy (s) | Verify (s) | Verify share | Safe |
|---|---|---|---|---|---|---|
| 1 (T7) | 203 | 203 | 15.2 | 5.5 | 26% | yes |
| 2 (T7 + Expansion) | 81 | 163 | 38.0 | 33.5 | 47% | yes |
| 3 (+ T7 1) | 49 | 148 | 62.5 | 54.3 | 46% | yes |

Per drive, verification read the SSDs at 560–625 MB/s and the hard disk at 57–92 MB/s.

- **The slowest drive sets the pace.** The card is read once, so every destination receives each
  chunk, and the bounded queues stop a fast drive from running far ahead of a slow one. With the
  hard disk in the set, the card is read at the disk's speed. In return the total written grows
  (148–203 MB/s), and the card is read once instead of once per drive.
- **Verification costs a quarter to a half of the time**, and more with a hard disk. It is the
  price of the guarantee: without reading back, a write error or a bad cable goes unnoticed.
- **`F_NOCACHE` costs nothing here.** A separate test wrote 0.87 GB to T7 at 118 MB/s with the
  page cache and 145 MB/s without it. The limit was the drive itself on this port and fill level.

### With proxies in the background (1 drive, ProRes Proxy)

| Card read (MB/s) | Proxies | Footage (s) | Proxy time (s) | Speed vs real time | Proxy size |
|---|---|---|---|---|---|
| 130 | 19 of 19 done | 122 | 340 | 0.36× | 1.1 GB for 3.09 GB of 4K |

- Proxies start as soon as each clip is verified, at background priority (`taskpolicy -b`), one
  at a time.
- The copy ran at 130 MB/s, against 118–203 MB/s for the same drive without proxies.
- Background priority throttles the proxies hard (0.36× real time, decoding 10-bit 4:2:2 H.264 on
  the CPU). They are meant to finish while the next card copies, not to race the ingest.
- The proxies came out at 36% of the source size, close to the 35% the pre-flight assumes.

## First real card (8 Nov 2026)

A Sony ILCE-7M5 card from a real event, copied to two drives: a USB SSD and a much slower external
drive.

| Measure | Result |
|---|---|
| Files | 497 (248 clips and their sidecars), 99.09 GB |
| Verified | 497 of 497 on both drives, identical hashes, no retries |
| Copy | 34.1 min, 48.5 MB/s to each drive at once |
| Verify | 3.4 min on the SSD (492 MB/s), 19.9 min on the slower drive (83 MB/s) |
| Whole ingest | 54.1 min |
| Proxies (ProRes Proxy 1080p 50) | 248 clips, 41.57 GB, 42% of the source, median 73.5 Mb/s |

The test changed two things:

- **Resume.** Whole files left by an interrupted copy are now verified instead of being written
  again, which would have needed the space twice.
- **Proxy space.** A fixed 35% of the source size underestimated this card (34.7 GB against 41.6 GB).
  A proxy's size follows the clip's length and frame rate, so the space check now reads the length
  and frame rate of a sample of 16 clips and applies the preset's bitrate (on this card: 42.0 GB estimated, 41.6 GB real).
