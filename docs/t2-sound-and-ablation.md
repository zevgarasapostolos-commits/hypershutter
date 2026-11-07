# T2: sound in the sorting, and the ablation study

The thesis question: **what does each signal (capture time, camera, image, sound) contribute to
sorting wedding footage by moment of the day?** Code: `core/audio_tags.py`, `core/ablation.py`
(`hypershutter ablation`), `scripts/ablation_table.py`.

## 1. Sound analysis (local, nothing uploaded)

1. **Sound events.**
   - Every clip is cut into 5 s windows of 16 kHz mono audio.
   - Each window goes through **CED-mini**: a 9.6 M-parameter AudioSet tagger (527 classes, mAP
     ≈ 0.49), run as ONNX through sherpa-onnx at about 0.04 s per 10 s of audio.
   - The 527 classes are reduced to 17 groups that matter at an event:

     | Kind | Groups |
     |---|---|
     | Voices | speech, shouting, laughter, crying |
     | Music | chanting (choir, chant, Christian music), singing, music (instruments and genres) |
     | Crowd | applause / cheering, crowd / chatter |
     | Place and things | bells, water, wind, vehicles, animals (birds, insects), fireworks, dishes, camera clicks |

   - Room acoustics are tagged too (small room, large hall, outdoors) and the RMS level in dBFS.
   - All of it is cached per file.
2. **Speech cues.**
   - Clips with speech or chanting in at least a fifth of their windows go through Whisper
     large-v3-turbo (mlx, local).
   - What is said becomes cue categories only: *liturgy* (most sentences are liturgical), the
     ritual moments (*rings, crowning, isaiah, common_cup, renunciation, creed, immersion,
     gospel*), *wishes*, *toast* and photographer *directions*.
   - Raw speech never reaches the model: it is compact, explainable, and keeps names private.
3. **Text features.**
   - Pass 2 gets one line per clip, e.g. `sound: chanting 80%, speech 40%; large hall; heard:
     liturgy, crowning`.
   - Pass 1 (prompt d4) gets the runs over time, e.g. `0:00–0:40 chanting + speech; 0:40–0:55
     applause + crowd`, and reports what the sound adds in a `sound` field.
4. **Offline fallback with sound.**
   - Without the API, a time segment is split where the sound context changes for at least 3 clips:
     - *service*: chanting or ritual cues;
     - *party*: mostly music with a lively crowd;
     - *other*.
   - A service becomes a ceremony ΡΟΗ / B-ROLL pair.

Throughput:
- **Tagging:** 507 wedding clips (4.0 h of footage) in 50 s, 267 baptism clips (2.6 h) in 41 s.
  Both read from a USB SSD.
- **Whisper:** 353 wedding clips (3.4 h) in 36 min, on Apple silicon, alongside other work.

### What the sound says about each part of the wedding

Per folder of the videographer's own sort (gamos 25-07): the sound context of each clip
(service / party / other) and the strongest groups (mean share of each clip).

| Folder | Clips | Service / party / other | Strongest groups | Speech cues |
|---|---|---|---|---|
| 01 Village & location | 14 | 0 / 6 / 8 | speech 81%, music 47%, animals 17% | – |
| 02 Details | 41 | 0 / 28 / 13 | speech 79%, music 71% | – |
| 03 Groom getting ready | 50 | 4 / 6 / 40 | speech 84%, music 16%, camera clicks 11% | liturgy 3 ✗, directions 2 |
| 04 Bride getting ready | 37 | 2 / 8 / 27 | speech 85%, music 28% | directions 5 |
| 05 Church & arrivals | 21 | 1 / 1 / 19 | speech 88%, animals 32% | – |
| 06 Wedding — ΡΟΗ | 2 | **2** / 0 / 0 | speech 68%, **chanting 37%** | **liturgy 2, crowning 1** |
| 06a Wedding — B-ROLL | 4 | 1 / 0 / 3 | animals 50%, chanting 17% | crowning 1 |
| 07 Exit & wishes | 22 | 0 / 0 / 22 | speech 99%, **crowd 68%** | – |
| 08 Couple shoot (scooter) | 14 | 0 / 0 / 14 | speech 97%, **animals 55%** (cicadas, outdoors) | directions 4 |
| 09 Family with the baby | 15 | 1 / 0 / 14 | speech 99%, crowd 69% | directions 6 |
| 10 Baptism — ΡΟΗ | 3 | **3** / 0 / 0 | speech 81%, chanting 19% | **liturgy 3, renunciation 1** |
| 11 Baptism — B-ROLL | 33 | 4 / 2 / 27 | speech 89%, animals 20%, music 19% | – |
| 12 Reception — decor | 40 | 0 / **39** / 1 | **music 99%** | – |
| 13 Reception — people & food | 31 | 0 / **31** / 0 | **music 100%**, crowd 35%, dishes 11% | – |
| 14 Dancing | 119 | 0 / **119** / 0 | **music 100%** | – |
| 15 Wishes / interviews | 11 | 0 / 11 / 0 | speech 99%, music 97%, laughter 7% | **wishes 6** |
| 17 Drone | 33 | – | no sound | – |

What the table shows:
- The ceremony masters are recognized by their sound, and so are the reception and the dancing
  (159 of 159 dancing and food clips are "party").
- Wishes are heard in the interviews, and a crowd at the exit and with the family.
- Short b-roll clips in the church mostly catch speech, not chanting, so sound alone cannot
  separate them.
- Whisper also "hears" liturgy in a few getting-ready clips (✗). Its prompt primes ritual words
  on unclear audio.

## 2. Ablation design

- **Events.** Three organized events, each scored against the videographer's own folders with the
  grouping metrics of M3: Hungarian-matched accuracy, pairwise F1, ARI, boundary F1.
  - The 25 July wedding + baptism: 507 clips, 19 folders including one unsorted camera folder.
  - Baptism 073: 267 clips. The pass-2 rules were tuned on it.
  - Baptism 071: 249 clips.
- **Conditions.** The same pipeline with signals switched off:

| Condition | Pass 1 (per clip) | Pass 2 sees per clip | Camera rules in validation |
|---|---|---|---|
| offline: time gaps | – | – (no model: new part at 10-min gaps, drone apart) | yes |
| offline: time gaps + sound | – | – (also split where the sound context changes) | yes |
| time | – | time span, duration | no |
| time + camera | – | + camera (main / second / drone) | yes |
| time + camera + sound | – | + sound line | yes |
| time + camera + image | pictures (d3) | + what the pictures show | yes |
| all (sound in pass 2 only) | pictures (d3) | + pictures + sound line | yes |
| all | pictures + sound (d4) | + pictures (described with sound) + sound line | yes |

"Camera rules" are the deterministic steps that need the camera: the drone folder, long
main-camera takes as ΡΟΗ, same-camera smoothing. Without the camera signal they are off.

- **Repeats.** Pass 2 is not deterministic, so every model condition runs 3 times; tables give
  mean ± sd. Pass-1 descriptions and the sound analysis are cached, so a repeat only pays for
  pass 2.
- **Model.** Claude Opus 5.5: low effort for pass 1, high effort for pass 2. Prompts d3 / d4 and s4.

## 3. Results

RESULTS

## 4. Frame density

Subset: 136 wedding clips. Every folder is represented in proportion, spread over the day, and
every long main-camera take is included. Signals: time + camera + image. 3 repeats per density.

| One frame every | Frames | Matched accuracy (%) | Pairwise F1 | ARI | Boundary F1 | Pass-1 cost |
|---|---|---|---|---|---|---|
| 4 s | 3,936 | 92.7 ± 1.9 | 0.871 ± 0.059 | 0.858 ± 0.064 | 0.913 ± 0.014 | $4.36 |
| **2 s (default)** | 7,572 | **94.4 ± 0.4** | **0.912 ± 0.006** | **0.904 ± 0.007** | **0.936 ± 0.012** | ≈ $6.70 * |
| 1 s | 14,048 | 93.4 ± 0.7 | 0.901 ± 0.025 | 0.891 ± 0.027 | 0.935 ± 0.010 | $7.03 |

\* The 2 s descriptions came from the full-event run: the subset's share of that run, by sheet count.

- **1 frame every 2 s is the sweet spot.** It gives the best accuracy and the smallest spread.
- **Fewer frames.** At 1 frame every 4 s, accuracy drops by 1.7 points and the repeats disagree
  more: short cutaways get only 1–2 frames, so their content is guessed.
- **More frames do not help.** 1 frame per second doubles the frames and costs more, with no
  gain. A request carries at most 20 sheets (480 frames), so long takes are subsampled anyway.
  The extra frames of short clips mostly repeat what the 2 s frames already show.
- **Time.** Extracting the extra frames for the 1 s subset took 26 minutes, against about 6 for 4 s.
