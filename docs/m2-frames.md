# M2: frames and contact sheets

## Frame extraction

- **Density**: one frame every `interval` seconds (Settings: 1, 2 or 4; default 2), centred in
  the clip (a 5 s clip gives 1.5 s and 3.5 s; anything shorter than the interval gets its middle
  frame). No per-clip cap: a 15-min dance gives ~450 frames.
- **Scene changes**: consecutive samples are compared (mean absolute difference of 64×36 grey
  thumbnails); where it exceeds 0.12, the midpoint frame is added as well, so a short distinct
  moment between two samples is not missed.
- **DJI `.LRF`** proxies are decoded instead of the 4K file when present (same frames, much faster).
- **Cache**: `~/Library/Application Support/HyperShutter/cache/frames/<clip>/<settings>/`, keyed by
  file name + size + mtime (not the path), plus `frames.json`. Changing the density or frame width
  creates a new cache folder; nothing is re-extracted otherwise.

### Why per-frame keyframe seeking instead of one decode pass per clip

The brief suggested one ffmpeg pass per clip (fps filter + scene select + downscale). Measured on
a 2:15 4K50 H.264 master (150 Mb/s, USB-C SSD, 11-core Apple silicon), 67 frames at 1 per 2 s:

| Method | Time | Footage speed |
|---|---|---|
| one pass, full software decode, `fps=0.5` | 37.3 s | 3.6× real time |
| one pass, full VideoToolbox decode, `fps=0.5` | 80.9 s | 1.7× |
| one pass, keyframes only (`-skip_frame nokey`), all keyframes | 21.3 s | 6.3× |
| per frame: `-noaccurate_seek -ss t`, 6 in parallel | 13.7 s | 9.9× |
| per frame + `-threads 1`, 10 in parallel | 10.4 s | 13× |
| **per frame + `-skip_frame nokey`, 6 in parallel (chosen)** | **5.0 s** | **27×** |
| raw file read (`cat`) | 2.8 s | – |

The cameras write a keyframe every 0.48 s (Sony) or 0.6 s (DJI), so seeking to the keyframe at
or before each sample time lands within half a second of it, and only the frames we keep are
decoded. Hardware decoding is slower here because every frame is copied back from the GPU.

## Contact sheets

- Sized for the high-resolution vision tier of the current models (Sonnet 5.5 / Opus 5.5:
  ≤ 2576 px long edge, ≤ 3.75 MP, ≈ w·h/750 tokens, capped ≈ 4784): 6 × 4 = 24 frames per sheet,
  2571 × 1067 px, tiles 425 × 239 px, ≈ 3,660 tokens per full sheet (≈ 150 tokens per frame).
  A clip's last sheet only has the rows it needs.
- Each tile is labelled **time in clip · corrected time of day** (e.g. `1:12 · 17:00:27`), in the
  yellow of the user's own sheets. **No file names or folder paths** ever appear on a sheet sent
  to the model.
- Rendered with Pillow (Homebrew's ffmpeg has no `drawtext`), cached next to the frames.

## Cost estimate

`hypershutter frames` ends with the estimated cost of describing every clip (pass 1) for each
model, from the real sheet sizes: image tokens + ~900 prompt tokens and ~450 output tokens per clip.
The app shows the same estimate and asks for confirmation before any API call.

## Result on the example baptism (073)

267 clips, 2:36:00 of footage → **5,835 frames** (4,559 at 1 per 2 s + 1,276 at scene changes),
**434 contact sheets**. Frames took 357 s (≈ 26× real time over USB), sheets 20 s; a second run is
instant from the cache. The event folder was byte-for-byte unchanged (names, sizes, mtimes).

Handheld masters trigger many scene frames (camera moves), so they end up close to 1 frame per
second; static shots stay at 1 per 2 s. Estimated cost of pass 1 for the whole event:
Sonnet 5.5 ≈ $3.5, Haiku 5.5 ≈ $0.2, Opus 5.5 ≈ $7.1 (≈ 1.17M input tokens), ~7 min.
