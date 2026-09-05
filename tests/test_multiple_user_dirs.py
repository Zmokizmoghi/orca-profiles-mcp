"""Orca keeps one profile tree per account, plus `default` when signed out.

Picking the wrong one is silent and expensive: profiles get written where the
running Orca never looks. This came from a real session where created profiles
had to be copied into the other tree by hand.
"""

import json

import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.service import build_service
from orca_profiles_mcp.sources import discover


def seed(tree, dirname: str, profile: str, mtime: float | None = None):
    """Add a user tree with one process profile."""
    d = tree["datadir"] / "user" / dirname / "process"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{profile}.json"
    path.write_text(
        json.dumps(
            {
                "name": profile,
                "from": "User",
                "version": "1.9.0.2",
                "inherits": "0.20mm Standard @Acme",
                "top_shell_layers": "4",
            }
        ),
        encoding="utf-8",
    )
    if mtime:
        import os

        os.utime(path, (mtime, mtime))
    return path


def test_default_tree_is_a_candidate(orca_tree):
    """Orca uses user/default when nobody is signed in — it cannot be skipped."""
    seed(orca_tree, "default", "Only In Default", mtime=2_000_000_000)
    setup = discover()
    names = [d.name for d in setup.user_dirs]
    assert "default" in names


def test_every_user_tree_is_reported(orca_tree):
    seed(orca_tree, "default", "Only In Default", mtime=1_000_000_000)
    setup = discover()
    assert len(setup.user_dirs) >= 2, "both trees must be visible to the caller"


def test_the_freshest_tree_wins_by_content(orca_tree):
    seed(orca_tree, "default", "Fresh One", mtime=2_100_000_000)
    setup = discover()
    assert setup.user_dir.name == "default"
    assert ProfileIndex.build(setup).get("process", "Fresh One") is not None


def test_an_explicit_choice_overrides_the_guess(orca_tree, monkeypatch):
    seed(orca_tree, "default", "Fresh One", mtime=2_100_000_000)
    monkeypatch.setenv("ORCA_USER_DIR", str(orca_tree["user_dir"]))
    setup = discover()
    assert setup.user_dir == orca_tree["user_dir"]


def test_setup_warns_when_several_trees_exist(orca_tree):
    seed(orca_tree, "default", "Only In Default", mtime=1_000_000_000)
    result = build_service().get_setup()
    assert len(result["user_dirs"]) >= 2
    assert result["user_dir_warning"], "the ambiguity must be stated, not hidden"


def test_writes_warn_when_the_tree_is_ambiguous(orca_tree):
    seed(orca_tree, "default", "Only In Default", mtime=1_000_000_000)
    service = build_service()
    report = service.create_profile(
        "process", "Written Somewhere", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    assert any("user profile director" in w for w in report["warnings"])
