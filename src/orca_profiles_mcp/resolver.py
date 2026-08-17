"""Expanding the profile inheritance chain.

Merge semantics follow Preset.cpp:1743-1746: the child's config is applied on
top of the fully expanded parent config. The root of the chain is backed by the
engine defaults.
"""

from __future__ import annotations

from .index import IndexEntry, ProfileIndex
from .models import (
    META_KEYS,
    ChainLink,
    Diagnostic,
    Override,
    ResolvedProfile,
    ResolvedValue,
)
from .snapshot import EngineSnapshot

MAX_CHAIN_DEPTH = 32


class Resolver:
    def __init__(self, index: ProfileIndex, snapshot: EngineSnapshot) -> None:
        self.index = index
        self.snapshot = snapshot

    # --- parent name resolution ---

    def _find_parent(self, ptype: str, name: str) -> tuple[IndexEntry | None, str]:
        entry = self.index.get(ptype, name)
        if entry is not None:
            return entry, "exact"
        return None, "missing"

    # --- chain ---

    def _build_chain(
        self, entry: IndexEntry, diagnostics: list[Diagnostic]
    ) -> list[tuple[IndexEntry, str]]:
        """Profile to root. Each item is (index entry, how it was resolved)."""
        chain: list[tuple[IndexEntry, str]] = [(entry, "self")]
        seen = {(entry.type, entry.name)}
        current = entry

        while len(chain) < MAX_CHAIN_DEPTH:
            parent_name = self.index.load_raw(current).get("inherits")
            if not parent_name:
                break
            if (current.type, parent_name) in seen:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "cycle",
                        f"inheritance cycle: {parent_name} already appears in the chain",
                        link=parent_name,
                    )
                )
                break
            parent, resolution = self._find_parent(current.type, parent_name)
            if parent is None:
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "missing_parent",
                        f"parent {parent_name!r} not found; "
                        f"Orca will skip profile {current.name!r} on load",
                        link=parent_name,
                    )
                )
                break
            if resolution != "exact":
                diagnostics.append(
                    Diagnostic(
                        "warning",
                        resolution,
                        f"parent {parent_name!r} resolved to {parent.name!r} "
                        f"via {resolution}",
                        link=parent.name,
                    )
                )
            chain.append((parent, resolution))
            seen.add((parent.type, parent.name))
            current = parent
        else:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "chain_too_deep",
                    f"chain longer than {MAX_CHAIN_DEPTH} links, traversal stopped",
                )
            )
        return chain

    # --- merge ---

    def _merge(
        self, ptype: str, chain: list[tuple[IndexEntry, str]]
    ) -> dict[str, ResolvedValue]:
        # --export-settings emits the header fields (name, from, version) alongside
        # the settings, so META_KEYS are filtered out of the defaults too.
        values: dict[str, ResolvedValue] = {
            key: ResolvedValue(
                value=value, origin="<engine defaults>", origin_file="", is_default=True
            )
            for key, value in self.snapshot.defaults.items()
            if key not in META_KEYS
        }
        # root first, profile last
        for entry, _ in reversed(chain):
            raw = self.index.load_raw(entry)
            for key, value in raw.items():
                if key in META_KEYS:
                    continue
                previous = values.get(key)
                overridden = []
                if previous is not None and not previous.is_default:
                    overridden = [
                        Override(previous.origin, previous.value),
                        *previous.overridden,
                    ]
                values[key] = ResolvedValue(
                    value=value,
                    origin=entry.name,
                    origin_file=str(entry.file),
                    overridden=overridden,
                    is_default=False,
                )
        return values

    # --- entry point ---

    def resolve(self, ptype: str, name: str) -> ResolvedProfile:
        entry = self.index.get(ptype, name)
        if entry is None:
            raise KeyError(f"profile not found: {ptype}/{name}")

        diagnostics: list[Diagnostic] = []
        chain = self._build_chain(entry, diagnostics)
        values = self._merge(ptype, chain)

        links = []
        for link_entry, resolution in chain:
            raw = self.index.load_raw(link_entry)
            links.append(
                ChainLink(
                    name=link_entry.name,
                    vendor=link_entry.vendor,
                    source=link_entry.source,
                    file=str(link_entry.file),
                    instantiation=raw.get("instantiation", "true") != "false",
                    resolution=resolution,
                    keys_defined=len([k for k in raw if k not in META_KEYS]),
                )
            )

        return ResolvedProfile(
            name=entry.name,
            type=entry.type,
            vendor=entry.vendor,
            source=entry.source,
            file=str(entry.file),
            chain=links,
            values=values,
            diagnostics=diagnostics,
        )
