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

## Held-out check: 071 baptism (249 clips, 13 folders, never used for tuning)

The s2 rules were tuned on 073, so 97.8% there is a training-set number. 071 is a different
baptism on the same day, organized by the user into folders, and was never looked at while
writing the rules.

| Run | Model | Prompts | Matched acc. | Pairwise F1 | ARI | Folders | Boundary F1 | Cost |
|---|---|---|---|---|---|---|---|---|
| held-out | Opus 5.5 | d3/s2 | **95.6%** | **0.915** | **0.905** | 14 (13) | **0.938** | $6.02 |

The clock was found automatically: camera A at +13:59:16, the same camera as in 073. There
were no refusals.

There were 11 misplaced clips:

- **Portraits vs arrival (7):** the same ambiguous boundary as in 073.
- **Baby photo shoot (3):** the model made a separate "photo shoot of the baby at the decor"
  folder, while the user kept those clips with the portraits after the baptism. This is a
  granularity choice.
- **Long receiving-line take after the sacrament (1):** the preset sends it to «ΕΥΧΕΣ & ΚΕΡΑΣΜΑ»
  and tells the user it can move to the ΡΟΗ. The model did exactly that and said so in its notes;
  the user had it in the ΡΟΗ.

Every ceremony folder (ΡΟΗ and B-ROLL of κατήχηση and μυστήριο), the drone, decor, details,
exterior and interior folders are 100 % correct.

Not usable as held-out events: 066, 067, 068 and 069. Their shot indexes list the clips, but
only the drone footage is still on the T7. The camera footage was moved, and `eval` now stops
before any API call in that case.

## Wedding: gamos 25-07 (507 clips, 18 folders, a γαμοβάφτιση)

A wedding and a baptism on the same day, two cameras, a drone and a sound recorder. The first
run used the baptism-tuned rules; s3 and s4 added wedding hints to the preset.

| Run | Rules | Matched acc. | Pairwise F1 | ARI | Folders (truth) | Boundary F1 | Cost |
|---|---|---|---|---|---|---|---|
| first run | s2 | 82.5% | 0.835 | 0.815 | 24 (18) | 0.847 | $13.71 |
| wedding hints | s3 | 93.1% | 0.862 | 0.846 | 19 (18) | 0.837 | +$0.68 |
| general split rule restored | s4 | **96.5%** | **0.952** | **0.947** | 19 (18) | **0.924** | +$0.68 |

What changed:
- **s3** made the reception rule preset-specific. A baptism keeps the reception as one part; a
  wedding splits it into decor vs people & food. The wedding preset also got its own parts: the
  village as a separate part, ΕΚΚΛΗΣΙΑ & ΑΦΙΞΗ ΚΟΣΜΟΥ as one part, ΒΑΦΤΙΣΗ ΡΟΗ / B-ROLL including
  the catechism, all dancing in ΧΟΡΟΣ, and "nothing is thrown away".
- **s4** put back the general rule "do not split one continuous stretch at the same place by
  subject", with the exceptions each preset keeps apart. s3 had dropped it, and 071 went down to
  91.2% because of that.

There are 19 misplaced clips left after s4:
- **Village establishing shots (7):** bell tower, plane trees and the stone terrace, filmed during
  the preparation or the reception. The user collects them in «ΧΩΡΙΟ & ΤΟΠΟΘΕΣΙΑ»; the model
  keeps them in the part where they were filmed.
- **Details vs groom preparation (3):** the groom's shoes and jacket. This boundary is ambiguous.
- **Dancing among the tables (3):** the user's folder is the reception, the model's is the dance.
- **Others (6):** a bride close-up from camera B, a girl on the stairs, the scooter through the
  crowd (exit vs photo shoot), a toast (decor vs people), an interview at the dance, and one
  accidental road shot. The model sent the road shot to 99; the user keeps everything.

## s3 and s4 on the baptisms

| Event | s2 | s3 | s4 |
|---|---|---|---|
| 073 (tuning) | 97.8% | 97.8% | **97.8%** |
| 071 | 95.6% | 91.2% | **96.0%** |

Re-running pass 2 only costs $0.36–0.39 per baptism, because pass 1 is cached. 071 is no longer
strictly held-out: its drop in s3 is what showed that the general rule was needed. The rule itself
is the one written for 073 in s2, so no 071-specific case was added.
