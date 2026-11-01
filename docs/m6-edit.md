# M6: Edit prep (B-roll, highlights, ροή, Premiere XML, previews)

The rules come from [workflow-editing.md](workflow-editing.md) and §5.4–5.5 and §6 of
[workflow-organizing.md](workflow-organizing.md). Everything is built from what the earlier
stages already know about each clip, so Edit prep makes **no API calls**:

- corrected time;
- reviewed folder;
- the pass-1 description: moments, people, shot type, posed or candid, quality issues, star,
  and notable moments with their time in the clip;
- resolution and frame rate.

## B-roll lists (`hypershutter broll`, app → Edit prep)

- Lists are per ceremony, or per folder. Only clips filmed during that part are listed.
- Clips are grouped like the user's lists: mum / baby · crowd · faces / family · details.
- The strongest clips come first and get ⭐. 1080p clips get a note "scale 200 %"; rotated and
  shaky clips get notes too.
- For the long masters, the list gives in → out points around each notable moment (e.g.
  "2:00 → 2:04 baby lifted up from the font"). These come from frames every 2 s, so they are
  marked as approximate.

## Highlights

1. **Music.**
   - With the template song, the user's own cut grid is used as is (101 slots, 190.52 s).
   - With any other song, its tempo is measured: onset envelope, a comb over multiples so a
     3/2 or 2× relative never wins, and a sub-frame refinement. The template's rhythm is then
     replayed on the new song's beats, and every cut snaps to a half-beat.
2. **Slots follow the day:**
   - drone opening, then the title over a clean wide drone;
   - exterior → interior → details (wide first, then close) → family → guests;
   - drone → κατήχηση around **FILM 1** → drone → μυστήριο around **FILM 2** (the immersion);
   - drone → κέρασμα / reception / kids / music / dance → baby with the parents → last wide drone.
3. **Rules applied:**
   - Drones: the window with steady, clear change between frames (moving, not hovering, no
     whip pans).
   - Ceremonies: the beats stay in time order around the film scene, and the immersion is
     always included.
   - A master never appears twice in a row (the film scene next door counts), and the same
     moment of a master is never shown twice.
   - Slow motion only on details and tender close shots from 50 fps sources, never on masters
     or drones.
   - Candid shots rank above posed ones; shaky shots are kept but get a "needs Warp" marker.
   - A slot longer than its clip takes another clip from the same folder.
   - The FILM scenes put the master's camera audio on A3, with Constant Power fades.

## Ροή

1. **Intro:** the highlights' pre-ceremony part, with the music fading out over 16 s under the
   start of the κατήχηση.
2. **Ceremony masters** in order:
   - each starts after its walking or shaky start;
   - overlapping masters are trimmed;
   - when the camera was off for more than 20 s, the steady b-roll of that gap runs on V1 with
     its own sound (up to ~35 s).
3. **V2 cutaways** (2.4 s each):
   - one over every join between masters, then about every 45 s;
   - none within 10 s of the immersion;
   - no b-roll is used twice;
   - a second-camera clip filmed during a master goes at its true instant (multicam);
   - other cutaways use the closest steady b-roll in time.
4. **Ending:** a moving drone, then the highlights' end montage on the same part of the song,
   so the cuts still fall on its beats, then a drone to the end of the song.
5. **Dances in full,** with their own sound, a marker at every join, and a closing drone.
6. **Markers:** ΤΙΤΛΟΣ, ΚΑΤΗΧΗΣΗ / ΜΥΣΤΗΡΙΟ — Impact Dissolve, camera-off bridges, ΒΟΥΤΙΑ,
   ΤΕΛΟΣ ΤΕΛΕΤΗΣ, ΧΟΡΟΙ.
7. **Not yet:** cutting the off-ritual talk needs a transcript (Whisper) and is left to the
   user. Each run says so.

## Premiere XML and previews

- **XML** is FCP7 XML v4, matching the user's sequences:
  - 25 fps, 3840×2160;
  - plain clips: in/out in sequence frames;
  - Time Remap clips: in/out in source frames at their own rate;
  - Basic Motion 200 % for 1080p;
  - Constant Power audio fades;
  - `file://localhost` paths with spaces and parentheses escaped.
- `Sequence.check()` refuses to write when a file is missing, when items overlap, or when an
  in/out falls outside its clip.
- **Previews** are 960×540 at 25 fps: the top video item at every moment (V2 over V1) and a mix
  of all audio items with their fades.
- **Output location:**
  - Files go to the event root: `<event> highlights.xml`, `<event> ροή.xml`,
    `<NNN> … - preview (για έλεγχο).mp4`.
  - The song is copied into `music/`.
  - Nothing is ever overwritten: an existing file makes the new one « (2)».
  - Reference projects write to `reports/edit/<event>/` instead.

## Safety added to Apply

- If the event root already has a `.prproj` or an exported XML that uses clips about to move,
  the plan lists those files (workflow §6.1).
- The CLI then refuses `--apply` without `--relink`, and the app asks for the "I will relink"
  confirmation. Both show the relink steps.

## Results on the 073 baptism (read-only, output in `reports/edit/`)

- **Highlights:** 101 cuts on the template song, built in under 1 s; the preview takes about 95 s.
  - Order: town drone → church → details (name sign, drinks, flowers, cupcakes) → family →
    guests → drone → κατήχηση with FILM 1 → drone → μυστήριο with FILM 2 on the immersion,
    followed by the second camera's immersion close-up → κέρασμα → reception → face painting
    → musicians → dance → final drone.
- **Ροή:** about 118 min (the user's own is 111 min with the talk already cut). It has
  112 V1 items, 17 V2 cutaways (the user had 22) and 42 A1 items, with markers at the same
  places as the user's.

## Tests

`tests/test_edit.py` covers:
- XML shape: remap frames, scale, escaping, fades, and out-of-range detection;
- the music grid on a 120 BPM click track: tempo within 2 % and cuts on half-beats;
- the highlights rules on a synthetic event: drone open, title and close, FILM 2 on the
  immersion, no master back to back, no slow motion on masters or drones;
- the ροή: ceremony and dance markers, no cutaway on the immersion, no reuse on V2;
- preview layering.

`tests/test_execute.py` adds the check for edited projects.
