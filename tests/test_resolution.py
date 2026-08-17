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
