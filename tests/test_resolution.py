import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover


@pytest.fixture
def resolver(orca_tree):
    return Resolver(ProfileIndex.build(discover()), EngineSnapshot.load())


def test_renamed_from_resolves_old_parent_name(resolver):
    resolved = resolver.resolve("process", "Uses Old Name")
    assert [link.name for link in resolved.chain] == [
        "Uses Old Name",
        "0.30mm Draft @Acme",
        "fdm_process_common",
    ]
    assert resolved.chain[1].resolution == "renamed_from"
    assert resolved.values["layer_height"].value == "0.3"


def test_renamed_resolution_is_reported(resolver):
    resolved = resolver.resolve("process", "Uses Old Name")
    assert "renamed_from" in {d.code for d in resolved.diagnostics}


def test_generic_fallback_maps_to_system_library(resolver):
    resolved = resolver.resolve("filament", "My PLA")
    assert [link.name for link in resolved.chain] == [
        "My PLA",
        "Generic PLA @System",
        "fdm_filament_pla",
        "fdm_filament_common",
    ]
    assert resolved.chain[1].resolution == "generic_fallback"


def test_generic_fallback_is_reported(resolver):
    resolved = resolver.resolve("filament", "My PLA")
    assert "generic_fallback" in {d.code for d in resolved.diagnostics}


def test_parent_is_resolved_within_the_same_vendor_first(orca_tree, write_profile):
    """Base profiles share names across vendors; a profile must get its own.

    fdm_machine_common exists in 64 of the bundled vendors, so a global lookup
    would hand a Sovol printer Creality's base profile.
    """
    bundle = orca_tree["resources"] / "profiles"
    # a second vendor shipping a same-named base profile with different values
    write_profile(
        bundle / "Other.json",
        {
            "name": "Other",
            "machine_list": [
                {
                    "name": "fdm_machine_common",
                    "sub_path": "machine/fdm_machine_common.json",
                },
                {"name": "Other Printer", "sub_path": "machine/Other Printer.json"},
            ],
        },
    )
    write_profile(
        bundle / "Other/machine/fdm_machine_common.json",
        {
            "type": "machine",
            "name": "fdm_machine_common",
            "from": "system",
            "instantiation": "false",
            "retraction_length": ["9.9"],
        },
    )
    write_profile(
        bundle / "Other/machine/Other Printer.json",
        {
            "type": "machine",
            "name": "Other Printer",
            "from": "system",
            "instantiation": "true",
            "inherits": "fdm_machine_common",
            "nozzle_diameter": ["0.4"],
        },
    )

    index = ProfileIndex.build(discover())
    resolver = Resolver(index, EngineSnapshot.load())

    other = resolver.resolve("machine", "Other Printer")
    assert other.chain[1].vendor == "Other"
    assert other.values["retraction_length"].value == ["9.9"]

    acme = resolver.resolve("machine", "Acme One 0.4 nozzle")
    assert acme.chain[1].vendor == "Acme"
    assert acme.values["retraction_length"].value == ["0.8"]
