"""Expanding the profile inheritance chain.

Merge semantics follow Preset.cpp:1743-1746: the child's config is applied on
top of the fully expanded parent config. The root of the chain is backed by the
engine defaults.
"""

from __future__ import annotations

import re

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
from .variants import VariantContext, extend_to_length, merge_key, variant_index

MAX_CHAIN_DEPTH = 32

# PresetCollection::find_preset2, Preset.cpp: when the parent is missing and the
# name contains "Generic", it is rewritten to "Generic <material> @System",
# which belongs to the OrcaFilamentLibrary vendor.
_GENERIC_RE = re.compile(r"^(?:.*?\b(?:\w+_)?)(Generic)\b\s+([^@]+?)\s*(?:@.*)?$")


def _variant_slots(ptype: str, raw: dict, variants: list[str]) -> int:
    """How many variant slots this profile's vectors span.

    extend_default_config_length, Preset.cpp:231: an explicit *_extruder_variant
    list wins; a machine profile otherwise takes its extruder count from
    nozzle_diameter.
    """
    if variants:
        return len(variants)
    if ptype == "machine":
        nozzles = raw.get("nozzle_diameter")
        if isinstance(nozzles, list) and nozzles:
            return len(nozzles)
    return 1


class Resolver:
    def __init__(self, index: ProfileIndex, snapshot: EngineSnapshot) -> None:
        self.index = index
        self.snapshot = snapshot

    # --- parent name resolution ---

    def _find_parent(
        self, ptype: str, name: str, vendor: str = ""
    ) -> tuple[IndexEntry | None, str]:
        # Deliberately global, matching the engine: PresetCollection::find_preset2
        # searches the whole collection in load order with no vendor scoping,
        # even though base names like fdm_machine_common repeat across 64
        # vendors. Preferring a profile's own vendor is intuitive but wrong —
        # measured against the deltas Orca wrote, it mismatches 65/113 Voron and
        # 221/565 Elegoo profiles, where the global lookup mismatches none.
        # The `vendor` argument is kept for call-site symmetry and diagnostics.
        entry = self.index.get(ptype, name)
        if entry is not None:
            return entry, "exact"

        renamed = self.index.renamed(ptype, name)
        if renamed is not None:
            return renamed, "renamed_from"

        if "Generic" in name:
            alternative = _GENERIC_RE.sub(r"Generic \2 @System", name)
            if alternative != name:
                entry = self.index.get(ptype, alternative)
                if entry is not None:
                    return entry, "generic_fallback"

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
            parent, resolution = self._find_parent(
                current.type, parent_name, current.vendor
            )
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
        self,
        ptype: str,
        chain: list[tuple[IndexEntry, str]],
        diagnostics: list[Diagnostic],
    ) -> dict[str, ResolvedValue]:
        allowed = self.snapshot.allowed_keys(ptype)

        def is_settable(key: str) -> bool:
            return key not in META_KEYS and (allowed is None or key in allowed)

        # --export-settings emits the header fields (name, from, version) alongside
        # the settings, so META_KEYS are filtered out of the defaults too.
        values: dict[str, ResolvedValue] = {
            key: ResolvedValue(
                value=value, origin="<engine defaults>", origin_file="", is_default=True
            )
            for key, value in self.snapshot.defaults.items()
            if is_settable(key)
        }
        set1, set2 = self.snapshot.keysets_for(ptype)
        id_key = self.snapshot.id_key(ptype)
        variant_key = self.snapshot.variant_key(ptype)

        accumulated_variants: list[str] = []
        accumulated_ids: list[str] = []

        # root first, profile last
        for entry, _ in reversed(chain):
            raw = self.index.load_raw(entry)
            child_variants = raw.get(variant_key, []) if variant_key else []
            child_ids = raw.get(id_key, []) if id_key else []
            mapping = variant_index(
                accumulated_variants, child_variants, accumulated_ids, child_ids
            )
            ctx = VariantContext(mapping=mapping, set1=set1, set2=set2)
            slots = _variant_slots(ptype, raw, child_variants)

            for key, value in raw.items():
                if key in META_KEYS:
                    continue
                if not is_settable(key):
                    diagnostics.append(
                        Diagnostic(
                            "warning",
                            "foreign_key",
                            f"{entry.name}: key {key!r} does not belong to a "
                            f"{ptype} profile; Orca drops it on load, so it has "
                            f"no effect",
                            link=entry.name,
                            key=key,
                        )
                    )
                    continue
                previous = values.get(key)
                # Engine defaults carry no variant layout, so per-slot merging
                # cannot apply to them: the first link's value is taken whole.
                inherited = previous is not None and not previous.is_default
                parent_value = previous.value if inherited else None
                # A child may declare more extruders than its parent; pad the
                # parent so the extra extruders keep a value instead of being
                # dropped.
                # Stride-2 keys (the machine limits) are excluded: real profiles
                # store one value per key even on multi-extruder machines, and
                # padding them contradicts the deltas Orca writes.
                if inherited and isinstance(parent_value, list) and key in set1:
                    parent_value = extend_to_length(parent_value, slots)
                # "nil" elements are resolved inside merge_key, once the child's
                # slots have been mapped onto the parent's — see merge_vector.
                merged = merge_key(key, parent_value, value, ctx) if inherited else value

                overridden = []
                if inherited:
                    overridden = [
                        Override(previous.origin, previous.value),
                        *previous.overridden,
                    ]
                values[key] = ResolvedValue(
                    value=merged,
                    origin=entry.name,
                    origin_file=str(entry.file),
                    overridden=overridden,
                    is_default=False,
                )

            if child_variants:
                accumulated_variants = list(child_variants)
            if child_ids:
                accumulated_ids = list(child_ids)

        return values

    # --- entry point ---

    def resolve(self, ptype: str, name: str) -> ResolvedProfile:
        entry = self.index.get(ptype, name)
        if entry is None:
            raise KeyError(f"profile not found: {ptype}/{name}")
        return self.resolve_entry(entry)

    def resolve_entry(self, entry: IndexEntry) -> ResolvedProfile:
        """Expand a specific index entry.

        Callers that already hold an entry must use this: looking the name up
        again would go through the global index and can land on a same-named
        profile from another vendor.
        """
        ptype = entry.type
        diagnostics: list[Diagnostic] = []
        chain = self._build_chain(entry, diagnostics)
        values = self._merge(ptype, chain, diagnostics)

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
