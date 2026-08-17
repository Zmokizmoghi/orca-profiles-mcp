from orca_profiles_mcp.sources import discover


def test_discover_reads_roots_from_env(orca_tree):
    setup = discover()
    assert setup.datadir == orca_tree["datadir"]
    assert setup.resources == orca_tree["resources"]


def test_datadir_system_has_priority_over_bundle(orca_tree):
    setup = discover()
    sources = [root.source for root in setup.vendor_roots]
    assert sources.index("datadir-system") < sources.index("bundle")


def test_discover_finds_user_directory(orca_tree):
    setup = discover()
    assert setup.user_id == "uid-1"
    assert setup.user_dir == orca_tree["user_dir"]


def test_discover_reads_app_version_and_selection(orca_tree):
    setup = discover()
    assert setup.app_version == "2.4.2"
    assert setup.selected["machine"] == "ACME ONE 0.4 nozzle"


def test_discover_tolerates_missing_resources(orca_tree, monkeypatch):
    monkeypatch.setenv("ORCA_RESOURCES", str(orca_tree["datadir"] / "nope"))
    setup = discover()
    assert [root.source for root in setup.vendor_roots] == ["datadir-system"]
