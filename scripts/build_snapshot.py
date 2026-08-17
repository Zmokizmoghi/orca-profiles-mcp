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
PRINTCONFIG_URL = (
    "https://raw.githubusercontent.com/SoftFever/OrcaSlicer/{ref}/src/libslic3r/PrintConfig.cpp"
)

VARIANT_SETS = {
    "print": "print_options_with_variant",
    "filament": "filament_options_with_variant",
    "printer_1": "printer_options_with_variant_1",
    "printer_2": "printer_options_with_variant_2",
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


def read_printconfig(source: str | None, ref: str) -> str:
    """Read PrintConfig.cpp from a local path, or fetch it at the given git ref.

    The ref should match the installed Orca: the variant key sets change between
    releases, and a snapshot taken from a different revision would silently
    describe a different engine.
    """
    if source is None:
        with urllib.request.urlopen(PRINTCONFIG_URL.format(ref=ref), timeout=60) as resp:
            return resp.read().decode("utf-8")
    return Path(source).read_text(encoding="utf-8")


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
        "--printconfig",
        default=None,
        help="path to PrintConfig.cpp; downloaded from GitHub when omitted",
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
    src = read_printconfig(args.printconfig, ref)
    categories, types = parse_options(src)

    snapshot = {
        "orca_version": version,
        "source_ref": ref if args.printconfig is None else str(args.printconfig),
        "defaults": defaults,
        "variant_sets": parse_variant_sets(src),
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
        f"  options with a category: {len(categories)} of {len(types)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
