"""MCP server on top of Service.

SDK 2.0: the high-level MCPServer class, the @server.tool() decorator, and
server.run(transport="stdio").
"""

from __future__ import annotations

from mcp.server import MCPServer

from .service import Service, build_service

server = MCPServer(name="orca-profiles", version="0.1.0")
_service: Service | None = None


def service() -> Service:
    global _service
    if _service is None:
        _service = build_service()
    return _service


@server.tool(
    description="Discovered Orca profile roots, application version, vendors, selected presets"
)
def get_setup() -> dict:
    return service().get_setup()


@server.tool(description="Search profiles by type, name, vendor and source")
def list_profiles(
    type: str | None = None,
    query: str | None = None,
    vendor: str | None = None,
    source: str | None = None,
    compatible_with: str | None = None,
    include_abstract: bool = False,
    limit: int = 200,
) -> dict:
    return service().list_profiles(
        type=type,
        query=query,
        vendor=vendor,
        source=source,
        compatible_with=compatible_with,
        include_abstract=include_abstract,
        limit=limit,
    )


@server.tool(
    description=(
        "A profile with inheritance expanded. mode: raw — file contents, "
        "resolved — effective values, traced — values with provenance. "
        "Engine defaults are excluded unless include_defaults is set"
    )
)
def get_profile(
    type: str,
    name: str,
    mode: str = "resolved",
    keys: str | None = None,
    group: str | None = None,
    include_defaults: bool = False,
    limit: int = 400,
) -> dict:
    return service().get_profile(
        type=type,
        name=name,
        mode=mode,
        keys=keys,
        group=group,
        include_defaults=include_defaults,
        limit=limit,
    )


@server.tool(
    description="The inheritance chain to its root, with how each link was resolved"
)
def get_chain(type: str, name: str) -> dict:
    return service().get_chain(type, name)


@server.tool(
    description=(
        "Where a key's value came from: originating link, overridden values, "
        "engine default"
    )
)
def explain_key(type: str, name: str, key: str) -> dict:
    return service().explain_key(type, name, key)


@server.tool(
    description="Profiles inheriting from this one. Check before editing shared profiles"
)
def find_children(type: str, name: str) -> dict:
    return service().find_children(type, name)


@server.tool(
    description=(
        "Compare two profiles by effective values (mode=resolved) or by their "
        "stored deltas (mode=raw)"
    )
)
def diff_profiles(type: str, a: str, b: str, mode: str = "resolved") -> dict:
    return service().diff_profiles(type, a, b, mode)


@server.tool(
    description=(
        "Integrity check: broken inherits, cycles, unknown keys, redundant "
        "deltas, name collisions"
    )
)
def validate(scope: str = "user") -> dict:
    return service().validate(scope)


@server.tool(
    description="Compare a profile against its version in the OrcaSlicer repository"
)
def compare_with_upstream(type: str, name: str, ref: str = "main") -> dict:
    return service().compare_with_upstream(type, name, ref)


@server.tool(
    description=(
        "Set profile values. The delta against the parent is recomputed "
        "automatically and the paired .info is updated. Editing a shared "
        "profile affects every descendant"
    )
)
def set_values(type: str, name: str, values: dict, backup: bool = True) -> dict:
    return service().set_values(type, name, values, backup=backup)


@server.tool(description="Create a user profile inheriting from the given one")
def create_profile(type: str, name: str, inherits: str, values: dict) -> dict:
    return service().create_profile(type, name, inherits, values)


@server.tool(description="Rename a user profile")
def rename_profile(type: str, name: str, new_name: str) -> dict:
    return service().rename_profile(type, name, new_name)


@server.tool(
    description="Delete a profile; for cloud-synced ones the .info file is flagged instead"
)
def delete_profile(type: str, name: str) -> dict:
    return service().delete_profile(type, name)


@server.tool(description="Drop keys whose values are identical to the parent's")
def normalize_profile(type: str, name: str, backup: bool = True) -> dict:
    return service().normalize_profile(type, name, backup=backup)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
