"""End-to-end tests driving the server the way a real MCP client does.

Everything else in the suite calls the Python objects directly. These tests
spawn the packaged entry point as a subprocess, speak the MCP protocol over
stdio, and exercise a full session: discover the library, read a profile with
provenance, edit it, and observe the edit through a fresh read. They cover the
wiring the unit tests cannot — tool registration, argument passing, JSON
serialisation of results, and process startup.

The fixtures build a self-contained profile library in a temp directory and
point the server at it through ORCA_DATADIR / ORCA_RESOURCES, so nothing
touches a real OrcaSlicer installation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

mcp_client = pytest.importorskip("mcp.client.stdio", reason="MCP client SDK required")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def tool_payload(result) -> dict:
    """The JSON body of a tool result, whichever shape the SDK returns."""
    if getattr(result, "structuredContent", None):
        content = result.structuredContent
        # A dict-returning tool is wrapped in {"result": ...} by some SDK versions
        if set(content.keys()) == {"result"}:
            return content["result"]
        return content
    text = "".join(block.text for block in result.content if block.type == "text")
    return json.loads(text)


@pytest.fixture
def server_params(orca_tree):
    """Launch the packaged entry point against the fixture library."""
    env = dict(os.environ)
    env["ORCA_DATADIR"] = str(orca_tree["datadir"])
    env["ORCA_RESOURCES"] = str(orca_tree["resources"])
    project_root = Path(__file__).parent.parent
    env["PYTHONPATH"] = str(project_root / "src")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "orca_profiles_mcp.server"],
        env=env,
    )


async def test_client_lists_every_tool(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    names = {t.name for t in tools.tools}
    assert {
        "get_setup",
        "list_profiles",
        "get_profile",
        "get_chain",
        "explain_key",
        "find_children",
        "diff_profiles",
        "validate",
        "check_deltas",
        "set_values",
        "create_profile",
        "rename_profile",
        "delete_profile",
        "normalize_profile",
        "compare_with_upstream",
    } <= names
    # every tool carries a description for the model to act on
    assert all(t.description for t in tools.tools)


async def test_reading_a_profile_over_the_protocol(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            setup = tool_payload(await session.call_tool("get_setup", {}))
            chain = tool_payload(
                await session.call_tool(
                    "get_chain", {"type": "process", "name": "My Fast"}
                )
            )
            explained = tool_payload(
                await session.call_tool(
                    "explain_key",
                    {"type": "process", "name": "My Fast", "key": "outer_wall_speed"},
                )
            )

    assert setup["app_version"] == "2.4.2"
    assert [link["name"] for link in chain["chain"]] == [
        "My Fast",
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]
    assert explained["value"] == ["180"]
    assert explained["origin"] == "My Fast"
    assert [o["link"] for o in explained["overridden"]] == [
        "0.20mm Standard @Acme",
        "fdm_process_common",
    ]


async def test_full_edit_cycle_over_the_protocol(server_params, orca_tree):
    """Create, edit, verify and delete a profile through the protocol alone."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            created = tool_payload(
                await session.call_tool(
                    "create_profile",
                    {
                        "type": "process",
                        "name": "E2E Draft",
                        "inherits": "0.20mm Standard @Acme",
                        "values": {"layer_height": "0.28"},
                    },
                )
            )
            edited = tool_payload(
                await session.call_tool(
                    "set_values",
                    {
                        "type": "process",
                        "name": "E2E Draft",
                        "values": {"outer_wall_speed": ["90"]},
                    },
                )
            )
            after = tool_payload(
                await session.call_tool(
                    "get_profile",
                    {"type": "process", "name": "E2E Draft", "mode": "traced"},
                )
            )
            deltas = tool_payload(
                await session.call_tool("check_deltas", {"scope": "user"})
            )
            removed = tool_payload(
                await session.call_tool(
                    "delete_profile", {"type": "process", "name": "E2E Draft"}
                )
            )

    path = orca_tree["user_dir"] / "process/E2E Draft.json"
    assert created["file"] == str(path)
    assert "outer_wall_speed" in edited["written_keys"]
    assert edited["orca_running_warning"]

    speed = after["values"]["outer_wall_speed"]
    assert speed["value"] == ["90"]
    assert speed["origin"] == "E2E Draft"
    assert speed["overridden"][0]["link"] == "0.20mm Standard @Acme"
    # inherited, not restated in the file
    assert after["values"]["sparse_infill_density"]["origin"] == "fdm_process_common"

    # the profile we just wrote agrees with what Orca would have stored
    assert deltas["mismatched"] == 0

    assert removed["file"] == str(path)
    assert not path.exists()


async def test_writing_an_unknown_key_is_reported_as_an_error(server_params):
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "set_values",
                {
                    "type": "process",
                    "name": "My Fast",
                    "values": {"no_such_setting": "1"},
                },
            )

    assert result.is_error
    text = "".join(b.text for b in result.content if b.type == "text")
    assert "no_such_setting" in text


async def test_diagnostics_reach_the_client(server_params):
    """A broken parent must surface through the protocol, not crash the server."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            chain = tool_payload(
                await session.call_tool(
                    "get_chain", {"type": "process", "name": "Broken"}
                )
            )
            report = tool_payload(
                await session.call_tool("validate", {"scope": "user"})
            )

    assert [d["code"] for d in chain["diagnostics"]] == ["missing_parent"]
    assert any(d["code"] == "missing_parent" for d in report["diagnostics"])
