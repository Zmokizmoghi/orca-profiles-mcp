import json

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.variants import (
    VariantContext,
    merge_key,
    merge_vector,
    variant_index,
)


def test_variant_index_matches_by_variant_name():
    # parent has two variants, child overrides only the second
    assert variant_index(["0.4", "0.6"], ["0.6"], [], []) == [-1, 0]


def test_variant_index_requires_matching_extruder_id():
    assert variant_index(["0.4", "0.4"], ["0.4"], ["1", "2"], ["2"]) == [-1, 0]


def test_variant_index_without_child_variants_takes_first():
    assert variant_index(["0.4", "0.6"], [], [], []) == [0, -1]


def test_merge_vector_stride_one_keeps_unmatched_parent_values():
    assert merge_vector(["0.8", "0.9"], ["1.5"], [-1, 0], stride=1) == ["0.8", "1.5"]


def test_merge_vector_stride_two_moves_pairs():
    parent = ["1000", "500", "2000", "800"]  # two variants, a pair each
    assert merge_vector(parent, ["3000", "900"], [-1, 0], stride=2) == [
        "1000",
        "500",
        "3000",
        "900",
    ]


def test_merge_vector_falls_back_to_child_on_length_mismatch():
    # parent length != len(mapping) * stride — Orca takes the child value
    assert merge_vector(["0.8"], ["1.5", "1.6"], [-1, 0], stride=1) == ["1.5", "1.6"]


def test_merge_key_replaces_scalar_wholesale():
    ctx = VariantContext([-1, 0], frozenset({"retraction_length"}), frozenset())
    assert merge_key("layer_height", "0.2", "0.16", ctx) == "0.16"


def test_merge_key_replaces_vector_outside_variant_sets():
    ctx = VariantContext([-1, 0], frozenset({"retraction_length"}), frozenset())
    assert merge_key("nozzle_diameter", ["0.4", "0.4"], ["0.6"], ctx) == ["0.6"]


def test_merge_key_uses_variant_mapping_for_known_keys():
    ctx = VariantContext([-1, 0], frozenset({"retraction_length"}), frozenset())
    assert merge_key("retraction_length", ["0.8", "0.9"], ["1.5"], ctx) == ["0.8", "1.5"]


def test_resolver_merges_variant_vector_per_extruder(orca_tree, write_profile):
    """The child overrides retraction_length for the second extruder only."""
    bundle = orca_tree["resources"] / "profiles"
    write_profile(
        bundle / "Acme/machine/Acme Dual.json",
        {
            "type": "machine",
            "name": "Acme Dual",
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "0.9"],
            "nozzle_diameter": ["0.4", "0.6"],
        },
    )
    write_profile(
        orca_tree["user_dir"] / "machine/Acme Dual Tuned.json",
        {
            "name": "Acme Dual Tuned",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Dual",
            "printer_extruder_variant": ["0.6"],
            "retraction_length": ["1.5"],
        },
    )
    vendor_file = bundle / "Acme.json"
    data = json.loads(vendor_file.read_text(encoding="utf-8"))
    data["machine_list"].append(
        {"name": "Acme Dual", "sub_path": "machine/Acme Dual.json"}
    )
    write_profile(vendor_file, data)

    resolver = Resolver(ProfileIndex.build(discover()), EngineSnapshot.load())
    resolved = resolver.resolve("machine", "Acme Dual Tuned")
    assert resolved.values["retraction_length"].value == ["0.8", "1.5"]


def test_engine_defaults_do_not_drive_variant_merging(orca_tree, write_profile):
    """A two-element vector must survive a one-element engine default.

    The engine default for retraction_length has a single element. If the merge
    treated it as a parent, the first chain link's two-element vector would be
    collapsed to one — silently losing the second extruder.
    """
    bundle = orca_tree["resources"] / "profiles"
    write_profile(
        bundle / "Acme/machine/Acme Root Dual.json",
        {
            "type": "machine",
            "name": "Acme Root Dual",
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "0.9"],
        },
    )
    vendor_file = bundle / "Acme.json"
    data = json.loads(vendor_file.read_text(encoding="utf-8"))
    data["machine_list"].append(
        {"name": "Acme Root Dual", "sub_path": "machine/Acme Root Dual.json"}
    )
    write_profile(vendor_file, data)

    resolver = Resolver(ProfileIndex.build(discover()), EngineSnapshot.load())
    resolved = resolver.resolve("machine", "Acme Root Dual")
    assert resolved.values["retraction_length"].value == ["0.8", "0.9"]
