"""Merging vector values bound to extruder variants.

Port of DynamicPrintConfig::update_diff_values_to_child_config,
PrintConfig.cpp:11377. Vector elements correspond to (extruder_variant,
extruder_id) pairs rather than to positions; for the
printer_options_with_variant_2 set each variant occupies two consecutive
values (stride 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NIL = "nil"


@dataclass(frozen=True)
class VariantContext:
    mapping: list[int]
    set1: frozenset[str]
    set2: frozenset[str]


def variant_index(
    parent_variants: list[str],
    child_variants: list[str],
    parent_ids: list[str],
    child_ids: list[str],
) -> list[int]:
    """For each parent variant, the index of the matching child variant, or -1."""
    if not parent_variants:
        return [0]
    mapping = [-1] * len(parent_variants)
    if not child_variants:
        mapping[0] = 0
        return mapping
    for i, parent_variant in enumerate(parent_variants):
        for j, child_variant in enumerate(child_variants):
            if parent_variant != child_variant:
                continue
            if parent_ids and child_ids:
                if i >= len(parent_ids) or j >= len(child_ids):
                    continue
                if parent_ids[i] != child_ids[j]:
                    continue
            mapping[i] = j
            break
    return mapping


def extend_to_length(values: list[str], length: int) -> list[str]:
    """Pad a vector to `length` by repeating its last element.

    Orca sizes variant vectors by the extruder count of the profile being
    loaded (extend_default_config_length, Preset.cpp:231): machine vectors take
    len(nozzle_diameter), or the explicit *_extruder_variant list when present.

    We apply this to the parent as well when a child declares more extruders
    than its parent. The engine's own merge keeps the parent's length here,
    which drops the extra extruders' values; the deltas Orca writes for such
    profiles contain the full-length vector, so padding is what reproduces its
    recorded output. A single-extruder parent under a toolchanger child is the
    case that makes the difference visible.
    """
    if length <= len(values) or not values:
        return list(values)
    return list(values) + [values[-1]] * (length - len(values))


def merge_vector(
    parent_value: list[str], child_value: list[str], mapping: list[int], stride: int
) -> list[str]:
    """Move the child's values into the parent's slots according to mapping."""
    if len(parent_value) != len(mapping) * stride:
        # Orca falls back to the child value here (PrintConfig.cpp:11455)
        return list(child_value)
    merged = list(parent_value)
    for parent_slot, child_slot in enumerate(mapping):
        if child_slot < 0:
            continue
        for offset in range(stride):
            source = child_slot * stride + offset
            target = parent_slot * stride + offset
            if source < len(child_value):
                merged[target] = child_value[source]
    return merged


def split_with_nil(
    parent_value: list[str], child_value: list[str], stride: int
) -> list[str]:
    """Replace elements equal to the parent's with "nil".

    Port of ConfigOptionVectorBase::set_with_nil, called from Preset::save
    (Preset.cpp:718-724): only genuinely changed elements are stored, the rest
    keep inheriting from the parent element by element.
    """
    if len(parent_value) != len(child_value) or stride <= 0:
        return list(child_value)
    result = list(child_value)
    for start in range(0, len(child_value), stride):
        chunk_child = child_value[start : start + stride]
        chunk_parent = parent_value[start : start + stride]
        if chunk_child == chunk_parent:
            for offset in range(len(chunk_child)):
                result[start + offset] = NIL
    return result


def merge_key(key: str, parent_value: Any, child_value: Any, ctx: VariantContext) -> Any:
    """The value of a key after applying the child on top of the parent."""
    if not isinstance(child_value, list) or not isinstance(parent_value, list):
        return child_value
    if key in ctx.set2:
        return merge_vector(parent_value, child_value, ctx.mapping, stride=2)
    if key in ctx.set1:
        return merge_vector(parent_value, child_value, ctx.mapping, stride=1)
    return child_value
