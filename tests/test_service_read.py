import pytest

from orca_profiles_mcp.service import build_service


@pytest.fixture
def service(orca_tree):
    return build_service()


def test_get_setup_reports_roots_and_version(service):
    setup = service.get_setup()
    assert setup["app_version"] == "2.4.2"
    assert "datadir-system" in [r["source"] for r in setup["vendor_roots"]]
    assert setup["counts"]["process"] >= 3


def test_list_profiles_hides_abstract_by_default(service):
    names = [p["name"] for p in service.list_profiles(type="process")["profiles"]]
    assert "0.20mm Standard @Acme" in names
    assert "fdm_process_common" not in names


def test_list_profiles_can_include_abstract(service):
    names = [
        p["name"]
        for p in service.list_profiles(type="process", include_abstract=True)["profiles"]
    ]
    assert "fdm_process_common" in names


def test_list_profiles_filters_by_query(service):
    result = service.list_profiles(type="process", query="fast")
    assert [p["name"] for p in result["profiles"]] == ["My Fast"]


def test_get_profile_omits_engine_defaults_by_default(service):
    result = service.get_profile("process", "My Fast")
    assert "outer_wall_speed" in result["values"]
    assert "top_shell_layers" not in result["values"]
    assert result["omitted_defaults"] > 0


def test_get_profile_traced_mode_shows_origin(service):
    result = service.get_profile("process", "My Fast", mode="traced")
    entry = result["values"]["outer_wall_speed"]
    assert entry["origin"] == "My Fast"
    assert entry["overridden"][0]["link"] == "0.20mm Standard @Acme"


def test_get_profile_raw_mode_returns_file_contents(service):
    result = service.get_profile("process", "My Fast", mode="raw")
    assert result["values"]["inherits"] == "0.20mm Standard @Acme"


def test_get_profile_filters_by_key_substring(service):
    result = service.get_profile("process", "My Fast", keys="wall")
    assert result["values"]
    assert all("wall" in key for key in result["values"])


def test_get_chain_lists_links_with_sources(service):
    chain = service.get_chain("process", "My Fast")
    assert [link["name"] for link in chain["chain"]] == [
        "My Fast",
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]
    assert chain["chain"][1]["source"] == "bundle"


def test_explain_key_reports_full_history(service):
    result = service.explain_key("process", "My Fast", "outer_wall_speed")
    assert result["value"] == ["180"]
    assert result["origin"] == "My Fast"
    assert [o["link"] for o in result["overridden"]] == [
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]
    assert result["engine_default"] is not None


def test_find_children_lists_dependents(service):
    result = service.find_children("process", "0.20mm Standard @Acme")
    assert "My Fast" in [c["name"] for c in result["children"]]


def test_diff_profiles_reports_differing_keys(service):
    result = service.diff_profiles("process", "My Fast", "0.20mm Standard @Acme")
    assert result["differences"]["outer_wall_speed"]["a"] == ["180"]
    assert result["differences"]["outer_wall_speed"]["b"] == ["120"]


def test_validate_returns_diagnostics(service):
    result = service.validate(scope="user")
    assert any(d["code"] == "missing_parent" for d in result["diagnostics"])
