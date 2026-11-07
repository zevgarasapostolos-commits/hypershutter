import shutil
from pathlib import Path

from hypershutter.core import execute, index, manifest
from hypershutter.core.project import Project
from test_execute import PRESET, _snapshot, event  # noqa: F401  (the fixture)


def _mirror(p: Project, drive: Path) -> Path:
    """A second drive's copy of the event, with the ingest manifests both copies would have."""
    from hypershutter.core.ingest import hash_file
    main = Path(p.root)
    copy = drive / main.name
    shutil.copytree(main, copy, ignore=shutil.ignore_patterns(".hypershutter"))
    for root in (main, copy):
        m = manifest.Manifest(root)
        for f in sorted(main.rglob("*")):
            if f.is_file() and ".hypershutter" not in f.parts:
                rel = str(f.relative_to(main))
                m.set(rel, f.stat().st_size, hash_file(f), manifest.VERIFIED, rel)
        m.save()
    execute.remember_copies([main, copy])
    return copy


def test_organize_and_undo_on_every_drive(event, tmp_path):
    p, st = event
    main = Path(p.root)
    px = main / "Proxies" / "cam apos" / "C0001.mov"                  # a proxy made on the main drive
    px.parent.mkdir(parents=True)
    px.write_bytes(b"proxy")
    copy = _mirror(p, tmp_path / "driveB")
    before_main, before_copy = _snapshot(main), _snapshot(copy)
    assert execute.copies(p) == [copy]
    r = execute.apply_everywhere(p, st, PRESET, extras=index.generated_files)
    assert [c["status"] for c in r["copies"]] == ["applied", "applied"]
    for root in (main, copy):
        assert (root / "03a KATIXISI - B-ROLL" / "C6501.MP4").exists() and (root / "03a KATIXISI - B-ROLL" / "C6501.THM").exists()
        assert (root / "00 EVRETIRIO PLANON.md").exists()
    assert (main / "Proxies" / "01 STOLISMOS" / "C0001.mov").exists()          # the proxy followed its clip
    # both drives now hold the same files at the same places
    tree = lambda r: sorted(str(f.relative_to(r)) for f in r.rglob("*") if f.is_file() and ".hypershutter" not in f.parts
                            and "Proxies" not in f.parts)
    assert tree(main) == tree(copy)
    # the ingest manifest knows where each card file is now (re-inserting the card copies nothing)
    m = manifest.Manifest(copy)
    assert m.get("cam apos/C0001.MP4").now == "01 STOLISMOS/C0001.MP4"
    assert m.verified("cam apos/C0001.MP4", (copy / "01 STOLISMOS/C0001.MP4").stat().st_size)
    # one journal per drive, undone on both
    assert execute.last_applied(p)["root"] == str(main)
    u = execute.undo_everywhere(p)
    assert [c["status"] for c in u["copies"]] == ["undone", "undone"]
    assert _snapshot(main) == before_main and _snapshot(copy) == before_copy
    assert manifest.Manifest(copy).get("cam apos/C0001.MP4").now == ""


def test_a_copy_that_differs_stops_the_whole_organize(event, tmp_path):
    p, st = event
    main = Path(p.root)
    copy = _mirror(p, tmp_path / "driveB")
    m = manifest.Manifest(copy)                                          # the copy's checksum disagrees
    e = m.get("cam dim/C6501.MP4")
    m.set(e.rel, e.size, "0" * 16, manifest.VERIFIED, e.source)
    m.save()
    before_main, before_copy = _snapshot(main), _snapshot(copy)
    try:
        execute.apply_everywhere(p, st, PRESET)
        raise AssertionError("should have refused")
    except RuntimeError as err:
        assert "differs from the main copy" in str(err)
    assert _snapshot(main) == before_main and _snapshot(copy) == before_copy        # nothing moved anywhere
