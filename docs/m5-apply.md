# M5: Apply, Undo, shot index, contact sheets

## What Apply does (`core/execute.py`)

1. **Plan (dry run).**
   - Every clip in the reviewed structure goes to `<root>/<NN folder>/<file name>`.
   - Its sidecars go with it (`.XML`, `.SRT`, `.LRF`, `.THM`, …).
   - Audio files join the folder whose clips they overlap most in time.
   - The plan stops and lists every conflict: a missing source, an existing destination, two
     files getting the same name, or a file sitting where a folder must go.
   - Renaming is off by default. When it is on (`--rename '{num}_{n:03d}_{name}'`), sidecars get
     the same new stem.
2. **Journal first.** Every planned move is written to Application Support
   (`journals/<project>/<id>.json`) and to `<event>/.hypershutter/journal.json` before the
   first file moves.
3. **Move.**
   - Moves use `os.rename` on the same drive only: no copy-then-delete, no re-encode, no
     metadata writes.
   - A move never overwrites a file.
   - On macOS exFAT drives, the AppleDouble `._` companions follow their files automatically.
4. **Generated files.**
   - `00 EVRETIRIO PLANON.md` and `00 CONTACT SHEETS/<NN>.jpg` (one sheet per folder: the middle
     frame of each clip, labelled `clip time duration`, 7 across).
   - Anything already at those paths is set aside under `.hypershutter/replaced/<id>/`, never
     overwritten.
5. **Re-apply after edits.**
   - Only the clips that changed folder move.
   - Folders from an earlier run that are now empty are removed (and recreated on undo).
   - Stale sheets are set aside.
6. **Refusals.**
   - The reference projects (073, the 25 July wedding) are refused by name.
   - So is any event whose clips mostly already sit in numbered folders and that has no
     HyperShutter journal (organized by hand). `--force` overrides the second rule only.

## Undo

- Undo works from what is on disk, not only from the journal status, so it also recovers a run
  that stopped half way.
- It goes newest move first:
  - a file at the destination with nothing at the source moves back;
  - a file already back at its source is skipped;
  - when both paths exist, nothing is touched and the clash is reported.
- It then:
  - deletes only the files Apply generated;
  - restores the files that were set aside;
  - removes the folders Apply created, only when they are empty;
  - recreates the folders a later run removed.
- Several runs undo one at a time, newest first.

## Backup (optional)

Before any move, every clip and sidecar can be copied to `<backup>/<event>/<same path>` with
`copy2`, then verified by xxHash-128 against the original. The free space is checked first.
Files already backed up and verified are skipped.

## Verification

**Unit tests** (`tests/test_execute.py`, 10 tests) cover:
- the plan, including sidecars and audio placed by overlap;
- apply followed by undo leaving an identical file tree;
- a run interrupted after 2 moves, with the journal already on disk, then undone;
- never overwriting a file;
- refusing the reference projects;
- the rename pattern;
- set-aside files being restored;
- the index format;
- backup verification;
- re-apply after an edit, then undoing both runs in order.

**Test copy** (`/Volumes/T7/HyperShutter-test/HS test 073-sample`): 30 small clips copied
read-only from the 073 baptism into a raw `cam apos / cam dim / drone` layout, plus 3 synthetic
`.THM` sidecars.

- Analysis cost $0.11, because the descriptions are cached per file and shared across projects.
- CLI `apply --apply` followed by `undo`: identical tree (size, mtime and inode of all 69 files).
- In the app:
  - Apply moved the files into 13 folders and wrote the index and 13 sheets.
  - After a Review edit (one clip to another folder), a second Apply moved one file, removed the
    empty folder and set its sheet aside.
  - Undo, then Undo again, gave an identical tree.
- The only difference left is the `.hypershutter/` journal folder, which is kept on purpose.

## Known issue

A server started by a process without the macOS permission for removable volumes blocks on its
first `open()` of a file on the external drive. macOS shows a permission prompt and waits for
it. In the packaged app this is the normal first-run prompt, and `NSRemovableVolumesUsageDescription`
must be set in M9. Run from Terminal, the app inherits Terminal's access.
