"""Map of "profile type + name -> file".

System profiles come from the lists inside <Vendor>.json (machine_list,
process_list, filament_list, machine_model_list; each item is {name, sub_path}).
User profiles are scanned recursively: they carry no "type" field, so the type
comes from the directory (machine/ process/ filament/) and the name is read
from the "name" field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .sources import PROFILE_TYPES, Setup

_LIST_KEYS = {
    "machine_list": "machine",
    "process_list": "process",
    "filament_list": "filament",
    "machine_model_list": "machine_model",
}


@dataclass(frozen=True)
class IndexEntry:
    type: str
    name: str
    vendor: str
    source: str
    file: Path


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


class UnreadableProfile(dict):
    """An empty mapping that remembers why the file could not be read.

    A failed read used to become a plain `{}`, indistinguishable from a profile
    that genuinely sets nothing — so a corrupt file silently resolved to engine
    defaults with no diagnostic anywhere.
    """

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


class ProfileIndex:
    def __init__(
        self,
        entries: dict[tuple[str, str], IndexEntry],
        shadowed: dict[tuple[str, str], list[IndexEntry]],
        user_dir: Path | None = None,
        user_id: str | None = None,
    ) -> None:
        self._entries = entries
        self._shadowed = shadowed
        self._user_dir = user_dir
        self._user_id = user_id
        self._raw_cache: dict[Path, dict] = {}
        self._children: dict[tuple[str, str], list[IndexEntry]] | None = None
        self._renamed: dict[tuple[str, str], IndexEntry] | None = None

    # --- construction ---

    @classmethod
    def build(cls, setup: Setup) -> "ProfileIndex":
        entries: dict[tuple[str, str], IndexEntry] = {}
        shadowed: dict[tuple[str, str], list[IndexEntry]] = {}
        def add(entry: IndexEntry) -> None:
            key = (entry.type, entry.name)
            if key in entries:
                shadowed.setdefault(key, []).append(entry)
            else:
                entries[key] = entry

        # vendor_roots is already ordered by precedence
        for root in setup.vendor_roots:
            for vendor_file in sorted(root.path.glob("*.json")):
                data = _load_json(vendor_file)
                if not isinstance(data, dict):
                    continue
                if not any(k in data for k in _LIST_KEYS):
                    continue  # not a vendor file (blacklist.json and friends)
                vendor = data.get("name") or vendor_file.stem
                vendor_dir = root.path / vendor_file.stem
                for list_key, ptype in _LIST_KEYS.items():
                    for item in data.get(list_key) or []:
                        sub_path = item.get("sub_path")
                        name = item.get("name")
                        if not sub_path or not name:
                            continue
                        add(
                            IndexEntry(
                                ptype, name, vendor, root.source, vendor_dir / sub_path
                            )
                        )

        if setup.user_dir is not None:
            for ptype in PROFILE_TYPES:
                type_dir = setup.user_dir / ptype
                if not type_dir.is_dir():
                    continue
                for path in sorted(type_dir.rglob("*.json")):
                    # Orca keeps sync backups in dot-directories such as
                    # .sync_bak; indexing those reports every backed-up profile
                    # as a name collision with its live original.
                    if any(part.startswith(".") for part in path.relative_to(type_dir).parts):
                        continue
                    data = _load_json(path)
                    # An unreadable file is still indexed, under its filename, so
                    # it can be reported rather than vanishing from every view.
                    name = data.get("name") or path.stem if isinstance(data, dict) else path.stem
                    add(IndexEntry(ptype, name, "", "user", path))

        return cls(entries, shadowed, setup.user_dir, setup.user_id)

    # --- access ---

    @property
    def user_dir(self) -> Path | None:
        return self._user_dir

    @property
    def user_id(self) -> str | None:
        return self._user_id

    def get(self, ptype: str, name: str) -> IndexEntry | None:
        return self._entries.get((ptype, name))

    def all(self, ptype: str | None = None) -> list[IndexEntry]:
        return [e for e in self._entries.values() if ptype is None or e.type == ptype]

    def load_raw(self, entry: IndexEntry) -> dict:
        cached = self._raw_cache.get(entry.file)
        if cached is None:
            loaded = _load_json(entry.file)
            if loaded is None:
                reason = (
                    "file is missing"
                    if not entry.file.exists()
                    else "file is not readable JSON"
                )
                cached = UnreadableProfile(reason)
            else:
                cached = loaded
            self._raw_cache[entry.file] = cached
        return cached

    def collisions(self) -> list[tuple[str, str, list[IndexEntry]]]:
        """Profiles shadowed by a same-named one from a higher-priority source."""
        return [
            (ptype, name, [self._entries[(ptype, name)], *extra])
            for (ptype, name), extra in self._shadowed.items()
        ]

    def children_of(self, ptype: str, name: str) -> list[IndexEntry]:
        if self._children is None:
            children: dict[tuple[str, str], list[IndexEntry]] = {}
            for entry in self._entries.values():
                if entry.type == "machine_model":
                    continue
                parent = self.load_raw(entry).get("inherits")
                if parent:
                    children.setdefault((entry.type, parent), []).append(entry)
            self._children = children
        return sorted(self._children.get((ptype, name), []), key=lambda e: e.name)

    def renamed(self, ptype: str, old_name: str) -> IndexEntry | None:
        """Profiles declare former names in renamed_from (Preset.cpp:3813)."""
        if self._renamed is None:
            mapping: dict[tuple[str, str], IndexEntry] = {}
            for entry in self._entries.values():
                for old in self.load_raw(entry).get("renamed_from") or []:
                    mapping.setdefault((entry.type, old), entry)
            self._renamed = mapping
        return self._renamed.get((ptype, old_name))

    # --- mutation, used by the writer ---

    def _reset_derived(self) -> None:
        self._children = None
        self._renamed = None

    def invalidate(self, entry: IndexEntry) -> None:
        self._raw_cache.pop(entry.file, None)
        self._reset_derived()

    def add_user_profile(self, ptype: str, name: str, path: Path) -> None:
        self._entries[(ptype, name)] = IndexEntry(ptype, name, "", "user", path)
        self._raw_cache.pop(path, None)
        self._reset_derived()

    def remove_profile(self, ptype: str, name: str) -> None:
        entry = self._entries.pop((ptype, name), None)
        if entry is not None:
            self._raw_cache.pop(entry.file, None)
        # A same-named profile from a lower-priority source now becomes visible,
        # exactly as it would after the application reloaded its libraries.
        shadowed = self._shadowed.get((ptype, name))
        if shadowed:
            self._entries[(ptype, name)] = shadowed.pop(0)
            if not shadowed:
                self._shadowed.pop((ptype, name), None)
        else:
            self._shadowed.pop((ptype, name), None)
        self._reset_derived()
