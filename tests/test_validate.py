import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.validate import validate_library


def build_parts():
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return index, Resolver(index, snapshot), snapshot


@pytest.fixture
def parts(orca_tree):
    return build_parts()


def test_validate_reports_missing_parent(parts):
    index, resolver, snapshot = parts
    codes = {d.code for d in validate_library(index, resolver, snapshot, scope="user")}
    assert "missing_parent" in codes


def test_validate_reports_unknown_key(orca_tree, write_profile):
    write_profile(
        orca_tree["user_dir"] / "process/Weird.json",
        {
            "name": "Weird",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "totally_made_up_key": "1",
        },
    )
    index, resolver, snapshot = build_parts()
    results = validate_library(index, resolver, snapshot, scope="user")
    assert any(
        d.code == "unknown_key" and d.key == "totally_made_up_key" for d in results
    )


def test_validate_reports_redundant_delta(orca_tree, write_profile):
    write_profile(
        orca_tree["user_dir"] / "process/Redundant.json",
        {
            "name": "Redundant",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "layer_height": "0.2",  # exactly the parent's value
        },
    )
    index, resolver, snapshot = build_parts()
    results = validate_library(index, resolver, snapshot, scope="user")
    assert any(d.code == "redundant_delta" and d.key == "layer_height" for d in results)


def test_validate_scope_all_covers_system_profiles(parts):
    index, resolver, snapshot = parts
    everything = validate_library(index, resolver, snapshot, scope="all")
    user_only = validate_library(index, resolver, snapshot, scope="user")
    assert len(everything) >= len(user_only)
