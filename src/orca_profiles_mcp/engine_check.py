"""Checking the resolver against the Orca engine via --export-settings.

Two constraints shape this module, both established by running the CLI:

1. The CLI only accepts profiles carrying a "type" field, and user profiles have
   none. A temporary copy with the type filled in is handed to it instead.
2. --export-settings always needs a machine *and* a process profile; either one
   alone is rejected. A filament profile is passed separately via
   --load-filaments. So checking one profile means picking companions for the
   other slots.

Only keys the profile chain actually sets are compared. Engine defaults are
shared across all three profile types, so comparing them would mostly measure
the companions rather than the profile under test.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .index import IndexEntry, ProfileIndex
from .models import META_KEYS
from .resolver import Resolver

# Keys the engine derives at load time and never stores in profile files.
ALWAYS_SKIP = {
    "print_settings_id",
    "filament_settings_id",
    "printer_settings_id",
    "inherits_group",
}


class EngineUnavailable(RuntimeError):
    """The CLI refused to load the profile set."""


def _typed_copy(raw: dict, ptype: str, directory: Path, name: str) -> Path:
    data = dict(raw)
    data.setdefault("type", ptype)
    # A slash in a profile name would be read as a directory separator.
    path = directory / f"{name.replace('/', '_')}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _instantiable(index: ProfileIndex, entry: IndexEntry) -> bool:
    return index.load_raw(entry).get("instantiation", "true") != "false"


def _pick_machine(index: ProfileIndex, entry: IndexEntry) -> IndexEntry | None:
    """The machine profile the given profile declares itself compatible with."""
    if entry.type == "machine":
        return entry
    for printer in index.load_raw(entry).get("compatible_printers") or []:
        found = index.get("machine", printer)
        if found is not None:
            return found
    return next(
        (e for e in index.all("machine") if _instantiable(index, e)),
        None,
    )


def _pick_process(index: ProfileIndex, machine: IndexEntry) -> IndexEntry | None:
    """A process profile compatible with the given machine."""
    default_profile = index.load_raw(machine).get("default_print_profile")
    if default_profile:
        found = index.get("process", default_profile)
        if found is not None:
            return found
    for candidate in index.all("process"):
        if not _instantiable(index, candidate):
            continue
        compatible = index.load_raw(candidate).get("compatible_printers") or []
        if machine.name in compatible:
            return candidate
    return next(
        (e for e in index.all("process") if _instantiable(index, e)),
        None,
    )


def build_profile_set(
    index: ProfileIndex, ptype: str, name: str, directory: Path
) -> tuple[list[Path], list[Path]]:
    """Files for --load-settings and --load-filaments covering the profile."""
    entry = index.get(ptype, name)
    if entry is None:
        raise KeyError(f"profile not found: {ptype}/{name}")

    machine = _pick_machine(index, entry)
    if machine is None:
        raise EngineUnavailable("no machine profile available to pair with")
    process = entry if ptype == "process" else _pick_process(index, machine)
    if process is None:
        raise EngineUnavailable("no process profile available to pair with")

    settings = [
        _typed_copy(index.load_raw(machine), "machine", directory, f"m-{machine.name}"),
        _typed_copy(index.load_raw(process), "process", directory, f"p-{process.name}"),
    ]
    filaments = []
    if ptype == "filament":
        filaments.append(
            _typed_copy(index.load_raw(entry), "filament", directory, f"f-{entry.name}")
        )
    return settings, filaments


def export_settings(
    binary: Path, datadir: Path, settings: list[Path], filaments: list[Path] | None = None
) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "settings.json"
        command = [
            str(binary),
            "--datadir",
            str(datadir),
            "--load-settings",
            ";".join(str(f) for f in settings),
        ]
        if filaments:
            command += ["--load-filaments", ";".join(str(f) for f in filaments)]
        command += ["--export-settings", str(out)]

        subprocess.run(command, check=True, capture_output=True, timeout=180)
        if not out.exists():
            # The CLI reports load failures on stdout and still exits with 0.
            raise EngineUnavailable("the engine did not produce a settings export")
        return json.loads(out.read_text(encoding="utf-8"))


def accepts_file(
    binary: Path, datadir: Path, index: ProfileIndex, ptype: str, name: str
) -> bool:
    """Whether the engine loads this profile without an error."""
    with tempfile.TemporaryDirectory() as tmp:
        settings, filaments = build_profile_set(index, ptype, name, Path(tmp))
        try:
            export_settings(binary, datadir, settings, filaments)
        except (subprocess.CalledProcessError, EngineUnavailable):
            return False
    return True


def compare_with_engine(
    resolver: Resolver,
    index: ProfileIndex,
    ptype: str,
    name: str,
    binary: Path,
    datadir: Path,
    allowlist: set[str] | None = None,
) -> dict:
    allowlist = (allowlist or set()) | ALWAYS_SKIP

    with tempfile.TemporaryDirectory() as tmp:
        settings, filaments = build_profile_set(index, ptype, name, Path(tmp))
        engine_values = export_settings(binary, datadir, settings, filaments)

    resolved = resolver.resolve(ptype, name)
    # Only keys this profile's chain sets: engine defaults are shared by all
    # three profile types and would compare the companions, not this profile.
    ours = {
        key: rv.value
        for key, rv in resolved.values.items()
        if key not in META_KEYS and not rv.is_default
    }

    mismatches = {}
    compared = 0
    missing_from_engine = []
    for key, value in ours.items():
        if key in allowlist:
            continue
        if key not in engine_values:
            missing_from_engine.append(key)
            continue
        compared += 1
        if value != engine_values[key]:
            mismatches[key] = {"ours": value, "engine": engine_values[key]}

    return {
        "compared_keys": compared,
        "mismatches": mismatches,
        "missing_from_engine": sorted(missing_from_engine),
        "skipped": sorted(allowlist & set(ours)),
    }
