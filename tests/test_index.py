from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.sources import discover


def test_index_finds_bundle_profile(orca_tree):
    index = ProfileIndex.build(discover())
    entry = index.get("process", "0.20mm Standard @Acme")
    assert entry is not None
    assert entry.vendor == "Acme"
    assert entry.source == "bundle"
    assert entry.file.exists()


def test_index_finds_user_profile_without_type_field(orca_tree):
    index = ProfileIndex.build(discover())
    entry = index.get("process", "My Fast")
    assert entry is not None
    assert entry.source == "user"


def test_index_keeps_case_sensitive_names_apart(orca_tree):
    index = ProfileIndex.build(discover())
    assert index.get("machine", "ACME ONE 0.4 nozzle").source == "datadir-system"
    assert index.get("machine", "Acme One 0.4 nozzle").source == "bundle"


def test_index_loads_raw_profile(orca_tree):
    index = ProfileIndex.build(discover())
    raw = index.load_raw(index.get("process", "0.20mm Standard @Acme"))
    assert raw["outer_wall_speed"] == ["120"]


def test_index_lists_children(orca_tree):
    index = ProfileIndex.build(discover())
    children = index.children_of("process", "0.20mm Standard @Acme")
    assert [c.name for c in children] == ["My Fast"]


def test_index_maps_renamed_profiles(orca_tree):
    index = ProfileIndex.build(discover())
    entry = index.renamed("process", "0.30mm Rough @Acme")
    assert entry is not None and entry.name == "0.30mm Draft @Acme"


def test_index_lists_all_of_type(orca_tree):
    index = ProfileIndex.build(discover())
    names = {e.name for e in index.all("filament")}
    assert {"Acme PLA", "Generic PLA @System", "fdm_filament_pla"} <= names
