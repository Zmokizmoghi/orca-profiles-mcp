"""Regressions for the second review's remaining findings."""

import json

import pytest

from orca_profiles_mcp.delta_check import check_profile_delta
from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.validate import validate_library
from orca_profiles_mcp.writer import Writer


def build():
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return index, Resolver(index, snapshot), snapshot


@pytest.fixture
def writer(orca_tree):
    index, resolver, snapshot = build()
    return Writer(index, resolver, snapshot)


# --- the index must not serve deleted or shadowed entries wrongly ---


def test_deleting_a_winner_exposes_the_shadowed_profile(orca_tree, write_profile):
    """A lower-priority same-named profile takes over, as it would after a restart."""
    system = orca_tree["datadir"] / "system"
    write_profile(
        system / "Acme.json",
        {
            "name": "Acme",
            "process_list": [
                {"name": "Shared Name", "sub_path": "process/Shared Name.json"}
            ],
        },
    )
    write_profile(
        system / "Acme/process/Shared Name.json",
        {
            "type": "process",
            "name": "Shared Name",
            "from": "system",
            "instantiation": "true",
            "layer_height": "0.1",
        },
    )
    bundle = orca_tree["resources"] / "profiles"
    vendor = json.loads((bundle / "Acme.json").read_text(encoding="utf-8"))
    vendor["process_list"].append(
        {"name": "Shared Name", "sub_path": "process/Shared Name.json"}
    )
    write_profile(bundle / "Acme.json", vendor)
    write_profile(
        bundle / "Acme/process/Shared Name.json",
        {
            "type": "process",
            "name": "Shared Name",
            "from": "system",
            "instantiation": "true",
            "layer_height": "0.9",
        },
    )

    index, _, _ = build()
    assert index.get("process", "Shared Name").source == "datadir-system"

    index.remove_profile("process", "Shared Name")
    survivor = index.get("process", "Shared Name")
    assert survivor is not None, "the bundle copy should take over"
    assert survivor.source == "bundle"


def test_removed_profile_disappears_from_collisions(orca_tree, write_profile):
    system = orca_tree["datadir"] / "system"
    write_profile(
        system / "Dup.json",
        {
            "name": "Dup",
            "process_list": [
                {"name": "0.20mm Standard @Acme", "sub_path": "process/copy.json"}
            ],
        },
    )
    write_profile(
        system / "Dup/process/copy.json",
        {
            "type": "process",
            "name": "0.20mm Standard @Acme",
            "from": "system",
            "instantiation": "true",
            "layer_height": "0.2",
        },
    )
    index, _, _ = build()
    assert any(name == "0.20mm Standard @Acme" for _, name, _ in index.collisions())

    index.remove_profile("process", "0.20mm Standard @Acme")
    assert not any(
        name == "0.20mm Standard @Acme" for _, name, _ in index.collisions()
    )


# --- unreadable files must be visible, not silently empty ---


def test_unreadable_profile_is_reported(orca_tree, write_profile):
    broken = orca_tree["user_dir"] / "process/Corrupt.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{ not json at all", encoding="utf-8")

    index, resolver, snapshot = build()
    results = validate_library(index, resolver, snapshot, scope="user")
    assert any(d.code == "unreadable_file" for d in results)


# --- rename and delete must not leave dangling references ---


def test_rename_updates_children_that_point_at_the_old_name(writer, orca_tree, write_profile):
    writer.create_profile(
        "process", "Base One", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    write_profile(
        orca_tree["user_dir"] / "process/Derived.json",
        {
            "name": "Derived",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Base One",
            "top_shell_layers": "4",
        },
    )
    index, resolver, snapshot = build()
    writer2 = Writer(index, resolver, snapshot)
    report = writer2.rename_profile("process", "Base One", "Base Renamed")

    child = json.loads(
        (orca_tree["user_dir"] / "process/Derived.json").read_text(encoding="utf-8")
    )
    assert child["inherits"] == "Base Renamed"
    assert "Derived" in report["updated_children"]

    index2, resolver2, _ = build()
    assert [l.name for l in resolver2.resolve("process", "Derived").chain][:2] == [
        "Derived",
        "Base Renamed",
    ]


def test_deleting_a_system_profile_needs_an_explicit_opt_in(writer):
    with pytest.raises(ValueError, match="force"):
        writer.delete_profile("process", "0.20mm Standard @Acme")

    report = writer.delete_profile("process", "0.20mm Standard @Acme", force=True)
    assert report["warnings"]


def test_editing_a_system_profile_needs_an_explicit_opt_in(writer):
    with pytest.raises(ValueError, match="force"):
        writer.set_values("process", "0.20mm Standard @Acme", {"top_shell_layers": "6"})

    report = writer.set_values(
        "process", "0.20mm Standard @Acme", {"top_shell_layers": "6"}, force=True
    )
    assert report["warnings"]


# --- a profile the engine would skip must say so ---


def test_profile_with_a_missing_parent_is_marked_unusable(orca_tree):
    _, resolver, _ = build()
    resolved = resolver.resolve("process", "Broken")
    assert resolved.usable is False
    assert any(d.code == "missing_parent" for d in resolved.diagnostics)


def test_a_healthy_profile_is_usable(orca_tree):
    _, resolver, _ = build()
    assert resolver.resolve("process", "My Fast").usable is True


# --- per-element provenance for variant vectors ---


def test_vector_provenance_is_recorded_per_element(orca_tree, write_profile):
    bundle = orca_tree["resources"] / "profiles"
    write_profile(
        bundle / "Acme/machine/Acme Duo.json",
        {
            "type": "machine",
            "name": "Acme Duo",
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "0.9"],
        },
    )
    vendor = json.loads((bundle / "Acme.json").read_text(encoding="utf-8"))
    vendor["machine_list"].append(
        {"name": "Acme Duo", "sub_path": "machine/Acme Duo.json"}
    )
    write_profile(bundle / "Acme.json", vendor)
    write_profile(
        orca_tree["user_dir"] / "machine/Duo Tuned.json",
        {
            "name": "Duo Tuned",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Duo",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "1.5"],
        },
    )
    _, resolver, _ = build()
    value = resolver.resolve("machine", "Duo Tuned").values["retraction_length"]
    assert value.value == ["0.8", "1.5"]
    # only the second extruder was actually changed by the child
    assert value.element_origins == ["Acme Duo", "Duo Tuned"]


# --- diff must not hide a different parent ---


def test_raw_diff_shows_a_differing_parent(orca_tree, write_profile):
    from orca_profiles_mcp.service import build_service

    write_profile(
        orca_tree["user_dir"] / "process/Same Body A.json",
        {
            "name": "Same Body A",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "top_shell_layers": "4",
        },
    )
    write_profile(
        orca_tree["user_dir"] / "process/Same Body B.json",
        {
            "name": "Same Body B",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.30mm Draft @Acme",
            "top_shell_layers": "4",
        },
    )
    service = build_service()
    result = service.diff_profiles("process", "Same Body A", "Same Body B", mode="raw")
    assert "inherits" in result["differences"]


# --- public tools must not crash on odd but legal input ---


def test_unknown_mode_is_rejected(orca_tree):
    from orca_profiles_mcp.service import build_service

    with pytest.raises(ValueError, match="mode"):
        build_service().get_profile("process", "My Fast", mode="whatever")


def test_compare_with_upstream_rejects_machine_model(orca_tree):
    from orca_profiles_mcp.service import build_service

    with pytest.raises(ValueError):
        build_service().compare_with_upstream("machine_model", "Acme One")
