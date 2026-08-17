import pytest

from orca_profiles_mcp.delta_check import check_library_deltas, check_profile_delta
from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover


def build_parts():
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return index, Resolver(index, snapshot), snapshot


@pytest.fixture
def parts(orca_tree):
    return build_parts()


def test_delta_of_a_well_formed_profile_is_consistent(parts):
    index, resolver, snapshot = parts
    result = check_profile_delta(index, resolver, snapshot, "process", "My Fast")
    assert result["checked"] is True
    assert result["consistent"] is True
    assert result["redundant_in_file"] == []


def test_root_profile_is_skipped(parts):
    index, resolver, snapshot = parts
    result = check_profile_delta(
        index, resolver, snapshot, "process", "fdm_process_common"
    )
    assert result["checked"] is False


def test_key_equal_to_parent_is_reported_as_redundant(orca_tree, write_profile):
    write_profile(
        orca_tree["user_dir"] / "process/Redundant.json",
        {
            "name": "Redundant",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "layer_height": "0.2",  # the parent already says 0.2
            "top_shell_layers": "7",
        },
    )
    index, resolver, snapshot = build_parts()
    result = check_profile_delta(index, resolver, snapshot, "process", "Redundant")
    assert result["redundant_in_file"] == ["layer_height"]
    # a redundant key is not a resolver mismatch
    assert result["consistent"] is True
    assert result["redundant_only"] is True


def test_child_with_more_extruders_keeps_both_values(orca_tree, write_profile):
    """A single-extruder parent must not shrink a toolchanger child's vector."""
    import json

    bundle = orca_tree["resources"] / "profiles"
    write_profile(
        bundle / "Acme/machine/Acme Single.json",
        {
            "type": "machine",
            "name": "Acme Single",
            "from": "system",
            "instantiation": "true",
            "nozzle_diameter": ["0.4"],
            "retraction_length": ["0.5"],
        },
    )
    vendor_file = bundle / "Acme.json"
    data = json.loads(vendor_file.read_text(encoding="utf-8"))
    data["machine_list"].append(
        {"name": "Acme Single", "sub_path": "machine/Acme Single.json"}
    )
    write_profile(vendor_file, data)

    write_profile(
        orca_tree["user_dir"] / "machine/Acme Toolchanger.json",
        {
            "name": "Acme Toolchanger",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Single",
            "nozzle_diameter": ["0.4", "0.4"],
            "retraction_length": ["0.5", "0.5"],
        },
    )

    index, resolver, snapshot = build_parts()
    resolved = resolver.resolve("machine", "Acme Toolchanger")
    assert resolved.values["retraction_length"].value == ["0.5", "0.5"]

    result = check_profile_delta(index, resolver, snapshot, "machine", "Acme Toolchanger")
    assert result["consistent"] is True
    assert "retraction_length" not in result["redundant_in_file"]


def test_library_report_counts_scopes(parts):
    index, resolver, snapshot = parts
    report = check_library_deltas(index, resolver, snapshot, scope="user")
    assert report["checked"] >= 1
    assert report["mismatched"] == 0
