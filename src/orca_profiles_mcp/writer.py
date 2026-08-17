"""Writing profiles in Orca's own format.

Preset::save (Preset.cpp:671): with a parent present, only the delta against
the fully expanded parent is stored; the *_extruder_id and *_extruder_variant
keys are always included.
ConfigBase::save_to_json (Config.cpp:1516): the object is a std::map, so keys
are alphabetical in the file and the file ends with a newline.
Preset::save_info (Preset.cpp:623): the paired .info file is INI-formatted.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index import IndexEntry, ProfileIndex
from .models import META_KEYS
from .resolver import Resolver
from .snapshot import EngineSnapshot

INFO_FIELDS = ("sync_info", "user_id", "setting_id", "base_id", "updated_time")
DEFAULT_INDENT = "    "
SETTINGS_ID_KEY = {
    "process": "print_settings_id",
    "filament": "filament_settings_id",
    "machine": "printer_settings_id",
}


def detect_indent(path: Path) -> str:
    """Indent style of an existing file: Orca 2.4.2 writes 4 spaces, master a tab."""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError:
        return DEFAULT_INDENT
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped and stripped != "}":
            return line[: len(line) - len(stripped)] or DEFAULT_INDENT
    return DEFAULT_INDENT


def directory_indent(directory: Path) -> str:
    """Prevailing indent style in a directory, for newly created files."""
    counts: dict[str, int] = {}
    for path in sorted(directory.glob("*.json"))[:20]:
        indent = detect_indent(path)
        counts[indent] = counts.get(indent, 0) + 1
    if not counts:
        return DEFAULT_INDENT
    return max(counts.items(), key=lambda kv: kv[1])[0]


def write_profile_json(path: Path, data: dict, indent: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_info(path: Path) -> dict[str, str]:
    info = {field: "" for field in INFO_FIELDS}
    if not path.exists():
        return info
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key in INFO_FIELDS:
            info[key] = value.strip()
    return info


def write_info(path: Path, info: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{field} = {info.get(field, '')}\n" for field in INFO_FIELDS),
        encoding="utf-8",
    )


def compute_delta(
    parent_values: dict[str, Any],
    target_values: dict[str, Any],
    ptype: str,
    snapshot: EngineSnapshot,
    child_raw: dict,
) -> dict[str, Any]:
    """Keys differing from the expanded parent, plus the mandatory variant keys."""
    delta = {
        key: value
        for key, value in target_values.items()
        if key not in META_KEYS and parent_values.get(key) != value
    }
    for key in (snapshot.id_key(ptype), snapshot.variant_key(ptype)):
        if key and key in child_raw:
            delta[key] = child_raw[key]
    return delta


@dataclass
class Writer:
    index: ProfileIndex
    resolver: Resolver
    snapshot: EngineSnapshot

    # --- helpers ---

    def _backup(self, path: Path, enabled: bool) -> str | None:
        if not enabled or not path.exists():
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = path.with_suffix(path.suffix + f".bak-{stamp}")
        counter = 1
        while target.exists():
            target = path.with_suffix(path.suffix + f".bak-{stamp}-{counter}")
            counter += 1
        shutil.copy2(path, target)
        return str(target)

    def _parent_values(self, entry: IndexEntry, raw: dict) -> dict[str, Any]:
        parent_name = raw.get("inherits")
        if not parent_name:
            return dict(self.snapshot.defaults)
        parent_entry, _ = self.resolver._find_parent(entry.type, parent_name)
        if parent_entry is None:
            raise KeyError(f"parent {parent_name!r} not found for {entry.name!r}")
        resolved = self.resolver.resolve(parent_entry.type, parent_entry.name)
        return {key: rv.value for key, rv in resolved.values.items()}

    def _warnings_for(self, entry: IndexEntry) -> list[str]:
        warnings = []
        if entry.source != "user":
            warnings.append(
                f"profile belongs to source {entry.source!r}: the change affects every "
                f"descendant and will be overwritten by a profile library update"
            )
        children = self.index.children_of(entry.type, entry.name)
        if children:
            listed = ", ".join(c.name for c in children[:5])
            more = "…" if len(children) > 5 else ""
            warnings.append(f"{len(children)} profiles inherit from it: {listed}{more}")
        return warnings

    def _write(self, entry: IndexEntry, data: dict, backup: bool) -> str | None:
        backup_path = self._backup(entry.file, backup)
        write_profile_json(entry.file, data, detect_indent(entry.file))
        info_path = entry.file.with_suffix(".info")
        info = read_info(info_path)
        info["updated_time"] = str(int(time.time()))
        write_info(info_path, info)
        return backup_path

    # --- operations ---

    def set_values(
        self, ptype: str, name: str, values: dict[str, Any], backup: bool = True
    ) -> dict:
        entry = self.index.get(ptype, name)
        if entry is None:
            raise KeyError(f"profile not found: {ptype}/{name}")
        raw = dict(self.index.load_raw(entry))

        unknown = [k for k in values if not self.snapshot.is_known_key(k)]
        if unknown:
            raise ValueError(f"unknown to the engine: {', '.join(sorted(unknown))}")

        resolved = self.resolver.resolve(ptype, name)
        target = {key: rv.value for key, rv in resolved.values.items()}
        target.update(values)

        parent_values = self._parent_values(entry, raw)
        delta = compute_delta(parent_values, target, ptype, self.snapshot, raw)

        meta = {k: v for k, v in raw.items() if k in META_KEYS}
        data = {**meta, **delta}
        removed = sorted(set(raw) - set(data))

        backup_path = self._write(entry, data, backup)
        self.index.invalidate(entry)
        return {
            "file": str(entry.file),
            "written_keys": sorted(delta),
            "removed_keys": removed,
            "backup": backup_path,
            "warnings": self._warnings_for(entry),
        }

    def create_profile(
        self,
        ptype: str,
        name: str,
        inherits: str,
        values: dict[str, Any],
        backup: bool = True,
    ) -> dict:
        if self.index.get(ptype, name) is not None:
            raise ValueError(f"profile already exists: {ptype}/{name}")
        parent_entry, _ = self.resolver._find_parent(ptype, inherits)
        if parent_entry is None:
            raise KeyError(f"parent not found: {inherits}")
        user_dir = self.index.user_dir
        if user_dir is None:
            raise RuntimeError("no user profile directory found")

        path = user_dir / ptype / f"{name}.json"
        data = {
            "name": name,
            "from": "User",
            "version": self.snapshot.orca_version,
            "inherits": parent_entry.name,
            "is_custom_defined": "0",
            SETTINGS_ID_KEY[ptype]: name,
            **values,
        }
        write_profile_json(path, data, directory_indent(path.parent))
        write_info(
            path.with_suffix(".info"),
            {
                "sync_info": "",
                "user_id": self.index.user_id or "",
                "setting_id": "",
                "base_id": "",
                "updated_time": str(int(time.time())),
            },
        )
        self.index.add_user_profile(ptype, name, path)
        return {
            "file": str(path),
            "written_keys": sorted(values),
            "removed_keys": [],
            "backup": None,
            "warnings": [],
        }

    def rename_profile(self, ptype: str, name: str, new_name: str) -> dict:
        entry = self.index.get(ptype, name)
        if entry is None:
            raise KeyError(f"profile not found: {ptype}/{name}")
        if entry.source != "user":
            raise ValueError("renaming is only supported for user profiles")
        if self.index.get(ptype, new_name) is not None:
            raise ValueError(f"profile already exists: {ptype}/{new_name}")

        raw = dict(self.index.load_raw(entry))
        raw["name"] = new_name
        if SETTINGS_ID_KEY[ptype] in raw:
            raw[SETTINGS_ID_KEY[ptype]] = new_name

        new_path = entry.file.with_name(f"{new_name}.json")
        write_profile_json(new_path, raw, detect_indent(entry.file))
        info = read_info(entry.file.with_suffix(".info"))
        info["updated_time"] = str(int(time.time()))
        write_info(new_path.with_suffix(".info"), info)

        entry.file.unlink(missing_ok=True)
        entry.file.with_suffix(".info").unlink(missing_ok=True)

        children = self.index.children_of(ptype, name)
        self.index.remove_profile(ptype, name)
        self.index.add_user_profile(ptype, new_name, new_path)
        warnings = (
            [
                "profiles still referencing the old name: "
                + ", ".join(c.name for c in children)
            ]
            if children
            else []
        )
        return {
            "file": str(new_path),
            "written_keys": [],
            "removed_keys": [],
            "backup": None,
            "warnings": warnings,
        }

    def delete_profile(self, ptype: str, name: str) -> dict:
        entry = self.index.get(ptype, name)
        if entry is None:
            raise KeyError(f"profile not found: {ptype}/{name}")
        warnings = self._warnings_for(entry)

        info_path = entry.file.with_suffix(".info")
        info = read_info(info_path)
        entry.file.unlink(missing_ok=True)
        if info.get("setting_id"):
            # Preset::remove_files: a cloud-synced profile is flagged, not erased
            info["sync_info"] = "delete"
            write_info(info_path, info)
        else:
            info_path.unlink(missing_ok=True)

        self.index.remove_profile(ptype, name)
        return {
            "file": str(entry.file),
            "written_keys": [],
            "removed_keys": [],
            "backup": None,
            "warnings": warnings,
        }

    def normalize_profile(self, ptype: str, name: str, backup: bool = True) -> dict:
        return self.set_values(ptype, name, {}, backup=backup)
