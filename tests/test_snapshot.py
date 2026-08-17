from orca_profiles_mcp.snapshot import EngineSnapshot


def test_snapshot_loads_engine_defaults():
    snap = EngineSnapshot.load()
    assert len(snap.defaults) > 600
    assert "layer_height" in snap.defaults


def test_snapshot_knows_variant_keysets_per_type():
    snap = EngineSnapshot.load()

    print_set1, print_set2 = snap.keysets_for("process")
    assert "outer_wall_speed" in print_set1
    assert print_set2 == frozenset()

    printer_set1, printer_set2 = snap.keysets_for("machine")
    assert "retraction_length" in printer_set1
    assert "machine_max_acceleration_x" in printer_set2

    filament_set1, _ = snap.keysets_for("filament")
    assert "filament_flow_ratio" in filament_set1


def test_snapshot_maps_extruder_keys_per_type():
    snap = EngineSnapshot.load()
    assert snap.id_key("process") == "print_extruder_id"
    assert snap.variant_key("process") == "print_extruder_variant"
    assert snap.id_key("machine") == "printer_extruder_id"
    assert snap.variant_key("machine") == "printer_extruder_variant"
    assert snap.id_key("filament") is None
    assert snap.variant_key("filament") == "filament_extruder_variant"


def test_snapshot_exposes_categories():
    snap = EngineSnapshot.load()
    assert snap.categories["layer_height"] == "Quality"
    assert snap.categories["outer_wall_speed"] == "Speed"
