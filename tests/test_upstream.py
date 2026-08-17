from orca_profiles_mcp.service import build_service
from orca_profiles_mcp.upstream import UpstreamClient

BASE = "https://raw.githubusercontent.com/SoftFever/OrcaSlicer/main/resources/profiles"
VENDOR_URL = f"{BASE}/Acme.json"
PROFILE_URL = f"{BASE}/Acme/process/0.20mm Standard @Acme.json"


class FakeTransport:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, url: str) -> dict | None:
        self.calls.append(url)
        return self.responses.get(url)


def vendor_listing() -> dict:
    return {
        "name": "Acme",
        "process_list": [
            {
                "name": "0.20mm Standard @Acme",
                "sub_path": "process/0.20mm Standard @Acme.json",
            }
        ],
    }


def test_client_fetches_vendor_and_profile(tmp_path):
    transport = FakeTransport(
        {
            VENDOR_URL: vendor_listing(),
            PROFILE_URL: {"type": "process", "outer_wall_speed": ["150"]},
        }
    )
    client = UpstreamClient(cache_dir=tmp_path, transport=transport)
    profile = client.fetch_profile("Acme", "process/0.20mm Standard @Acme.json")
    assert profile["outer_wall_speed"] == ["150"]


def test_client_uses_cache_on_second_call(tmp_path):
    transport = FakeTransport({PROFILE_URL: {"name": "x"}})
    client = UpstreamClient(cache_dir=tmp_path, transport=transport)
    client.fetch_profile("Acme", "process/0.20mm Standard @Acme.json")
    client.fetch_profile("Acme", "process/0.20mm Standard @Acme.json")
    assert len(transport.calls) == 1


def test_compare_with_upstream_reports_differences(orca_tree, tmp_path):
    transport = FakeTransport(
        {
            VENDOR_URL: vendor_listing(),
            PROFILE_URL: {
                "type": "process",
                "name": "0.20mm Standard @Acme",
                "inherits": "fdm_process_common",
                "outer_wall_speed": ["150"],
            },
        }
    )
    service = build_service()
    service.upstream = UpstreamClient(cache_dir=tmp_path, transport=transport)

    result = service.compare_with_upstream("process", "0.20mm Standard @Acme")
    assert result["found_upstream"] is True
    assert result["differences"]["outer_wall_speed"] == {
        "local": ["120"],
        "upstream": ["150"],
    }


def test_compare_with_upstream_handles_missing_profile(orca_tree, tmp_path):
    service = build_service()
    service.upstream = UpstreamClient(cache_dir=tmp_path, transport=FakeTransport({}))
    result = service.compare_with_upstream("process", "0.20mm Standard @Acme")
    assert result["found_upstream"] is False
