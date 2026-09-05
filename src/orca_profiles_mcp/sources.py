"""Locating the roots that hold Orca profiles.

Source precedence follows PresetBundle.cpp:5213-5215: <datadir>/system first,
then the application resources directory.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROFILE_TYPES = ("machine", "process", "filament")

MACOS_DATADIR = Path.home() / "Library/Application Support/OrcaSlicer"
MACOS_RESOURCES = Path("/Applications/OrcaSlicer.app/Contents/Resources")


@dataclass(frozen=True)
class VendorRoot:
    source: str  # "datadir-system" | "bundle"
    path: Path  # directory holding <Vendor>.json and <Vendor>/


@dataclass(frozen=True)
class Setup:
    datadir: Path
    resources: Path
    user_id: str | None
    user_dir: Path | None
    vendor_roots: tuple[VendorRoot, ...]
    app_version: str | None
    selected: dict[str, str] = field(default_factory=dict)
    # Every profile tree found, not just the chosen one. Orca keeps one per
    # signed-in account and uses `default` when signed out, and nothing in its
    # config says which is live — so the ambiguity is surfaced, not hidden.
    user_dirs: tuple[Path, ...] = ()


def _newest_profile_mtime(directory: Path) -> float:
    """When this tree was last written, judged by its profiles, not the folder.

    A directory's own mtime only changes when entries are added or removed, so
    a tree whose profiles were all edited yesterday can look older than one
    nobody has touched in months.
    """
    newest = 0.0
    for ptype in PROFILE_TYPES:
        type_dir = directory / ptype
        if not type_dir.is_dir():
            continue
        for path in type_dir.rglob("*.json"):
            if any(part.startswith(".") for part in path.relative_to(type_dir).parts):
                continue
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
    return newest or directory.stat().st_mtime


def _find_user_dirs(datadir: Path) -> list[Path]:
    """Every tree that holds profiles, `default` included.

    `default` is where Orca writes when no account is signed in, so excluding
    it means reading and writing a tree the running application ignores.
    """
    root = datadir / "user"
    if not root.is_dir():
        return []
    return sorted(
        (d for d in root.iterdir()
         if d.is_dir() and any((d / t).is_dir() for t in PROFILE_TYPES)),
        key=lambda d: d.name,
    )


def _pick_user_dir(datadir: Path) -> tuple[str | None, Path | None, list[Path]]:
    candidates = _find_user_dirs(datadir)
    if not candidates:
        return None, None, []

    override = os.environ.get("ORCA_USER_DIR")
    if override:
        chosen = Path(override)
        return chosen.name, chosen, candidates

    chosen = max(candidates, key=_newest_profile_mtime)
    return chosen.name, chosen, candidates


def _read_conf(datadir: Path) -> tuple[str | None, dict[str, str]]:
    conf = datadir / "OrcaSlicer.conf"
    if not conf.exists():
        return None, {}
    try:
        raw = json.loads(conf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, {}
    header = raw.get("header") or ""
    version = header.split()[-1] if header else None
    selected = {
        k: v for k, v in (raw.get("presets") or {}).items() if isinstance(v, str)
    }
    return version, selected


def discover(datadir: Path | None = None, resources: Path | None = None) -> Setup:
    datadir = Path(datadir or os.environ.get("ORCA_DATADIR") or MACOS_DATADIR)
    resources = Path(resources or os.environ.get("ORCA_RESOURCES") or MACOS_RESOURCES)

    roots: list[VendorRoot] = []
    if (datadir / "system").is_dir():
        roots.append(VendorRoot("datadir-system", datadir / "system"))
    if (resources / "profiles").is_dir():
        roots.append(VendorRoot("bundle", resources / "profiles"))

    user_id, user_dir, user_dirs = _pick_user_dir(datadir)
    version, selected = _read_conf(datadir)

    return Setup(
        datadir=datadir,
        resources=resources,
        user_id=user_id,
        user_dir=user_dir,
        vendor_roots=tuple(roots),
        app_version=version,
        selected=selected,
        user_dirs=tuple(user_dirs),
    )
