import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover


@pytest.fixture
def resolver(orca_tree):
    return Resolver(ProfileIndex.build(discover()), EngineSnapshot.load())


def test_chain_goes_from_profile_to_root(resolver):
    resolved = resolver.resolve("process", "My Fast")
    assert [link.name for link in resolved.chain] == [
        "My Fast",
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]


def test_chain_marks_abstract_links(resolver):
    resolved = resolver.resolve("process", "My Fast")
    by_name = {link.name: link for link in resolved.chain}
    assert by_name["fdm_process_common"].instantiation is False
    assert by_name["0.20mm Standard @Acme"].instantiation is True


def test_child_value_wins_and_records_overridden(resolver):
    resolved = resolver.resolve("process", "My Fast")
    speed = resolved.values["outer_wall_speed"]
    assert speed.value == ["180"]
    assert speed.origin == "My Fast"
    assert [(o.link, o.value) for o in speed.overridden] == [
        ("0.20mm Standard @Acme", ["120"]),
        ("fdm_process_common", ["200"]),
    ]


def test_value_inherited_from_root_keeps_origin(resolver):
    resolved = resolver.resolve("process", "My Fast")
    assert resolved.values["layer_height"].value == "0.2"
    assert resolved.values["layer_height"].origin == "fdm_process_common"
    assert resolved.values["layer_height"].overridden == []


def test_engine_defaults_fill_unset_keys(resolver):
    resolved = resolver.resolve("process", "My Fast")
    # a key set by no link in the chain
    assert "top_shell_layers" in resolved.values
    assert resolved.values["top_shell_layers"].is_default is True


def test_meta_keys_are_not_values(resolver):
    resolved = resolver.resolve("process", "My Fast")
    for key in ("name", "from", "inherits", "version", "print_settings_id"):
        assert key not in resolved.values


def test_cross_vendor_inheritance_resolves(resolver):
    resolved = resolver.resolve("filament", "Acme PLA")
    assert [link.name for link in resolved.chain] == [
        "Acme PLA",
        "Generic PLA @System",
        "fdm_filament_pla",
        "fdm_filament_common",
    ]
    assert resolved.values["filament_flow_ratio"].origin == "fdm_filament_pla"


def test_missing_parent_is_reported_not_raised(resolver):
    resolved = resolver.resolve("process", "Broken")
    assert [link.name for link in resolved.chain] == ["Broken"]
    errors = [d for d in resolved.diagnostics if d.severity == "error"]
    assert errors and errors[0].code == "missing_parent"
    # the profile's own values are still available
    assert resolved.values["top_shell_layers"].value == "9"
