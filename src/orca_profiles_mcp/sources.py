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


def _pick_user_dir(datadir: Path) -> tuple[str | None, Path | None]:
    """The active user directory is the one holding profile subdirectories."""
    root = datadir / "user"
    if not root.is_dir():
        return None, None
    candidates = [
        d
        for d in root.iterdir()
        if d.is_dir()
        and d.name != "default"
        and any((d / t).is_dir() for t in PROFILE_TYPES)
    ]
    if not candidates:
        return None, None
    chosen = max(candidates, key=lambda d: d.stat().st_mtime)
    return chosen.name, chosen


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

    user_id, user_dir = _pick_user_dir(datadir)
    version, selected = _read_conf(datadir)

    return Setup(
        datadir=datadir,
        resources=resources,
        user_id=user_id,
        user_dir=user_dir,
        vendor_roots=tuple(roots),
        app_version=version,
        selected=selected,
    )
