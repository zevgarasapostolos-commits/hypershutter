# Editing workflow: B-roll, highlights, ροή, Premiere XML

Synthesized on 2026-11-01 from the user's baptism editing session (events 067–073, plus the
wedding thread) and the rules saved from his corrections. No client names. This is the source
for M6 (B-roll selection, Premiere sequences, previews). The organizing part is in
[workflow-organizing.md](workflow-organizing.md) (the user's own export, in Greek).

## 1. Deliverables per event

- **highlights**: music-driven, ~3:10, chronological story of the day.
- **ροή** (flow): the full ceremony, condensed only by cutting off-ritual talk, plus intro and ending.
- Both as **FCP7 XML (xmeml v4)** for Premiere, 3840×2160, **25 fps** timeline, named
  `<NNN> <code> highlights.xml` / `<NNN> <code> ροή.xml` in the event root.
- Low-res previews for checking: `<NNN> highlights - preview (για έλεγχο).mp4`,
  `<NNN> ροή - preview (για έλεγχο).mp4` (960×540).
- The song is copied into `<event>/music/`.
- **Only cutting and stitching.** No colour, effects, overlays or stabilization — those are the
  user's. The single exception: 1080p clips get a Basic Motion scale (200 %) to fill 4K.
- The user adds **Impact Dissolves** himself: drop a **marker** at every big time jump
  (into κατήχηση, μυστήριο, after camera-off gaps, into Gospel/απόλυση, end, each dance change).
- When adding to an existing Premiere project, add a new sequence to the same project; never
  touch other open projects.

## 2. Highlights rules

- Follow the real day chronologically: drone establishing → title over a clean wide drone →
  church exterior + interior → details/decor (**wide first, then close**) → family → guests →
  drone → κατήχηση → drone → μυστήριο → drone → κέρασμα/δεξίωση → baby with parents → final
  wide drone. Never pull later shots into the intro.
- **One new shot per music slot.** Never two pieces of the same master back to back (put a
  slow-motion reaction face between), never near-identical shots a few slots apart.
- **Candid over posed.** Faces visible and smiling; vary who is in frame (mum+baby, dad+baby,
  grandparents, siblings, extended groups, baby alone, a parents' kiss). Not three parent shots in
  a row. Family shots ≤ ~2 s.
- Prefer the cleaner detail (cross close-up over the box) and the cute-face moment.
- **Slow motion only on details and tender close moments** (~18 % of slots). Never on masters,
  crowds or posed groups.
- **Content beats stability**: keep good shaky shots and flag them "needs Warp"; drop only
  badly shaky ones.
- The μυστήριο must contain its beats in order: wide master → family → personalised details →
  faces → undressing → mum+baby → **the immersion** (never missing) → dressing → candles circle →
  communion → kisses.
- **Film scenes** (2 slots): a ceremony master moment with its synced audio on A3.
  Film 1 = the phrase with the baby's name («…προσκάλεσαι τον δούλον σου…» through the name, or
  the godparent declaring the name). Film 2 = the immersion («Βαπτίζεται ο δούλος του Θεού…»).
- **Drone shots must MOVE**: orbit, push forward, flyover, reveal — never a still hover. Use the
  widest, most establishing part (whole town / mountains), not tight on the church.

## 3. Ροή rules

- **Intro** = the highlights' pre-ceremony part (~1:28), music fading out over ~16 s under the
  first seconds of the κατήχηση.
- Transcribe the ceremony audio (Greek) and mark ritual vs talk. **Cut off-ritual talk** (instructions
  to godparents, chatter, photo talk, repeats) only when nothing ritual is on screen. Start/end
  pieces on clean sentence boundaries; end a prayer on its «Αμήν».
- **Keep**: the first prayer; at most a ~10 s exorcism excerpt over 2–3 short b-roll faces; the
  exsufflation «εμφύσησον και έμπτυσον… φύσηξε / φτύσε τρεις φορές» (explicit user rule);
  Αποτάσσομαι → Συντάσσομαι → the whole **Πιστεύω** (quiet godparent voice is ritual, not chatter)
  → prayer with the name → απόλυση of the catechism; in the μυστήριο the litany, water blessing,
  oil prayer with undressing, **anointing → immersion → chrism → tonsure → dressing as one
  continuous piece**, a little dressing in white, «Εβαπτίσθης», circle, Gospel (only if audible on
  the mic), απόλυση, the μετάνοιες / hand-kissing after it, «να ζήσει».
- **Cut**: the silent Apostle reading, the Εκτενής/prayers after the Gospel, instructions after the
  exsufflation («γύρνα προς Ανατολή»), the priest's speech before the mystery.
- **Start masters after their shaky first seconds** instead of covering the shake.
- **No V1 b-roll bridges carried by the priest's audio.** Let a master run longer instead. Where
  only b-roll exists (undressing, dressing — camera was off), use 10–35 s of it with **its own
  camera audio** (baby crying, ambience).
- **Cutaways** (V2): about half cover joins, the rest every ~40–50 s; fewer in the μυστήριο and
  **none over the immersion**. 1–3 s each, never long chains.
- **No b-roll reuse** anywhere in the ροή; use as many different *good* b-roll clips as possible
  (smiles, reactions, kids), not just the steadiest.
- **Second camera (δικάμερο)**: sync by audio and cut to it **at its true time** like a multicam
  (Creed, font, chrism, Gospel) — **only when steady**; drop shaky second-camera clips.
- **Ευχές**: if there is a long take of guests congratulating the family, put 5–6 min of it after
  the ceremony, muted, under music from the user's library, then the κέρασμα montage.
- **Ending**: ~6 s moving drone → κέρασμα/δεξίωση montage (= highlights ending) with music
  crossfading in ~10–16 s early → 1–2 moving drones to the song's end.
- **Dances in full**: if dance footage exists, after the montage put every dance clip whole, in
  order, with its own camera audio, trimming only the 1–5 s where the camera is raised/lowered;
  marker at each join; end on a moving drone over the last dance's fading audio. The ροή can then
  run well over 1.5 h.

## 4. Audio

- With a lapel mic (DJI recorder in `sound/`): A1 = mic only for the ceremony, short constant-power
  crossfades at joins; camera audio dropped. κέρασμα uses camera audio, J-cut in with ~12 s crossfade.
- **No mic** (confirm with the user): A1 = the camera audio of the master on screen; bridges use the
  b-roll's own audio; highlights film scenes take camera audio on A3.
- Music on A2/A3 (ροή) or A1/A2 (highlights). Audio fades = Constant Power transition items.

## 5. Techniques that worked

- **Sync**: decode audio to 4 kHz mono, GCC-PHAT cross-correlation. For a camera with a wrong
  clock: align one clip, derive the clock offset, then refine every clip locally (±25 s window)
  against the master camera's audio. A global search on short clips gives false peaks.
- **Transcription**: Whisper large-v3(-turbo) via mlx-whisper, Greek, word timestamps,
  `condition_on_previous_text=False`, a liturgical initial prompt; re-run weak parts on
  high-passed + loudness-normalized snippets. "Υπότιτλοι AUTHORWAVE" = hallucination.
- **Cut points**: RMS envelope per 0.1 s, smoothed, find pauses.
- **Motion metrics** (10 fps): phase-correlation shift per frame, jitter = |shift − smooth(shift)|,
  brightness, Laplacian sharpness. Shaky second = max shift > 6 px or jitter > 0.8.
  Fast decode: `-skip_frame nokey` for HEVC/drone, `-skip_frame bidir` for 4:2:2 H.264.
- **Drone moving-window score** (5 fps, 160×90 blurred frames):
  `change/len − 4·jitter − 0.3·max(0, whip−12) − 0.5·unevenness`, pick the best smooth window
  with clear start→end change.
- **Reading the user's corrected projects**: `.prproj` is gzip XML; walk ObjectID/ObjectRef;
  254016000000 ticks per second; nested sequences resolve to the inner clip. Diffing his final cut
  against ours is how every rule above was learned.

## 6. Premiere XML (xmeml v4) details

- Sequence 25 fps. Plain clips: in/out in **sequence frames**. Time-remapped (slow-mo) clips:
  in/out in **source frames**, with per-clip `src_rate` (50 for 4K50, 25 for 1080p25).
- `pathurl` = `file://localhost` + path with spaces and parentheses percent-escaped. Verify every
  file exists and every in/out is inside the clip before delivering.
- 1080p clips: Basic Motion scale = 3840 / width × 100.
- Markers carry section names and Impact Dissolve hints.
- After import, DJI drone clips have come in offline: File → Link Media (Align Timecode off) →
  Locate fixes them. Check drone clips after every XML import.

## 7. The highlights cut grid (from the user's template, song length 190.52 s)

Slot start times (s):
```
0, 3.36, 5.84, 8.36, 11.40, 13.20, 15.04, 16.84, 18.60, 22.40, 24.40, 26.08, 27.84, 28.80, 29.24,
29.68, 33.40, 35.00, 37.04, 38.88, 40.72, 42.56, 44.36, 46.20, 48.04, 49.88, 51.68, 54.40, 55.40,
57.20, 58.16, 59.08, 60.08, 61.80, 63.60, 64.84, 66.36, 67.28, 68.24, 70.00, 71.88, 73.72, 75.60,
77.48, 79.24, 81.12, 82.92, 85.40, 88.40, 90.16, 92.00, 93.76, 95.64, 97.56, 99.44, 101.04, 107.56,
110.28, 113.04, 114.88, 116.72, 118.56, 119.48, 120.80, 122.36, 124.84, 125.92, 127.56, 129.64,
132.32, 134.08, 138.16, 143.68, 145.12, 146.96, 147.96, 148.84, 150.64, 152.52, 155.80, 157.08,
157.96, 160.68, 162.52, 163.44, 164.36, 165.28, 166.24, 167.16, 168.92, 169.88, 170.88, 172.68,
174.44, 176.28, 178.08, 179.92, 182.24, 183.72, 184.84, 187.84   (END 190.52)
```
Slow-motion slots (index: speed): 1: .5, 2: .7, 4: .5, 6: .5, 7: .5, 8: .7, 9: .5, 11: .5, 15: .5,
17: .5, 18: .5, 19: .5, 20: .5, 21: .5, 22: .5, 23: .5, 34: .5, 63: .5, 64: .5, 70: .7, 88: .6.
Markers: ΤΙΤΛΟΣ 8.36, FILM 1 101.04, FILM 2 138.16. Intro ends at 88.40; end montage from 157.96.
