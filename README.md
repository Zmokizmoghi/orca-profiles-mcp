# orca-profiles-mcp

An MCP server that reads and edits OrcaSlicer profiles. It expands the whole
`inherits` chain and shows which link set every value.

## What it does

An OrcaSlicer profile stores only its differences from its parent. Opening the
file is not enough to learn the outer wall speed: the value may come from the
parent, from the parent's parent, or from the engine's built-in defaults. This
server walks the chain to its root, computes the effective values and keeps
their provenance.

It handles the parts of Orca that break naive readers:

- parents are resolved **by name, across vendors** — a Sovol filament inherits
  from the OrcaFilamentLibrary;
- a missing `Generic …` parent falls back to `Generic <material> @System`, and
  renamed profiles are found through their `renamed_from` list;
- vectors bound to extruder variants merge element by element, including the
  `nil` marker that means "keep the parent's value here";
- a child may declare more extruders than its parent — a toolchanger on top of
  a single-extruder machine profile — and both extruders keep their values;
- keys that do not belong to the profile's type are dropped, because Orca drops
  them too; they are reported instead of being silently applied.

## Setup

```bash
cd ~/job/orca-profiles-mcp
uv sync
```

Register with Claude Code:

```bash
claude mcp add orca-profiles -- uv --directory ~/job/orca-profiles-mcp run orca-profiles-mcp
```

## Tools

| Tool | Purpose |
|---|---|
| `get_setup` | discovered roots, Orca version, vendors, selected presets |
| `list_profiles` | search by type, name, vendor, source |
| `get_profile` | profile in `raw` / `resolved` / `traced` mode |
| `get_chain` | inheritance chain to the root |
| `explain_key` | where a specific value came from |
| `find_children` | which profiles inherit from this one |
| `diff_profiles` | compare two profiles |
| `compare_with_upstream` | compare against the OrcaSlicer repository |
| `validate` | broken `inherits`, cycles, unknown keys, redundant deltas |
| `check_deltas` | verify expansion against the deltas Orca itself wrote |
| | reports redundant keys and unexplained vector lengths separately |
| `set_values` | set values with delta recomputation |
| `create_profile` | create a user profile |
| `rename_profile`, `delete_profile` | rename and delete |
| `normalize_profile` | drop keys identical to the parent's |

Values are returned exactly as the files store them: `"0.20"` stays `"0.20"`,
and `"100%"` stays a percentage. The engine normalises both when it slices;
this server does not, so what you read is what the profile says and what gets
written back is unchanged.

## Writing profiles

Your own profiles are edited freely. Touching a system or bundled one requires
`force=true`: those files belong to a vendor library, the next profile update
restores them, and every descendant inherits the change.

Writes go through a temporary file and an atomic rename, so an interrupted
write cannot truncate a profile, and a backup copy is made next to the file
first (`backup=false` disables it). Values are checked before anything is
written — a key belonging to another profile type, a vector where the engine
wants a scalar, or a number where the format requires a string is refused
rather than stored and silently dropped by Orca. Settings your pinned snapshot
does not recognise are carried through untouched, so a profile written by a
newer Orca does not lose them.

**OrcaSlicer reads profiles at startup and rewrites them at exit.** Edits made
while the application is running will be overwritten — close Orca first.

## How correctness is checked

Orca's CLI cannot verify inheritance. `--export-settings` returns the engine
defaults plus the keys present in the files handed to it and never walks
`inherits`; selecting presets through `OrcaSlicer.conf` does not activate them;
passing a whole chain as a file list is rejected as a duplicate config file.
All three were tried against 2.4.2.

What Orca does leave behind is evidence of its own expansion: when it saves a
user profile it stores the minimal delta against the fully expanded parent. So
every profile Orca has written is a recorded answer. `check_deltas` recomputes
those deltas and compares — a mismatch means the resolver expands a parent
differently than the engine did.

This is what `tests/test_smoke.py` asserts against the installed library, and
it is how the toolchanger vector defect was found.

Keys stored despite already matching the parent are reported separately: they
are harmless leftovers from before a parent changed, not resolver errors.

## Refreshing the engine snapshot

Engine defaults, the variant key sets and the per-type key lists are captured
from the installed Orca into `src/orca_profiles_mcp/data/engine-snapshot.json`,
pinned to its version tag. After upgrading OrcaSlicer:

```bash
uv run python scripts/build_snapshot.py
uv run pytest
```

## Tests

```bash
uv run pytest
```

Four layers:

- unit tests over a miniature fixture library, one per edge case — cross-vendor
  inheritance, the `Generic` fallback, `renamed_from`, cycles, missing parents,
  stride-1 and stride-2 vectors, `nil` elements;
- write round-trips: read → write unchanged → the file is byte-identical;
- end-to-end tests that spawn the packaged entry point as a subprocess and
  drive it over MCP stdio, covering tool registration, a full
  create/edit/verify/delete cycle, and error propagation;
- checks against the installed library, including the delta verification
  described above.

Tests using the real library skip themselves when no Orca data directory is
present; everything else runs against fixtures.

## Documents

- Design: `docs/specs/2026-08-17-orca-profiles-mcp-design.md` — includes what
  reading the OrcaSlicer sources established about the profile format, and what
  the CLI experiments ruled out
- Implementation plan: `docs/plans/2026-08-17-orca-profiles-mcp.md`

## Licence

AGPL-3.0, matching [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) itself.
This project contains no OrcaSlicer code, but its inheritance logic is a
line-by-line port of `Preset.cpp` and `PrintConfig.cpp`, and the engine snapshot
holds default values and key lists extracted from that source.

Not affiliated with or endorsed by the OrcaSlicer project.
