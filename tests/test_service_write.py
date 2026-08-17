import pytest

from orca_profiles_mcp.service import build_service


@pytest.fixture
def service(orca_tree):
    return build_service()


def test_set_values_reports_written_keys(service):
    report = service.set_values("process", "My Fast", {"top_shell_layers": "6"})
    assert "top_shell_layers" in report["written_keys"]
    assert report["backup"] is not None
    assert report["orca_running_warning"]


def test_set_values_is_visible_to_reader_immediately(service):
    service.set_values("process", "My Fast", {"top_shell_layers": "6"})
    result = service.get_profile("process", "My Fast")
    assert result["values"]["top_shell_layers"] == "6"


def test_set_values_rejects_unknown_key(service):
    with pytest.raises(ValueError):
        service.set_values("process", "My Fast", {"no_such_setting": "1"})


def test_set_values_warns_when_editing_shared_profile(service):
    report = service.set_values(
        "process", "0.20mm Standard @Acme", {"top_shell_layers": "6"}
    )
    assert any("bundle" in w for w in report["warnings"])
    assert any("inherit from it" in w for w in report["warnings"])


def test_create_profile_then_read_it(service):
    service.create_profile(
        "process", "Fresh", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    chain = service.get_chain("process", "Fresh")
    assert [link["name"] for link in chain["chain"]] == [
        "Fresh",
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]


def test_rename_profile_updates_index(service):
    service.create_profile(
        "process", "Old Name", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    service.rename_profile("process", "Old Name", "New Name")
    assert service.get_profile("process", "New Name")["name"] == "New Name"
    with pytest.raises(KeyError):
        service.get_profile("process", "Old Name")


def test_delete_profile_removes_from_index(service):
    service.create_profile(
        "process", "Doomed", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    service.delete_profile("process", "Doomed")
    with pytest.raises(KeyError):
        service.get_profile("process", "Doomed")


def test_normalize_profile_reports_removed_keys(service):
    service.set_values("process", "My Fast", {"outer_wall_speed": ["120"]})
    report = service.normalize_profile("process", "My Fast")
    assert isinstance(report["removed_keys"], list)
