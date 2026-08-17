import json

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.variants import split_with_nil
from orca_profiles_mcp.writer import Writer


def register_dual(orca_tree, write_profile, base_name: str) -> None:
    """Add a two-variant machine profile to the bundle vendor."""
    bundle = orca_tree["resources"] / "profiles"
    write_profile(
        bundle / f"Acme/machine/{base_name}.json",
        {
            "type": "machine",
            "name": base_name,
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "0.9"],
        },
    )
    vendor_file = bundle / "Acme.json"
    data = json.loads(vendor_file.read_text(encoding="utf-8"))
    data["machine_list"].append(
        {"name": base_name, "sub_path": f"machine/{base_name}.json"}
    )
    write_profile(vendor_file, data)


def test_split_with_nil_marks_matching_elements():
    assert split_with_nil(["0.8", "0.9"], ["0.8", "1.5"], stride=1) == ["nil", "1.5"]


def test_split_with_nil_keeps_pairs_together_for_stride_two():
    parent = ["1000", "500", "2000", "800"]
    child = ["1000", "500", "3000", "900"]
    assert split_with_nil(parent, child, stride=2) == ["nil", "nil", "3000", "900"]


def test_split_with_nil_returns_child_on_length_mismatch():
    assert split_with_nil(["0.8"], ["1.5", "1.6"], stride=1) == ["1.5", "1.6"]


def test_writer_stores_nil_for_unchanged_variant_elements(orca_tree, write_profile):
    register_dual(orca_tree, write_profile, "Acme Dual")
    write_profile(
        orca_tree["user_dir"] / "machine/Dual Tuned.json",
        {
            "name": "Dual Tuned",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Dual",
            "printer_extruder_variant": ["0.4", "0.6"],
        },
    )

    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    writer = Writer(index, Resolver(index, snapshot), snapshot)
    writer.set_values("machine", "Dual Tuned", {"retraction_length": ["0.8", "1.5"]})

    saved = json.loads((orca_tree["user_dir"] / "machine/Dual Tuned.json").read_text())
    assert saved["retraction_length"] == ["nil", "1.5"]


def test_resolver_expands_nil_from_parent(orca_tree, write_profile):
    register_dual(orca_tree, write_profile, "Acme Nil Base")
    write_profile(
        orca_tree["user_dir"] / "machine/Nil Child.json",
        {
            "name": "Nil Child",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Nil Base",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["nil", "1.5"],
        },
    )

    index = ProfileIndex.build(discover())
    resolved = Resolver(index, EngineSnapshot.load()).resolve("machine", "Nil Child")
    assert resolved.values["retraction_length"].value == ["0.8", "1.5"]
