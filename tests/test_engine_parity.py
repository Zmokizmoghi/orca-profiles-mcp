import json
import shutil
from pathlib import Path

import pytest

from orca_profiles_mcp.engine_check import accepts_file, compare_with_engine
from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.writer import Writer

BINARY = Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer")
SAMPLE = json.loads((Path(__file__).parent / "engine_sample.json").read_text())

pytestmark = pytest.mark.engine


@pytest.fixture(scope="module")
def real_datadir(tmp_path_factory):
    """A copy of the working datadir: the engine runs against the copy, never live data."""
    if not BINARY.exists():
        pytest.skip("OrcaSlicer is not installed")
    source = Path.home() / "Library/Application Support/OrcaSlicer"
    if not source.exists():
        pytest.skip("no OrcaSlicer data directory")
    target = tmp_path_factory.mktemp("datadir")
    for name in ("system", "user", "OrcaSlicer.conf"):
        src = source / name
        if src.is_dir():
            shutil.copytree(src, target / name)
        elif src.exists():
            shutil.copy2(src, target / name)
    return target


@pytest.mark.parametrize("case", SAMPLE["spot_checks"], ids=lambda c: c["name"])
def test_resolver_matches_engine(case, real_datadir, monkeypatch):
    monkeypatch.setenv("ORCA_DATADIR", str(real_datadir))
    index = ProfileIndex.build(discover())
    resolver = Resolver(index, EngineSnapshot.load())
    if index.get(case["type"], case["name"]) is None:
        pytest.skip(f"profile absent from the library: {case['name']}")

    result = compare_with_engine(
        resolver,
        index,
        case["type"],
        case["name"],
        binary=BINARY,
        datadir=real_datadir,
        allowlist=set(SAMPLE["allowlist"]),
    )
    assert result["mismatches"] == {}, (
        f"{len(result['mismatches'])} mismatches out of {result['compared_keys']} keys"
    )


def test_engine_accepts_a_file_we_wrote(real_datadir, monkeypatch):
    """Level 4 of the test plan: Orca must load a profile written by the writer."""
    monkeypatch.setenv("ORCA_DATADIR", str(real_datadir))
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    writer = Writer(index, Resolver(index, snapshot), snapshot)

    target = SAMPLE["spot_checks"][0]
    if index.get(target["type"], target["name"]) is None:
        pytest.skip(f"profile absent from the library: {target['name']}")

    writer.create_profile(
        target["type"], "parity-check-tmp", target["name"], {"top_shell_layers": "7"}
    )
    try:
        assert accepts_file(
            BINARY, real_datadir, index, target["type"], "parity-check-tmp"
        )
    finally:
        writer.delete_profile(target["type"], "parity-check-tmp")
