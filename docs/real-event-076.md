# The first real card: event 076

The whole system on a real memory card from a real event, on 8 November 2026, after development.
The event played no part in tuning the sorting rules.

- **Event:** a baptism, shot on one camera (Sony ILCE-7M5).
- **Card:** 248 clips and their sidecars, 497 files, 99.09 GB, read-only.
- **Drives:** a USB SSD (first, holds the proxies) and a much slower external drive.

## Results

| Step | Measure | Result |
|---|---|---|
| Ingest | Verified | 497 of 497 files on both drives, no retries |
| | Copy | 34.1 min, 48.5 MB/s to each drive at once |
| | Verify | 3.4 min on the SSD, 19.9 min on the slower drive |
| | Whole ingest | 54.1 min |
| Proxies | Output | 248 clips, 41.57 GB, 42% of the source |
| | Space estimate | 42.0 GB (+1.0%) |
| Sorting | Proposal | 15 folders for 248 clips, 3 clips flagged "needs review" |
| | Corrections in Review | none: no clip moved, no folder renamed, merged or split |
| Organize | Moves | 496 files on each drive, plus the 248 proxies on the first |
| | Copies compared | same placement, same xxHash64 on both drives, nothing missing |
| | Generated | shot index and one contact sheet per folder on both drives |
| Export | H.264 1080p, 2 clips | same length as the source (234.24 s, 366.24 s); originals still match their checksums |

The sorting's second pass used 39,669 input and 12,273 output tokens in 98 s. The first pass was not
timed separately in this run; at the wedding's cost per clip it comes to about $7.

## What this result does not prove

- It is one event, a baptism, not a wedding. Accuracy against independent folders is in
  [t2-sound-and-ablation.md](t2-sound-and-ablation.md).
- "No corrections" means the reviewer accepted the proposal. It is not an independent ground truth,
  and the reviewer is the author of the system.
- There was one camera, so this run did not exercise the clock synchronization between cameras.

## What the real run found

| Found | Fix |
|---|---|
| After an interruption, whole files were written again and the old copies kept, needing the space twice | They are verified against the card's hash instead of being rewritten |
| The space check for proxies used a fixed 35% of the source size (34.7 GB against 41.6 GB) | Clip length × frame rate × the preset's bitrate, from a sample of 16 clips |
| A finished proxy still counted as space needed when a card was inserted again | Proxies already made are left out, also after organizing |
| The event name was pre-filled from a folder opened on the card itself | A folder on the card is no longer used as the event name |
| A placeholder camera serial made two bodies of the same model look like one | Such a card is identified by its own volume |
| The language was lost at every launch | The saved setting decides |
| Checkboxes in the Export screen overlapped their labels | Checkboxes keep their own size |
| The Drives table overflowed the smallest window | Only the numbers stay on one line |
