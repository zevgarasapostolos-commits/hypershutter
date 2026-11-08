"""Drive monitoring (thesis §6.9): capacity, used and free space of every connected drive, the size
of each known project and of its proxies, the space left after planned work, and warnings.

Sizes come from what HyperShutter already knows (the project's clips, the proxy and export jobs):
a drive is never walked to measure it.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from hypershutter.core import cards, config, store
from hypershutter.core.project import Project

VOLUMES = Path("/Volumes")
WARN_PERCENT = 10.0          # free space under this share of the drive: warning
WARN_GB = 50.0               # … or under this many GB
CRITICAL_GB = 10.0


@dataclass
class ProjectUse:
    name: str
    root: str
    footage_bytes: int
    proxies_bytes: int


@dataclass
class Drive:
    path: str
    name: str
    total: int
    used: int
    free: int
    is_card: bool = False
    is_system: bool = False
    projects: list[ProjectUse] = field(default_factory=list)
    planned: int = 0             # bytes queued to land here (proxies, exports, an ingest being planned)
    status: str = "ok"           # ok | warn | critical
    message: str = ""

    @property
    def free_after(self) -> int:
        return self.free - self.planned


def thresholds() -> dict:
    f = config.app_support_dir() / "drive_thresholds.json"
    d = {"warn_percent": WARN_PERCENT, "warn_gb": WARN_GB, "critical_gb": CRITICAL_GB}
    if f.exists():
        import json
        d.update(json.loads(f.read_text()))
    return d


def classify(total: int, free_after: int, t: dict | None = None) -> tuple[str, str]:
    t = t or thresholds()
    gb = free_after / 1e9
    if gb < t["critical_gb"]:
        return "critical", f"only {gb:.1f} GB free"
    if gb < t["warn_gb"] or (total and 100 * free_after / total < t["warn_percent"]):
        return "warn", f"{gb:.0f} GB free ({100 * free_after / total:.0f}%)"
    return "ok", ""


def _projects_by_volume() -> dict[str, list[ProjectUse]]:
    """Known projects (recent ones) grouped by the volume they live on, sized from their clips."""
    out: dict[str, list[ProjectUse]] = {}
    for r in store.recent_projects(50, include_hidden=True):      # a removed list entry still takes up space
        root = Path(r["root"])
        if not root.exists():
            continue
        p = Project.load(root)
        if p is None:
            continue
        footage = sum(c.size for c in p.clips.values())
        from hypershutter.core import proxies
        px = sum(f.stat().st_size for f in (root / proxies.PROXY_DIR).rglob("*.mov")) if (root / proxies.PROXY_DIR).is_dir() else 0
        out.setdefault(_volume_of(root), []).append(ProjectUse(p.name.strip(), str(root), footage, px))
    return out


def _volume_of(path: Path) -> str:
    parts = Path(path).resolve().parts
    return str(Path(*parts[:3])) if len(parts) >= 3 and parts[1] == "Volumes" else "/"


def planned_bytes() -> dict[str, int]:
    """Bytes the queued proxy / export jobs will still write, per volume (rough, from the presets)."""
    from hypershutter.core import jobs as jobs_mod
    out: dict[str, int] = {}
    for j in jobs_mod.read_all():
        if j.status not in (jobs_mod.QUEUED, jobs_mod.RUNNING):
            continue
        src = Path(j.project) / j.rel
        ratio = 0.35 if j.kind == "proxy" else 0.25
        try:
            size = int(src.stat().st_size * ratio * (1 - j.progress))
        except OSError:
            continue
        v = _volume_of(Path(j.out))
        out[v] = out.get(v, 0) + size
    return out


def drives(volumes: Path = VOLUMES, with_projects: bool = True) -> list[Drive]:
    t = thresholds()
    projects = _projects_by_volume() if with_projects else {}
    planned = planned_bytes()
    out = []
    roots = [Path("/")] + (sorted(v for v in volumes.iterdir() if v.is_dir() and not v.is_symlink()) if volumes.exists() else [])
    seen: set[tuple[int, int]] = set()
    for v in roots:
        try:
            u = shutil.disk_usage(v)
        except OSError:
            continue
        if (u.total, u.used) in seen:                # another volume of the same APFS container
            continue
        seen.add((u.total, u.used))
        d = Drive(str(v), "Macintosh HD" if str(v) == "/" else v.name, u.total, u.used, u.free,
                  is_card=str(v) != "/" and cards.looks_like_card(v), is_system=str(v) == "/",
                  projects=projects.get(str(v), []), planned=planned.get(str(v), 0))
        d.status, d.message = classify(d.total, d.free_after, t)
        out.append(d)
    return out


def space_problem(dest: Path, need: int) -> dict | None:
    """What does not fit when `need` bytes go on dest's drive with the warning margin left."""
    p = Path(dest)
    while not p.exists():
        p = p.parent
    u = shutil.disk_usage(p)
    after = u.free - need - planned_bytes().get(_volume_of(p), 0)
    if after < thresholds()["critical_gb"] * 1e9:
        return {"path": str(p), "need_gb": round(need / 1e9, 1), "free_gb": round(u.free / 1e9, 1)}
    return None


def check_space(dest: Path, need: int) -> str | None:
    """The same as an English sentence (CLI, errors)."""
    x = space_problem(dest, need)
    return f"{x['path']}: needs {x['need_gb']:.1f} GB, {x['free_gb']:.1f} GB free" if x else None


def as_dict(d: Drive) -> dict:
    x = asdict(d)
    x["free_after"] = d.free_after
    return x
