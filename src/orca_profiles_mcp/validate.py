"""Integrity checks over the profile library."""

from __future__ import annotations

from .index import IndexEntry, ProfileIndex
from .models import META_KEYS, Diagnostic
from .resolver import Resolver
from .snapshot import EngineSnapshot


def _in_scope(entry: IndexEntry, scope: str) -> bool:
    if entry.type == "machine_model":
        return False
    if scope == "all":
        return True
    if scope == "user":
        return entry.source == "user"
    return entry.vendor == scope


def validate_library(
    index: ProfileIndex,
    resolver: Resolver,
    snapshot: EngineSnapshot,
    scope: str = "user",
) -> list[Diagnostic]:
    results: list[Diagnostic] = []

    for ptype, name, entries in index.collisions():
        if scope != "all" and not any(_in_scope(e, scope) for e in entries):
            continue
        sources = ", ".join(f"{e.source}/{e.vendor or 'user'}" for e in entries)
        results.append(
            Diagnostic(
                "warning",
                "name_collision",
                f"{ptype} {name!r} is defined in several sources: {sources}; "
                f"{entries[0].source} wins",
                link=name,
            )
        )

    for entry in index.all():
        if not _in_scope(entry, scope):
            continue
        raw = index.load_raw(entry)

        for key in raw:
            if key in META_KEYS:
                continue
            if not snapshot.is_known_key(key):
                results.append(
                    Diagnostic(
                        "warning",
                        "unknown_key",
                        f"the engine does not know key {key!r}; Orca drops it on load",
                        link=entry.name,
                        key=key,
                    )
                )

        try:
            resolved = resolver.resolve(entry.type, entry.name)
        except KeyError as err:  # profile vanished between scan and resolution
            results.append(
                Diagnostic("error", "missing_parent", str(err), link=entry.name)
            )
            continue

        for diagnostic in resolved.diagnostics:
            results.append(
                Diagnostic(
                    diagnostic.severity,
                    diagnostic.code,
                    f"{entry.name}: {diagnostic.message}",
                    link=entry.name,
                    key=diagnostic.key,
                )
            )

        parent_name = raw.get("inherits")
        if not parent_name:
            continue
        parent_entry, _ = resolver._find_parent(entry.type, parent_name)
        if parent_entry is None:
            continue
        parent_resolved = resolver.resolve(parent_entry.type, parent_entry.name)
        for key, value in raw.items():
            if key in META_KEYS:
                continue
            parent_value = parent_resolved.values.get(key)
            if parent_value is not None and parent_value.value == value:
                results.append(
                    Diagnostic(
                        "info",
                        "redundant_delta",
                        f"{entry.name}: key {key!r} equals the value from parent "
                        f"{parent_entry.name!r} and changes nothing",
                        link=entry.name,
                        key=key,
                    )
                )

    return results
