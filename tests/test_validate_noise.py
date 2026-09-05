"""Regressions for validate's false positives and unbounded output."""

import json

import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.service import build_service
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.validate import validate_library


def build():
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return index, Resolver(index, snapshot), snapshot


def test_filament_override_keys_are_known(orca_tree):
    """They live in the filament option list but have no engine default."""
    snapshot = EngineSnapshot.load()
    for key in ("filament_retraction_length", "filament_wipe", "filament_z_hop"):
        assert snapshot.is_known_key(key), key


def test_no_unknown_key_warning_for_a_filament_override(orca_tree, write_profile):
    write_profile(
        orca_tree["user_dir"] / "filament/Override User.json",
        {
            "name": "Override User",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Generic PLA @System",
            "filament_retraction_length": ["1.2"],
        },
    )
    index, resolver, snapshot = build()
    results = validate_library(index, resolver, snapshot, scope="user")
    assert not [d for d in results if d.code == "unknown_key"]


def test_hidden_backup_directories_are_not_indexed(orca_tree, write_profile):
    """Orca keeps sync backups in dot-directories; they are not live profiles."""
    write_profile(
        orca_tree["user_dir"] / "filament/.sync_bak/My PLA.json",
        {
            "name": "My PLA",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Generic PLA @System",
            "filament_flow_ratio": ["0.5"],
        },
    )
    index, _, _ = build()
    assert not any(
        ".sync_bak" in str(e.file) for e in index.all("filament")
    ), "a backup copy was indexed as a real profile"
    assert not [c for c in index.collisions() if c[1] == "My PLA"]


def test_validate_summarises_and_caps_its_output(orca_tree):
    service = build_service()
    result = service.validate(scope="user", limit=5)
    assert result["by_code"], "a per-code summary makes a long list actionable"
    assert result["by_severity"]
    assert len(result["diagnostics"]) <= 5
    assert result["returned"] <= result["count"]


def test_validate_can_filter_by_code(orca_tree, write_profile):
    write_profile(
        orca_tree["user_dir"] / "process/Redundant.json",
        {
            "name": "Redundant",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "layer_height": "0.2",
        },
    )
    result = build_service().validate(scope="user", code="redundant_delta")
    assert result["diagnostics"]
    assert {d["code"] for d in result["diagnostics"]} == {"redundant_delta"}
