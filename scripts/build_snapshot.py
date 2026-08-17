"""Generate the Orca engine snapshot.

Defaults come from `OrcaSlicer --export-settings` (616 keys in 2.4.2).
Variant key sets, categories and option types are parsed out of PrintConfig.cpp:
  print_options_with_variant       PrintConfig.cpp:9202  (44 keys)
  filament_options_with_variant    PrintConfig.cpp:9249  (49 keys)
  printer_options_with_variant_1   PrintConfig.cpp:9317  (28 keys)
  printer_options_with_variant_2   PrintConfig.cpp:9351  (16 keys, stride 2)
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

MACOS_BINARY = Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer")
SOURCE_URL = (
    "https://raw.githubusercontent.com/SoftFever/OrcaSlicer/{ref}/src/libslic3r/{name}"
)

VARIANT_SETS = {
    "print": "print_options_with_variant",
    "filament": "filament_options_with_variant",
    "printer_1": "printer_options_with_variant_1",
    "printer_2": "printer_options_with_variant_2",
}

# Which keys each profile type may hold. Orca drops the rest on load
# (Preset::remove_invalid_keys, Preset.cpp:1766), so a machine profile that
# carries a process key does not actually apply it.
# Preset.cpp:1005, 1326, 1391, 1406; PrintConfig.cpp:8137.
TYPE_OPTION_LISTS = {
    "process": ["s_Preset_print_options"],
    "filament": ["s_Preset_filament_options"],
    "machine": [
        "s_Preset_printer_options",
        "s_Preset_machine_limits_options",
        "m_extruder_option_keys",
    ],
}


def export_defaults(binary: Path, datadir: Path) -> dict:
    """Capture engine defaults: running without --load-settings yields bare values."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "defaults.json"
        subprocess.run(
            [str(binary), "--datadir", str(datadir), "--export-settings", str(out)],
            check=True,
            capture_output=True,
            timeout=180,
        )
        return json.loads(out.read_text(encoding="utf-8"))


def read_source(name: str, directory: str | None, ref: str) -> str:
    """Read a libslic3r source file from a local checkout, or fetch it at a ref.

    The ref should match the installed Orca: these lists change between
    releases, and a snapshot taken from a different revision would silently
    describe a different engine.
    """
    if directory is not None:
        return (Path(directory) / name).read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCE_URL.format(ref=ref, name=name), timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse_string_list(src: str, symbol: str) -> list[str]:
    """Extract the string literals of a `std::vector`/`std::set` initialiser."""
    match = re.search(
        r"\b" + re.escape(symbol) + r"\s*(?:=\s*)?\{(.*?)\n\s*\};", src, re.S
    )
    if match is None:
        raise SystemExit(f"symbol {symbol} not found")
    return re.findall(r'"([^"]+)"', match.group(1))


def parse_type_options(print_config: str, preset: str) -> dict[str, list[str]]:
    """Keys allowed per profile type; anything else is dropped by Orca on load."""
    sources = {"m_extruder_option_keys": print_config}
    result = {}
    for ptype, symbols in TYPE_OPTION_LISTS.items():
        keys: set[str] = set()
        for symbol in symbols:
            keys.update(parse_string_list(sources.get(symbol, preset), symbol))
        result[ptype] = sorted(keys)
    return result


def parse_variant_sets(src: str) -> dict[str, list[str]]:
    result = {}
    for alias, cpp_name in VARIANT_SETS.items():
        match = re.search(
            r"std::set<std::string>\s+" + cpp_name + r"\s*=\s*\{(.*?)\n\};", src, re.S
        )
        if match is None:
            raise SystemExit(f"key set {cpp_name} not found in PrintConfig.cpp")
        result[alias] = sorted(set(re.findall(r'"([^"]+)"', match.group(1))))
    return result


def parse_options(src: str) -> tuple[dict[str, str], dict[str, str]]:
    """Categories and option types from `def = this->add("key", coType);` blocks."""
    categories, types = {}, {}
    blocks = re.findall(
        r'def\s*=\s*this->add\(\s*"([^"]+)"\s*,\s*(co\w+)\s*\)\s*;'
        r"(.*?)(?=def\s*=\s*this->add\(|\Z)",
        src,
        re.S,
    )
    for key, ctype, body in blocks:
        types[key] = ctype
        cat = re.search(r'def->category\s*=\s*L\("([^"]+)"\)', body)
        if cat:
            categories[key] = cat.group(1)
    return categories, types


def detect_version(datadir: Path) -> str:
    conf = datadir / "OrcaSlicer.conf"
    if conf.exists():
        header = json.loads(conf.read_text(encoding="utf-8")).get("header", "")
        if header:
            return header.split()[-1]
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, default=MACOS_BINARY)
    parser.add_argument(
        "--datadir",
        type=Path,
        default=Path.home() / "Library/Application Support/OrcaSlicer",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="path to a local src/libslic3r directory; files are fetched from "
        "GitHub when omitted",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="git ref to fetch PrintConfig.cpp from; defaults to v<installed version>",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent.parent
        / "src/orca_profiles_mcp/data/engine-snapshot.json",
    )
    args = parser.parse_args()

    version = detect_version(args.datadir)
    ref = args.ref or (f"v{version}" if version != "unknown" else "main")

    defaults = export_defaults(args.binary, args.datadir)
    print_config = read_source("PrintConfig.cpp", args.sources, ref)
    preset = read_source("Preset.cpp", args.sources, ref)
    categories, types = parse_options(print_config)
    type_options = parse_type_options(print_config, preset)

    snapshot = {
        "orca_version": version,
        "source_ref": ref if args.sources is None else str(args.sources),
        "defaults": defaults,
        "variant_sets": parse_variant_sets(print_config),
        "type_options": type_options,
        "categories": categories,
        "option_types": types,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"snapshot written: {args.out}\n"
        f"  orca version: {snapshot['orca_version']}\n"
        f"  source ref: {snapshot['source_ref']}\n"
        f"  defaults: {len(defaults)}\n"
        f"  options with a category: {len(categories)} of {len(types)}\n"
        + "\n".join(
            f"  keys allowed for {ptype}: {len(keys)}"
            for ptype, keys in sorted(type_options.items())
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
