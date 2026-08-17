"""Verifying the resolver against deltas Orca itself wrote.

The Orca CLI cannot serve as an oracle for inheritance: --export-settings takes
the engine defaults plus the keys present in the files handed to it and does
not walk `inherits` at all (verified against v2.4.2 — a value defined only in a
parent comes back as the engine default). Selecting presets through
OrcaSlicer.conf does not activate them either, and passing a whole chain as a
file list is rejected with "duplicate machine config file".

What Orca does leave behind is evidence of its own expansion: when it saves a
user profile it stores the minimal delta against the fully expanded parent
(Preset::save, Preset.cpp:671). So a profile file written by Orca is a recorded
answer. Recomputing that delta with our resolver and comparing reproduces the
engine's expansion indirectly, on real data.

A mismatch means one of two things: our resolver expands the parent
differently, or the file was hand-edited after Orca last wrote it.
"""

from __future__ import annotations

from typing import Any

from .index import ProfileIndex
from .models import META_KEYS
from .resolver import Resolver
from .snapshot import EngineSnapshot
from .writer import compute_delta


def check_profile_delta(
    index: ProfileIndex,
    resolver: Resolver,
    snapshot: EngineSnapshot,
    ptype: str,
    name: str,
) -> dict:
    """Compare the delta stored in the file with the one we would compute."""
    entry = index.get(ptype, name)
    if entry is None:
        raise KeyError(f"profile not found: {ptype}/{name}")

    raw = index.load_raw(entry)
    parent_name = raw.get("inherits")
    if not parent_name:
        return {
            "name": name,
            "type": ptype,
            "checked": False,
            "reason": "root profile: no parent to compute a delta against",
        }
    parent_entry, _ = resolver._find_parent(ptype, parent_name)
    if parent_entry is None:
        return {
            "name": name,
            "type": ptype,
            "checked": False,
            "reason": f"parent {parent_name!r} not found",
        }

    allowed = snapshot.allowed_keys(ptype)
    stored: dict[str, Any] = {
        key: value
        for key, value in raw.items()
        if key not in META_KEYS and (allowed is None or key in allowed)
    }

    parent_resolved = resolver.resolve(parent_entry.type, parent_entry.name)
    parent_values = {key: rv.value for key, rv in parent_resolved.values.items()}
    resolved = resolver.resolve(ptype, name)
    target = {key: rv.value for key, rv in resolved.values.items()}
    recomputed = compute_delta(parent_values, target, ptype, snapshot, raw)

    only_stored = sorted(set(stored) - set(recomputed))
    only_recomputed = sorted(set(recomputed) - set(stored))
    differing = {
        key: {"stored": stored[key], "recomputed": recomputed[key]}
        for key in sorted(set(stored) & set(recomputed))
        if stored[key] != recomputed[key]
    }

    return {
        "name": name,
        "type": ptype,
        "checked": True,
        "parent": parent_entry.name,
        "stored_keys": len(stored),
        # Keys the file stores whose value already equals the parent's. Harmless:
        # the profile was written before the parent changed, or Orca simply kept
        # them. They change nothing and normalize_profile can remove them.
        "redundant_in_file": only_stored,
        # These two mean the resolver and the engine disagree about the parent.
        "we_would_add": only_recomputed,
        "differing_values": differing,
        "consistent": not (only_recomputed or differing),
        "redundant_only": bool(only_stored) and not (only_recomputed or differing),
    }


def check_library_deltas(
    index: ProfileIndex,
    resolver: Resolver,
    snapshot: EngineSnapshot,
    scope: str = "user",
) -> dict:
    """Run the delta check across a scope: "user", "all" or a vendor name."""
    results = []
    for entry in index.all():
        if entry.type == "machine_model":
            continue
        if scope == "user" and entry.source != "user":
            continue
        if scope not in ("user", "all") and entry.vendor != scope:
            continue
        results.append(
            check_profile_delta(index, resolver, snapshot, entry.type, entry.name)
        )

    checked = [r for r in results if r["checked"]]
    mismatched = [r for r in checked if not r["consistent"]]
    redundant = [r for r in checked if r.get("redundant_only")]
    return {
        "scope": scope,
        "profiles": len(results),
        "checked": len(checked),
        "skipped": len(results) - len(checked),
        "mismatched": len(mismatched),
        "with_redundant_keys": len(redundant),
        "details": mismatched,
        "redundant": [
            {"name": r["name"], "type": r["type"], "keys": r["redundant_in_file"]}
            for r in redundant
        ],
    }
