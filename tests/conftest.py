import json
from pathlib import Path

import pytest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def orca_tree(tmp_path, monkeypatch):
    """Miniature profile library: bundle + datadir/system + user profiles."""
    datadir = tmp_path / "datadir"
    resources = tmp_path / "resources"
    user_dir = datadir / "user" / "uid-1"

    # --- bundle vendor ---
    bundle = resources / "profiles"
    write_json(
        bundle / "Acme.json",
        {
            "name": "Acme",
            "version": "02.04.00.01",
            "machine_model_list": [
                {"name": "Acme One", "sub_path": "machine/Acme One.json"}
            ],
            "machine_list": [
                {
                    "name": "fdm_machine_common",
                    "sub_path": "machine/fdm_machine_common.json",
                },
                {
                    "name": "Acme One 0.4 nozzle",
                    "sub_path": "machine/Acme One 0.4 nozzle.json",
                },
            ],
            "process_list": [
                {
                    "name": "fdm_process_common",
                    "sub_path": "process/fdm_process_common.json",
                },
                {
                    "name": "0.20mm Standard @Acme",
                    "sub_path": "process/0.20mm Standard @Acme.json",
                },
                {
                    "name": "0.30mm Draft @Acme",
                    "sub_path": "process/0.30mm Draft @Acme.json",
                },
            ],
            "filament_list": [{"name": "Acme PLA", "sub_path": "filament/Acme PLA.json"}],
        },
    )
    write_json(
        bundle / "Acme/machine/Acme One.json",
        {
            "type": "machine_model",
            "name": "Acme One",
            "model_id": "Acme-One",
            "nozzle_diameter": "0.4",
        },
    )
    write_json(
        bundle / "Acme/machine/fdm_machine_common.json",
        {
            "type": "machine",
            "name": "fdm_machine_common",
            "from": "system",
            "instantiation": "false",
            "retraction_length": ["0.8"],
            "machine_max_acceleration_x": ["10000", "10000"],
        },
    )
    write_json(
        bundle / "Acme/machine/Acme One 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "Acme One 0.4 nozzle",
            "from": "system",
            "instantiation": "true",
            "inherits": "fdm_machine_common",
            "printer_model": "Acme One",
            "nozzle_diameter": ["0.4"],
        },
    )
    write_json(
        bundle / "Acme/process/fdm_process_common.json",
        {
            "type": "process",
            "name": "fdm_process_common",
            "from": "system",
            "instantiation": "false",
            "layer_height": "0.2",
            "outer_wall_speed": ["200"],
            "sparse_infill_density": "15%",
        },
    )
    write_json(
        bundle / "Acme/process/0.20mm Standard @Acme.json",
        {
            "type": "process",
            "name": "0.20mm Standard @Acme",
            "from": "system",
            "instantiation": "true",
            "inherits": "fdm_process_common",
            "outer_wall_speed": ["120"],
            "compatible_printers": ["Acme One 0.4 nozzle"],
        },
    )
    write_json(
        bundle / "Acme/process/0.30mm Draft @Acme.json",
        {
            "type": "process",
            "name": "0.30mm Draft @Acme",
            "from": "system",
            "instantiation": "true",
            "inherits": "fdm_process_common",
            "renamed_from": ["0.30mm Rough @Acme"],
            "layer_height": "0.3",
        },
    )
    write_json(
        bundle / "Acme/filament/Acme PLA.json",
        {
            "type": "filament",
            "name": "Acme PLA",
            "from": "system",
            "instantiation": "true",
            "inherits": "Generic PLA @System",
            "filament_id": "ACME01",
        },
    )

    # --- filament library in the bundle ---
    write_json(
        bundle / "OrcaFilamentLibrary.json",
        {
            "name": "OrcaFilamentLibrary",
            "version": "02.04.00.03",
            "filament_list": [
                {
                    "name": "fdm_filament_common",
                    "sub_path": "filament/base/fdm_filament_common.json",
                },
                {
                    "name": "fdm_filament_pla",
                    "sub_path": "filament/base/fdm_filament_pla.json",
                },
                {
                    "name": "Generic PLA @System",
                    "sub_path": "filament/Generic PLA @System.json",
                },
            ],
        },
    )
    write_json(
        bundle / "OrcaFilamentLibrary/filament/base/fdm_filament_common.json",
        {
            "type": "filament",
            "name": "fdm_filament_common",
            "from": "system",
            "instantiation": "false",
            "filament_flow_ratio": ["1"],
            "filament_type": ["PLA"],
        },
    )
    write_json(
        bundle / "OrcaFilamentLibrary/filament/base/fdm_filament_pla.json",
        {
            "type": "filament",
            "name": "fdm_filament_pla",
            "from": "system",
            "instantiation": "false",
            "inherits": "fdm_filament_common",
            "filament_flow_ratio": ["0.98"],
        },
    )
    write_json(
        bundle / "OrcaFilamentLibrary/filament/Generic PLA @System.json",
        {
            "type": "filament",
            "name": "Generic PLA @System",
            "from": "system",
            "instantiation": "true",
            "inherits": "fdm_filament_pla",
        },
    )

    # --- datadir/system vendor: shadows the bundle, name differs by case ---
    system = datadir / "system"
    write_json(
        system / "AcmeStock.json",
        {
            "name": "AcmeStock",
            "version": "01.09.00.02",
            "machine_list": [
                {
                    "name": "ACME ONE 0.4 nozzle",
                    "sub_path": "machine/ACME ONE 0.4 nozzle.json",
                }
            ],
        },
    )
    write_json(
        system / "AcmeStock/machine/ACME ONE 0.4 nozzle.json",
        {
            "type": "machine",
            "name": "ACME ONE 0.4 nozzle",
            "from": "system",
            "instantiation": "true",
            "nozzle_diameter": ["0.4"],
            "retraction_length": ["1.2"],
        },
    )

    # --- user profiles: no "type" field, type comes from the directory ---
    write_json(
        user_dir / "process/My Fast.json",
        {
            "name": "My Fast",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.20mm Standard @Acme",
            "outer_wall_speed": ["180"],
            "print_settings_id": "My Fast",
        },
    )
    (user_dir / "process/My Fast.info").write_text(
        "sync_info = \nuser_id = uid-1\nsetting_id = \nbase_id = \n"
        "updated_time = 1700000000\n",
        encoding="utf-8",
    )
    # inherits a parent under its former name
    write_json(
        user_dir / "process/Uses Old Name.json",
        {
            "name": "Uses Old Name",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "0.30mm Rough @Acme",
            "top_shell_layers": "5",
        },
    )
    # inherits a Generic filament with a foreign suffix
    write_json(
        user_dir / "filament/My PLA.json",
        {
            "name": "My PLA",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "Generic PLA @Acme One",
            "filament_flow_ratio": ["0.95"],
        },
    )
    # parent does not exist at all
    write_json(
        user_dir / "process/Broken.json",
        {
            "name": "Broken",
            "from": "User",
            "version": "1.9.0.2",
            "inherits": "No Such Profile",
            "top_shell_layers": "9",
        },
    )

    (datadir / "OrcaSlicer.conf").write_text(
        json.dumps(
            {
                "header": "OrcaSlicer 2.4.2",
                "presets": {"machine": "ACME ONE 0.4 nozzle", "filaments": None},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ORCA_DATADIR", str(datadir))
    monkeypatch.setenv("ORCA_RESOURCES", str(resources))
    return {"datadir": datadir, "resources": resources, "user_dir": user_dir}


@pytest.fixture
def write_profile():
    """Profile-writing helper for tests.

    Exposed as a fixture rather than imported from conftest: the tests package
    is not installed, so importing from it is unreliable.
    """
    return write_json
