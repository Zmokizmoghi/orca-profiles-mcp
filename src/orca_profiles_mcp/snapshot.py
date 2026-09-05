"""Snapshot of Orca's built-in engine values.

Type-to-key mapping follows Preset::get_extruder_names_and_keysets,
Preset.cpp:927.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOT_PATH = Path(__file__).parent / "data" / "engine-snapshot.json"

# profile type -> (extruder id key, extruder variant key, stride-1 set, stride-2 set)
_TYPE_KEYS: dict[str, tuple[str | None, str | None, str | None, str | None]] = {
    "process": ("print_extruder_id", "print_extruder_variant", "print", None),
    "machine": (
        "printer_extruder_id",
        "printer_extruder_variant",
        "printer_1",
        "printer_2",
    ),
    "filament": (None, "filament_extruder_variant", "filament", None),
}


@dataclass(frozen=True)
class EngineSnapshot:
    orca_version: str
    defaults: dict[str, Any]
    variant_sets: dict[str, frozenset[str]]
    type_options: dict[str, frozenset[str]]
    categories: dict[str, str]
    option_types: dict[str, str]

    @classmethod
    def load(cls, path: Path | None = None) -> "EngineSnapshot":
        raw = json.loads((path or DEFAULT_SNAPSHOT_PATH).read_text(encoding="utf-8"))
        return cls(
            orca_version=raw["orca_version"],
            defaults=raw["defaults"],
            variant_sets={k: frozenset(v) for k, v in raw["variant_sets"].items()},
            type_options={
                k: frozenset(v) for k, v in raw.get("type_options", {}).items()
            },
            categories=raw["categories"],
            option_types=raw["option_types"],
        )

    def allowed_keys(self, ptype: str) -> frozenset[str] | None:
        """Keys this profile type may hold, or None when the type is unknown.

        Orca drops everything else at load time (Preset::remove_invalid_keys,
        Preset.cpp:1766): a process key sitting in a machine profile has no
        effect on the print.
        """
        return self.type_options.get(ptype)

    def keysets_for(self, ptype: str) -> tuple[frozenset[str], frozenset[str]]:
        _, _, set1, set2 = _TYPE_KEYS.get(ptype, (None, None, None, None))
        return (
            self.variant_sets.get(set1, frozenset()) if set1 else frozenset(),
            self.variant_sets.get(set2, frozenset()) if set2 else frozenset(),
        )

    def id_key(self, ptype: str) -> str | None:
        return _TYPE_KEYS.get(ptype, (None, None, None, None))[0]

    def variant_key(self, ptype: str) -> str | None:
        return _TYPE_KEYS.get(ptype, (None, None, None, None))[1]

    def is_known_key(self, key: str) -> bool:
        """Whether the engine recognises this key at all.

        Three sources, and none of them alone is complete. The filament retract
        overrides (filament_retraction_length and friends) appear only in the
        per-type option lists: they carry no engine default and are not declared
        through PrintConfigDef::add, so checking defaults and types alone
        reported every one of them as unknown.
        """
        if key in self.defaults or key in self.option_types:
            return True
        return any(key in keys for keys in self.type_options.values())
