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
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index import IndexEntry, ProfileIndex
from .models import META_KEYS
from .resolver import Resolver
from .snapshot import EngineSnapshot
from .variants import split_with_nil

INFO_FIELDS = ("sync_info", "user_id", "setting_id", "base_id", "updated_time")
DEFAULT_INDENT = "    "
SETTINGS_ID_KEY = {
    "process": "print_settings_id",
    "filament": "filament_settings_id",
    "machine": "printer_settings_id",
}
# Option types whose value is a list of strings rather than a plain string.
_VECTOR_TYPE_PREFIXES = ("coStrings", "coFloats", "coInts", "coBools", "coPercents",
                         "coPoints", "coFloatsOrPercents", "coEnums")


def validate_profile_name(name: str) -> str:
    """Reject names that would write outside the profile directory.

    A profile name becomes a filename, and `dir / name` silently discards the
    directory when the name is absolute. Names arrive from tool calls, so they
    are untrusted input.
    """
    if not name or not name.strip():
        raise ValueError("profile name must not be empty")
    if name in (".", ".."):
        raise ValueError(f"invalid profile name: {name!r}")
    if any(sep in name for sep in ("/", "\\")):
        raise ValueError(f"profile name must not contain a path separator: {name!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ValueError("profile name must not contain control characters")
    return name


def is_vector_option(snapshot: EngineSnapshot, key: str, ptype: str = "") -> bool:
    """Whether this key is stored as a list of strings in a profile file.

    Two independent reasons make a key a vector, and the option's declared type
    only covers one of them. Keys bound to extruder variants hold one element
    per extruder regardless of their scalar type: outer_wall_speed is a coFloat
    whose engine default is "60", yet profiles store it as ["120"].
    """
    if isinstance(snapshot.defaults.get(key), list):
        return True
    if ptype:
        set1, set2 = snapshot.keysets_for(ptype)
        if key in set1 or key in set2:
            return True
    ctype = snapshot.option_types.get(key) or ""
    return ctype.startswith(_VECTOR_TYPE_PREFIXES)


def validate_values(
    snapshot: EngineSnapshot, ptype: str, values: dict[str, Any]
) -> None:
    """Check ownership, shape and representation before anything is written.

    Orca stores every setting as a string or a list of strings, drops keys that
    belong to another profile type, and would misread a scalar written as a
    vector. Catching that here keeps a malformed edit from reaching the file.
    """
    metadata = sorted(set(values) & META_KEYS)
    if metadata:
        raise ValueError(
            f"these keys are profile metadata and cannot be set as values: "
            f"{', '.join(metadata)}"
        )

    allowed = snapshot.allowed_keys(ptype)
    for key, value in values.items():
        if not snapshot.is_known_key(key):
            raise ValueError(f"unknown to the engine: {key}")
        if allowed is not None and key not in allowed:
            owners = [
                t for t in ("process", "machine", "filament")
                if key in (snapshot.allowed_keys(t) or ())
            ]
            owner = f" (it belongs to: {', '.join(owners)})" if owners else ""
            raise ValueError(
                f"{key!r} is not a {ptype} setting{owner}; Orca drops it on load"
            )

        wants_vector = is_vector_option(snapshot, key, ptype)
        if isinstance(value, list):
            if not wants_vector:
                raise ValueError(f"{key!r} is a scalar option, got a list")
            bad = [v for v in value if not isinstance(v, str)]
            if bad:
                raise ValueError(f"{key!r} must hold string elements, got {bad!r}")
        elif isinstance(value, str):
            if wants_vector:
                raise ValueError(f"{key!r} is a vector option, got a plain string")
        else:
            raise ValueError(
                f"{key!r} must be a string or a list of strings, got "
                f"{type(value).__name__}"
            )


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


def _write_atomically(path: Path, text: str) -> None:
    """Write through a temporary sibling and rename over the target.

    A direct truncating write leaves a half-written profile if the process dies
    or the disk fills — losing the file this tool exists to protect. os.replace
    is atomic within a filesystem, so a reader sees either the old file or the
    new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_profile_json(path: Path, data: dict, indent: str) -> None:
    _write_atomically(
        path, json.dumps(data, ensure_ascii=False, indent=indent, sort_keys=True) + "\n"
    )


def read_info(path: Path) -> dict[str, str]:
    info = {field: "" for field in INFO_FIELDS}
    if not path.exists():
        return info
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # unknown fields are kept so a rewrite does not drop them
        info[key.strip()] = value.strip()
    return info


def write_info(path: Path, info: dict[str, str]) -> None:
    known = "".join(f"{field} = {info.get(field, '')}\n" for field in INFO_FIELDS)
    # Fields a newer Orca may have added are carried through untouched.
    extra = "".join(
        f"{key} = {value}\n"
        for key, value in info.items()
        if key not in INFO_FIELDS
    )
    _write_atomically(path, known + extra)


def compute_delta(
    parent_values: dict[str, Any],
    target_values: dict[str, Any],
    ptype: str,
    snapshot: EngineSnapshot,
    child_raw: dict,
) -> dict[str, Any]:
    """Keys differing from the expanded parent, plus the mandatory variant keys."""
    set1, set2 = snapshot.keysets_for(ptype)
    delta: dict[str, Any] = {}

    for key, value in target_values.items():
        if key in META_KEYS:
            continue
        parent_value = parent_values.get(key)
        if parent_value == value:
            continue
        if (
            isinstance(value, list)
            and isinstance(parent_value, list)
            and (key in set1 or key in set2)
        ):
            stride = 2 if key in set2 else 1
            delta[key] = split_with_nil(parent_value, value, stride)
        else:
            delta[key] = value

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
        # Same vendor-first lookup the resolver uses: base profile names repeat
        # across vendors, and comparing against another vendor's base would drop
        # overrides that are genuinely needed.
        parent_entry, _ = self.resolver._find_parent(
            entry.type, parent_name, entry.vendor
        )
        if parent_entry is None:
            raise KeyError(f"parent {parent_name!r} not found for {entry.name!r}")
        resolved = self.resolver.resolve_entry(parent_entry)
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

    def _settings_id_value(self, ptype: str, name: str) -> Any:
        """filament_settings_id is coStrings; the print and printer ids are scalar."""
        key = SETTINGS_ID_KEY[ptype]
        return [name] if is_vector_option(self.snapshot, key) else name

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
        validate_values(self.snapshot, ptype, values)

        resolved = self.resolver.resolve(ptype, name)
        target = {key: rv.value for key, rv in resolved.values.items()}
        target.update(values)

        parent_values = self._parent_values(entry, raw)
        delta = compute_delta(parent_values, target, ptype, self.snapshot, raw)

        meta = {k: v for k, v in raw.items() if k in META_KEYS}
        # Keys the pinned snapshot does not know are carried through verbatim.
        # The snapshot is tied to one Orca version; a newer engine's settings
        # would otherwise be silently deleted from the file on the next edit.
        unknown = {
            k: v
            for k, v in raw.items()
            if k not in META_KEYS and not self.snapshot.is_known_key(k)
        }
        data = {**meta, **unknown, **delta}
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
        validate_profile_name(name)
        validate_values(self.snapshot, ptype, values)
        if self.index.get(ptype, name) is not None:
            raise ValueError(f"profile already exists: {ptype}/{name}")
        parent_entry, _ = self.resolver._find_parent(ptype, inherits)
        if parent_entry is None:
            raise KeyError(f"parent not found: {inherits}")
        user_dir = self.index.user_dir
        if user_dir is None:
            raise RuntimeError("no user profile directory found")

        path = user_dir / ptype / f"{name}.json"
        # The index skips unreadable files and keys entries by the profile's
        # internal name, so index membership is not proof the path is free.
        if path.exists():
            raise ValueError(f"a file already exists at {path}")
        data = {
            **values,
            # identity fields are written last: they define the profile and must
            # not be overridable through the values payload
            "name": name,
            "from": "User",
            "version": self.snapshot.orca_version,
            "inherits": parent_entry.name,
            "is_custom_defined": "0",
            SETTINGS_ID_KEY[ptype]: self._settings_id_value(ptype, name),
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
        validate_profile_name(new_name)
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
            raw[SETTINGS_ID_KEY[ptype]] = self._settings_id_value(ptype, new_name)

        new_path = entry.file.with_name(f"{new_name}.json")
        if new_path.exists() and new_path != entry.file:
            raise ValueError(f"a file already exists at {new_path}")
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
