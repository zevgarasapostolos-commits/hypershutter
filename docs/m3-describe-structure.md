# M3: describe, structure and evaluation

## Pipeline

1. **Frames and sheets** (M2): 1 frame every 2 s plus scene-change frames. Frames are tiled 6×4 per
   contact sheet at 2571×1067 px, with the time inside the clip and the corrected clock time on each tile.
2. **Pass 1: describe** (`core/describe.py`, one call per clip, 8 calls in parallel).
   - **Input:**
     - the clip's contact sheets, with at most 20 sheets per clip; longer clips are subsampled evenly;
     - event type, camera role, resolution/fps/audio, duration and time of day;
     - never a file name or a path.
   - **Output:** structured JSON (`output_config.format`), containing:
     - an English description and a Greek one-liner;
     - location, moments (35 tags), who is in the shot, shot type, continuous take or cutaway;
     - posed or candid, and whether the priest in vestments is at the font;
     - notable moments with times, quality issues, usable, star and confidence.
   - **Model settings:** effort `low`, and the system prompt is cached.
   - **Refusals:** server-side refusal fallback is on (`fallbacks: "default"`). A clip refused
     even then keeps its place by time and is flagged for review.
   - **Caching:** results are cached per clip, model, frame settings and prompt version in
     Application Support. Re-running is free.
3. **Pass 2: structure** (`core/structure.py`, one streamed text-only call, effort `high`).
   - **Input:**
     - one line per clip on the corrected timeline: index, time span, duration, camera,
       moments, location, who, flags and description;
     - the preset hints and the workflow rules.
   - **Output:** the event's own parts (Greek label, Greek description, kind, ceremony name)
     and every clip's part with a confidence.
4. **Validation** (`finalize`, deterministic):
   - every clip is assigned exactly once;
   - 99 is allowed only for clips with no picture of the event;
   - all drone clips go to one part;
   - ΡΟΗ / B-ROLL rule: under 30 s in ΡΟΗ goes to B-ROLL; a main-camera continuous take of 90 s
     or more in B-ROLL goes to ΡΟΗ;
   - isolated low-confidence outliers are smoothed;
   - parts are numbered chronologically, with ceremony pairs sharing N / Na and unusable as 99;
   - folder names are Greeklish;
   - clips with confidence below 0.6 are marked "needs review".
5. **Offline fallback:** without a key or internet, the timeline is split at time gaps.

## Evaluation (`hypershutter eval`)

The pipeline runs read-only on an organized event, and the folder each clip sits in is the
ground truth. Folder names differ between runs, so the metrics compare groupings:

- **matched accuracy:** predicted folders are matched to true folders by overlap with the
  Hungarian method;
- **pairwise precision / recall / F1:** whether clips the user put together end up together;
- **ARI** (Adjusted Rand Index);
- **boundary F1:** folder changes between consecutive clips on the timeline, ±1 clip.

Each run also reports clock offsets, cost and time. Reports go to `reports/`, which is
git-ignored because they hold clip descriptions.

## Results: 073 baptism (267 clips, 17 folders)

| Run | Model | Prompts | Matched acc. | Pairwise F1 | ARI | Folders | Boundary F1 | Cost |
|---|---|---|---|---|---|---|---|---|
| offline (time gaps) | — | — | 46.1% | 0.290 | 0.177 | 7 | 0.394 | $0 |
| first AI run | Opus 5.5 | d3/s1 | 89.1% | 0.872 | 0.862 | 20 | 0.783 | $7.69 |
| rules s2 | Opus 5.5 | d3/s2 | **97.8%** | **0.963** | **0.960** | **17** | **0.932** | $0.38 (pass 2 only) |

- **Time:** pass 1 took 138 s for 267 clips and pass 2 took about 90 s.
- **Refusals:** none.
- **Clocks:** camera A was found automatically at +13:59:16 (the index says +14:00).

### What the first run got wrong, and the s2 rules

The first run had 29 misplaced clips, from three causes:

1. **Reception split by subject (17 clips).** The model split the reception into empty venue,
   guests at the tables and kids with the animals. The user keeps one reception part.
   The workflow template's «ΔΕΞΙΩΣΗ — ΧΩΡΟΣ & ΤΡΑΠΕΖΙΑ / ΔΕΞΙΩΣΗ — ΚΟΣΜΟΣ & ΦΑΓΗΤΟ» lists
   alternative names, not two folders.
   - **Rule:** a new part starts with a new activity or place, not a new subject.
2. **Portraits vs arrival (9 clips).** These clips interleave in time. In the user's folders,
   set-up family shots are held long (almost all ≥ 7 s), while arrival shots are quick
   snapshots (≤ 5–6 s).
   - **Rule:** decide with duration and who is in the shot, not only the posed/candid flag.
     The clip table now lists who is in each shot.
3. **An unnecessary 99 folder (4 clips).** The user keeps short, blurry and accidental-looking
   clips in their part.
   - **Rule:** 99 is used only when no frame shows the event. This is also enforced in code:
     anything else the model sends to 99 rejoins its neighbours in time and is flagged.

### Errors that remain after s2 (6 of 267)

- **Portraits vs arrival (5 clips):** genuinely ambiguous. One example: parents posing with the
  baby for the photographer are in the user's arrival folder, while a 1 s posed group is in
  portraits.
- **Musicians vs dance (1 clip):** a musicians cutaway between dance takes. The model's notes
  already say it could go either way.

### Caveat

The s2 rules come from errors on this same event, so 97.8% is a training-set number. They
still need checking on an organized event they were not tuned on: another baptism, then the
25 July wedding.
