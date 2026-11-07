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

**Matched accuracy (%)** (mean ± sd over repeats; n = repeats)

| Signals | Wedding + baptism (507 clips) | Baptism 073 (267, tuning) | Baptism 071 (249) |
|---|---|---|---|
| offline: time gaps | 45.4 | 46.1 | 20.5 |
| offline: time gaps + sound | 60.6 | 56.5 | 40.6 |
| time | 73.2 ± 1.1 | 70.7 ± 6.6 | 60.5 ± 4.3 |
| time + camera | 75.2 ± 0.5 | 73.9 ± 12.6 | 62.4 ± 2.2 |
| time + camera + sound | 75.6 ± 0.7 | – | 63.9 ± 2.1 |
| time + camera + image | 93.2 ± 1.1 | 97.8 ± 0.0 | 95.7 ± 0.3 |
| all (sound in pass 2 only) | 93.7 ± 0.5 | – | 95.3 ± 0.9 |
| all | 94.1 ± 0.0 | – | 94.2 ± 1.1 |

**Pairwise F1** (mean ± sd over repeats; n = repeats)

| Signals | Wedding + baptism (507 clips) | Baptism 073 (267, tuning) | Baptism 071 (249) |
|---|---|---|---|
| offline: time gaps | 0.447 | 0.290 | 0.215 |
| offline: time gaps + sound | 0.613 | 0.486 | 0.327 |
| time | 0.696 ± 0.021 | 0.716 ± 0.054 | 0.554 ± 0.034 |
| time + camera | 0.701 ± 0.047 | 0.746 ± 0.128 | 0.567 ± 0.006 |
| time + camera + sound | 0.759 ± 0.013 | – | 0.551 ± 0.039 |
| time + camera + image | 0.893 ± 0.030 | 0.963 ± 0.000 | 0.917 ± 0.007 |
| all (sound in pass 2 only) | 0.909 ± 0.004 | – | 0.908 ± 0.012 |
| all | 0.911 ± 0.000 | – | 0.890 ± 0.019 |

**Adjusted Rand Index** (mean ± sd over repeats; n = repeats)

| Signals | Wedding + baptism (507 clips) | Baptism 073 (267, tuning) | Baptism 071 (249) |
|---|---|---|---|
| offline: time gaps | 0.354 | 0.177 | 0.023 |
| offline: time gaps + sound | 0.568 | 0.439 | 0.279 |
| time | 0.656 ± 0.023 | 0.687 ± 0.060 | 0.499 ± 0.036 |
| time + camera | 0.664 ± 0.051 | 0.721 ± 0.143 | 0.514 ± 0.008 |
| time + camera + sound | 0.726 ± 0.015 | – | 0.490 ± 0.049 |
| time + camera + image | 0.881 ± 0.033 | 0.960 ± 0.000 | 0.907 ± 0.007 |
| all (sound in pass 2 only) | 0.898 ± 0.004 | – | 0.897 ± 0.013 |
| all | 0.901 ± 0.000 | – | 0.876 ± 0.021 |

**Boundary F1** (mean ± sd over repeats; n = repeats)

| Signals | Wedding + baptism (507 clips) | Baptism 073 (267, tuning) | Baptism 071 (249) |
|---|---|---|---|
| offline: time gaps | 0.392 | 0.394 | 0.396 |
| offline: time gaps + sound | 0.477 | 0.523 | 0.583 |
| time | 0.279 ± 0.007 | 0.582 ± 0.133 | 0.568 ± 0.016 |
| time + camera | 0.531 ± 0.008 | 0.736 ± 0.128 | 0.697 ± 0.013 |
| time + camera + sound | 0.560 ± 0.056 | – | 0.644 ± 0.020 |
| time + camera + image | 0.812 ± 0.015 | 0.932 ± 0.000 | 0.938 ± 0.017 |
| all (sound in pass 2 only) | 0.816 ± 0.006 | – | 0.913 ± 0.016 |
| all | 0.817 ± 0.000 | – | 0.927 ± 0.008 |

"–": the sound conditions of baptism 073 are still to run. The API credit ran out before their pass 1
(see the README status).

### What each signal adds

1. **Capture time alone already gets most clips into roughly the right part.**
   - Given only times and durations, the model reaches 61–73% matched accuracy. The time-gap
     segmentation without a model reaches only 21–46%.
   - The boundaries are the weak point (boundary F1 0.28–0.58). Without pictures, the model must
     guess where one part ends and the next begins inside a continuous stretch of the day.
2. **The camera adds a little (+1–3 points).**
   - It helps most with the boundaries: boundary F1 0.28 → 0.53 on the wedding, 0.58 → 0.74 on
     073, 0.57 → 0.70 on 071.
   - Drone clips get their own folder, and long main-camera takes become the ceremony ΡΟΗ.
3. **The image is the decisive signal (+18 to +33 points).**
   - With what the pictures show, accuracy jumps to 93–98% on all three events, and pairwise F1 to
     0.89–0.96.
   - The repeats agree (sd ≤ 1.1 points), against up to 12.6 points without pictures.
4. **Sound helps clearly when there are no pictures, and is marginal next to them.**
   - In the offline fallback, sound adds +15, +10 and +20 points on the three events (wedding
     45 → 61%, 073 46 → 57%, 071 21 → 41%). It finds the ceremonies (chanting, liturgy) and the
     party (music with a crowd).
   - With time and camera but no pictures it adds +0.4 / +1.5 points of accuracy, and on the
     wedding +0.06 pairwise F1.
   - With pictures it moves accuracy by +0.9 (wedding) and −0.4 to −1.5 (071), all within the
     run-to-run spread. On the wedding it made the result fully repeatable: 94.1% in all three runs.
   - Hearing the sound in pass 1 too (prompt d4), rather than only in pass 2, made no consistent
     difference.

### Why sound can also hurt: an error analysis (071)

Two more runs of each condition kept their misplaced clips.

- **Without sound**, both runs misplaced the same 10 clips: the portraits-vs-arrival boundary
  (6 + 6 over the two runs) and a few portraits after the baptism. Both are known to be ambiguous
  (docs/m3).
- **With sound**, these 10 plus 2–6 more. 5 short catechism cutaways (C4030–C4034, in the narthex)
  went to *guest arrival* in some runs.
  - Their sound is speech and a crowd, with no chanting: a 5–10 s cutaway rarely catches the
    priest's chant.
  - That weak evidence pulled the start of the catechism later.
- **The lesson.** The sound of a short clip is weak evidence for its part. It is strong for long
  takes (the ceremony masters are 100% "service") and for whole stretches (159/159 dancing and
  food clips are "party"). That is where the offline fallback gains, while pass 2 already knows
  those from the pictures.

### Cost (Claude Opus 5.5)

- **One full sort** (pass 1 + pass 2) costs $13.71 for the 507-clip wedding, $7.69 for baptism 073,
  and $6.02 for 071. Pass 1 dominates.
- **With sound in pass 1**, the wedding costs $13.86 + pass 2.
- **A pass-2-only repeat** costs $0.25–0.70.
- **The whole ablation study** cost about $56: $31 of pass 1 (the sound and density variants) and
  $25 of pass-2 repeats. That covers all conditions and repeats on the three events, plus the
  density study.


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
