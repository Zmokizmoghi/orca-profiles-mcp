"""Regressions for defects found in external review.

Each test names the failure it locks down. They are grouped here rather than
scattered so the review's findings stay traceable.
"""

import json

import pytest

from orca_profiles_mcp.index import ProfileIndex
from orca_profiles_mcp.resolver import Resolver
from orca_profiles_mcp.snapshot import EngineSnapshot
from orca_profiles_mcp.sources import discover
from orca_profiles_mcp.variants import merge_vector
from orca_profiles_mcp.writer import Writer


def build(orca_tree=None):
    index = ProfileIndex.build(discover())
    snapshot = EngineSnapshot.load()
    return index, Resolver(index, snapshot), snapshot


@pytest.fixture
def writer(orca_tree):
    index, resolver, snapshot = build()
    return Writer(index, resolver, snapshot)


def register_machine(orca_tree, write_profile, vendor: str, name: str, body: dict):
    """Add a machine profile to a bundle vendor, creating the vendor if needed."""
    bundle = orca_tree["resources"] / "profiles"
    vendor_file = bundle / f"{vendor}.json"
    if vendor_file.exists():
        data = json.loads(vendor_file.read_text(encoding="utf-8"))
    else:
        data = {"name": vendor, "machine_list": []}
    data.setdefault("machine_list", []).append(
        {"name": name, "sub_path": f"machine/{name}.json"}
    )
    write_profile(vendor_file, data)
    write_profile(bundle / f"{vendor}/machine/{name}.json", {**body, "name": name})


# --- nil must resolve against the slot it lands in, not by position ---


def test_nil_keeps_the_value_of_the_slot_it_maps_to():
    """merge_vector must leave a nil element as whatever the parent slot holds."""
    merged = merge_vector(["0.8", "0.9"], ["nil"], [-1, 0], stride=1)
    assert merged == ["0.8", "0.9"]


def test_nil_in_a_full_layout_keeps_each_parent_element():
    merged = merge_vector(["0.8", "0.9"], ["nil", "1.5"], [0, 1], stride=1)
    assert merged == ["0.8", "1.5"]


def test_resolver_expands_nil_against_the_mapped_parent_slot(orca_tree, write_profile):
    register_machine(
        orca_tree,
        write_profile,
        "Acme",
        "Acme Two Variants",
        {
            "type": "machine",
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["0.8", "0.9"],
        },
    )
    write_profile(
        orca_tree["user_dir"] / "machine/Second Only.json",
        {
            "name": "Second Only",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Two Variants",
            "printer_extruder_variant": ["0.6"],
            "retraction_length": ["nil"],
        },
    )
    _, resolver, _ = build()
    resolved = resolver.resolve("machine", "Second Only")
    # the child touches only the 0.6 slot and asks to keep its inherited value
    assert resolved.values["retraction_length"].value == ["0.8", "0.9"]


# --- a profile name must not escape the profile directory ---


@pytest.mark.parametrize(
    "bad_name",
    ["/tmp/escaped", "../../escaped", "sub/dir", "..", ".", "", "with\x00null"],
)
def test_create_profile_rejects_names_that_escape_the_directory(writer, bad_name):
    with pytest.raises(ValueError):
        writer.create_profile(
            "process", bad_name, "0.20mm Standard @Acme", {"layer_height": "0.1"}
        )


def test_rename_profile_rejects_an_escaping_name(writer):
    writer.create_profile(
        "process", "Renamable", "0.20mm Standard @Acme", {"layer_height": "0.1"}
    )
    with pytest.raises(ValueError):
        writer.rename_profile("process", "Renamable", "../escaped")


# --- writes must respect the option's type ownership and shape ---


def test_set_values_rejects_a_key_from_another_profile_type(writer):
    """nozzle_diameter is a machine option; Orca would drop it from a process."""
    with pytest.raises(ValueError, match="machine"):
        writer.set_values("process", "My Fast", {"nozzle_diameter": ["0.6"]})


def test_set_values_rejects_a_vector_for_a_scalar_option(writer):
    with pytest.raises(ValueError, match="scalar"):
        writer.set_values("process", "My Fast", {"layer_height": ["0.1"]})


def test_set_values_rejects_non_string_values(writer):
    with pytest.raises(ValueError, match="string"):
        writer.set_values("process", "My Fast", {"layer_height": 0.1})


def test_create_profile_validates_values_too(writer):
    with pytest.raises(ValueError):
        writer.create_profile(
            "process", "Bad New", "0.20mm Standard @Acme", {"nozzle_diameter": ["0.6"]}
        )


def test_create_profile_rejects_metadata_in_values(writer):
    """values must not be able to rewrite the profile's own identity."""
    with pytest.raises(ValueError, match="metadata"):
        writer.create_profile(
            "process",
            "Sneaky",
            "0.20mm Standard @Acme",
            {"inherits": "Something Else", "name": "Other"},
        )


def test_filament_settings_id_is_written_as_a_list(writer, orca_tree):
    """filament_settings_id is coStrings, unlike the scalar print/printer ids."""
    writer.create_profile("filament", "Tuned PLA", "Generic PLA @System", {})
    data = json.loads(
        (orca_tree["user_dir"] / "filament/Tuned PLA.json").read_text(encoding="utf-8")
    )
    assert data["filament_settings_id"] == ["Tuned PLA"]


# --- the writer must pick the same parent the resolver picked ---


def test_writer_and_resolver_agree_on_the_parent(orca_tree, write_profile):
    """Two vendors ship a same-named base; both sides must pick the same one.

    Which one wins is the engine's business (a global lookup in load order).
    What must never happen is the resolver expanding against one base while the
    writer computes its delta against another — that silently drops overrides.
    """
    register_machine(
        orca_tree,
        write_profile,
        "Acme",
        "shared_base",
        {
            "type": "machine",
            "from": "system",
            "instantiation": "false",
            "retraction_length": ["0.8"],
        },
    )
    register_machine(
        orca_tree,
        write_profile,
        "Rival",
        "shared_base",
        {
            "type": "machine",
            "from": "system",
            "instantiation": "false",
            "retraction_length": ["1.2"],
        },
    )
    register_machine(
        orca_tree,
        write_profile,
        "Rival",
        "Rival Printer",
        {
            "type": "machine",
            "from": "system",
            "instantiation": "true",
            "inherits": "shared_base",
            "nozzle_diameter": ["0.4"],
            # explicitly restates a value that only Acme's base happens to match
            "retraction_length": ["0.8"],
        },
    )

    index, resolver, snapshot = build()
    writer = Writer(index, resolver, snapshot)

    entry = index.get("machine", "Rival Printer")
    resolver_parent, _ = resolver._find_parent("machine", "shared_base", entry.vendor)
    writer_parent_values = writer._parent_values(entry, index.load_raw(entry))
    resolver_parent_values = {
        k: v.value for k, v in resolver.resolve_entry(resolver_parent).values.items()
    }
    assert writer_parent_values == resolver_parent_values

    # and the profile's own value survives a normalise either way
    chain_parent = resolver.resolve("machine", "Rival Printer").chain[1]
    assert chain_parent.name == resolver_parent.name
    assert chain_parent.vendor == resolver_parent.vendor


# --- data must survive a write ---


def test_keys_unknown_to_the_snapshot_are_preserved(writer, orca_tree, write_profile):
    """A newer Orca's settings must not be deleted by an unrelated edit."""
    path = orca_tree["user_dir"] / "process/Futuristic.json"
    write_profile(
        path,
        {
            "name": "Futuristic",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "some_future_setting": "custom",
            "top_shell_layers": "4",
        },
    )
    index, resolver, snapshot = build()
    Writer(index, resolver, snapshot).set_values(
        "process", "Futuristic", {"top_shell_layers": "5"}
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["some_future_setting"] == "custom"
    assert data["top_shell_layers"] == "5"


def test_create_does_not_overwrite_a_file_outside_the_index(writer, orca_tree):
    """Unreadable files are skipped by the index; the path is still taken."""
    stray = orca_tree["user_dir"] / "process/Stray.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("{ this is not valid json", encoding="utf-8")

    index, resolver, snapshot = build()
    with pytest.raises(ValueError, match="already exists"):
        Writer(index, resolver, snapshot).create_profile(
            "process", "Stray", "0.20mm Standard @Acme", {"layer_height": "0.1"}
        )
    assert stray.read_text(encoding="utf-8").startswith("{ this is not valid json")


def test_writes_are_atomic(writer, orca_tree, monkeypatch):
    """A failure mid-write must leave the previous file intact."""
    import orca_profiles_mcp.writer as writer_module

    path = orca_tree["user_dir"] / "process/My Fast.json"
    before = path.read_text(encoding="utf-8")

    real_replace = writer_module.os.replace

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(writer_module.os, "replace", explode)
    with pytest.raises(OSError):
        writer.set_values("process", "My Fast", {"top_shell_layers": "6"}, backup=False)
    monkeypatch.setattr(writer_module.os, "replace", real_replace)

    assert path.read_text(encoding="utf-8") == before
    assert not list(path.parent.glob(".*tmp"))


def test_info_keeps_fields_it_does_not_know(orca_tree):
    from orca_profiles_mcp.writer import read_info, write_info

    info_path = orca_tree["user_dir"] / "process/My Fast.info"
    info_path.write_text(
        "sync_info = \nuser_id = uid-1\nsetting_id = \nbase_id = \n"
        "updated_time = 1700000000\nfuture_field = keep me\n",
        encoding="utf-8",
    )
    info = read_info(info_path)
    write_info(info_path, info)
    assert "future_field = keep me" in info_path.read_text(encoding="utf-8")


# --- the delta check must not cry wolf ---


def test_spelled_out_element_is_not_reported_as_engine_divergence(
    orca_tree, write_profile
):
    """A file that writes a value the encoder would compress to nil is redundant."""
    from orca_profiles_mcp.delta_check import check_profile_delta

    register_machine(
        orca_tree,
        write_profile,
        "Acme",
        "Acme Pair",
        {
            "type": "machine",
            "from": "system",
            "instantiation": "true",
            "printer_extruder_variant": ["0.4", "0.6"],
            "retraction_length": ["2", "3"],
        },
    )
    write_profile(
        orca_tree["user_dir"] / "machine/Spelled Out.json",
        {
            "name": "Spelled Out",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Acme Pair",
            "printer_extruder_variant": ["0.4", "0.6"],
            # element 0 restates the parent instead of using "nil"
            "retraction_length": ["2", "9"],
        },
    )
    index, resolver, snapshot = build()
    result = check_profile_delta(index, resolver, snapshot, "machine", "Spelled Out")
    assert result["consistent"] is True
    assert result["differing_values"] == {}
