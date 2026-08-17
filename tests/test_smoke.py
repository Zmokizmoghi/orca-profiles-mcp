"""Checks against the real, installed profile library.

These run without OrcaSlicer being launched; they only read its files. They are
skipped when no Orca data directory is present.
"""

from pathlib import Path

import pytest

from orca_profiles_mcp.service import build_service

REAL_DATADIR = Path.home() / "Library/Application Support/OrcaSlicer"


@pytest.fixture
def real_service(monkeypatch):
    if not REAL_DATADIR.exists():
        pytest.skip("no OrcaSlicer data directory")
    monkeypatch.delenv("ORCA_DATADIR", raising=False)
    monkeypatch.delenv("ORCA_RESOURCES", raising=False)
    return build_service()


def test_setup_sees_installed_library(real_service):
    counts = real_service.get_setup()["counts"]
    assert counts["process"] > 100
    assert counts["filament"] > 100


def test_every_user_profile_resolves(real_service):
    """No user profile may blow up during expansion."""
    failures = []
    for profile in real_service.list_profiles(source="user", limit=10_000)["profiles"]:
        try:
            real_service.get_profile(profile["type"], profile["name"])
        except Exception as err:  # noqa: BLE001 — the failure itself is the finding
            failures.append(f"{profile['type']}/{profile['name']}: {err}")
    assert failures == []


def test_resolver_matches_the_deltas_orca_wrote(real_service):
    """The strongest correctness signal available: Orca's own recorded answers.

    Redundant keys are ignored — they mean the file predates a parent change,
    not that the resolver is wrong.
    """
    report = real_service.check_deltas(scope="user")
    assert report["checked"] > 0
    assert report["mismatched"] == 0, [
        {
            "profile": d["name"],
            "differing": d["differing_values"],
            "we_would_add": d["we_would_add"],
        }
        for d in report["details"]
    ]


def test_validate_user_scope_runs(real_service):
    assert "diagnostics" in real_service.validate(scope="user")
