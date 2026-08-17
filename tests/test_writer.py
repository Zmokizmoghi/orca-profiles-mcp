import json

import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.writer import Writer, detect_indent, read_info, write_info


@pytest.fixture
def writer(orca_tree):
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return Writer(index, Resolver(index, snapshot), snapshot)


def test_detect_indent_reads_existing_style(orca_tree):
    assert detect_indent(orca_tree["user_dir"] / "process/My Fast.json") == "    "


def test_set_values_writes_only_delta(writer, orca_tree):
    writer.set_values("process", "My Fast", {"top_shell_layers": "6"})
    data = json.loads((orca_tree["user_dir"] / "process/My Fast.json").read_text())
    assert data["top_shell_layers"] == "6"
    # values equal to the parent's are not stored
    assert "layer_height" not in data
    assert data["inherits"] == "0.20mm Standard @Acme"


def test_set_values_drops_key_equal_to_parent(writer, orca_tree):
    # the parent sets outer_wall_speed = ["120"], the profile ["180"]
    writer.set_values("process", "My Fast", {"outer_wall_speed": ["120"]})
    data = json.loads((orca_tree["user_dir"] / "process/My Fast.json").read_text())
    assert "outer_wall_speed" not in data


def test_set_values_keeps_alphabetical_order_and_trailing_newline(writer, orca_tree):
    writer.set_values("process", "My Fast", {"top_shell_layers": "6"})
    raw = (orca_tree["user_dir"] / "process/My Fast.json").read_text()
    keys = list(json.loads(raw).keys())
    assert keys == sorted(keys)
    assert raw.endswith("\n")


def test_set_values_makes_backup(writer, orca_tree):
    report = writer.set_values("process", "My Fast", {"top_shell_layers": "6"})
    assert report["backup"] is not None
    assert list((orca_tree["user_dir"] / "process").glob("My Fast.json.bak-*"))


def test_set_values_updates_info_timestamp(writer, orca_tree):
    info_path = orca_tree["user_dir"] / "process/My Fast.info"
    before = read_info(info_path)["updated_time"]
    writer.set_values("process", "My Fast", {"top_shell_layers": "6"})
    assert int(read_info(info_path)["updated_time"]) > int(before)


def test_round_trip_without_changes_keeps_file_identical(writer, orca_tree):
    path = orca_tree["user_dir"] / "process/My Fast.json"
    before = path.read_text()
    writer.set_values("process", "My Fast", {}, backup=False)
    assert path.read_text() == before


def test_set_values_rejects_unknown_key(writer):
    with pytest.raises(ValueError):
        writer.set_values("process", "My Fast", {"no_such_setting": "1"})


def test_create_profile_requires_existing_parent(writer):
    with pytest.raises(KeyError):
        writer.create_profile("process", "New One", "No Such", {"layer_height": "0.1"})


def test_create_profile_writes_file_and_info(writer, orca_tree):
    report = writer.create_profile(
        "process", "New One", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    path = orca_tree["user_dir"] / "process/New One.json"
    data = json.loads(path.read_text())
    assert data["inherits"] == "0.20mm Standard @Acme"
    assert data["from"] == "User"
    assert data["layer_height"] == "0.1"
    assert (orca_tree["user_dir"] / "process/New One.info").exists()
    assert report["file"] == str(path)


def test_delete_profile_removes_both_files(writer, orca_tree):
    writer.create_profile(
        "process", "Temp", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    writer.delete_profile("process", "Temp")
    assert not (orca_tree["user_dir"] / "process/Temp.json").exists()
    assert not (orca_tree["user_dir"] / "process/Temp.info").exists()


def test_delete_keeps_info_for_cloud_synced_profile(writer, orca_tree):
    writer.create_profile(
        "process", "Synced", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    info_path = orca_tree["user_dir"] / "process/Synced.info"
    info = read_info(info_path)
    info["setting_id"] = "cloud-123"
    write_info(info_path, info)

    writer.delete_profile("process", "Synced")
    assert not (orca_tree["user_dir"] / "process/Synced.json").exists()
    assert read_info(info_path)["sync_info"] == "delete"


def test_rename_profile_moves_files(writer, orca_tree):
    writer.create_profile(
        "process", "Old", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    writer.rename_profile("process", "Old", "New")
    assert not (orca_tree["user_dir"] / "process/Old.json").exists()
    data = json.loads((orca_tree["user_dir"] / "process/New.json").read_text())
    assert data["name"] == "New"
    assert data["print_settings_id"] == "New"


def test_normalize_removes_redundant_keys(writer, orca_tree):
    path = orca_tree["user_dir"] / "process/My Fast.json"
    data = json.loads(path.read_text())
    data["layer_height"] = "0.2"  # identical to the parent
    path.write_text(json.dumps(data, indent=4, sort_keys=True) + "\n")

    report = writer.normalize_profile("process", "My Fast")
    assert "layer_height" in report["removed_keys"]
    assert "layer_height" not in json.loads(path.read_text())
