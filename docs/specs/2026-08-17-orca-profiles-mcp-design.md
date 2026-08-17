# orca-profiles-mcp — Design

Date: 2026-08-17

## 1. Problem

An MCP server that reads and edits OrcaSlicer profiles, fully expanding the inheritance mechanism: rather than returning the contents of a JSON file, it walks the `inherits` chain to its root, computes the effective value of every setting, and records provenance — which link in the chain set the value and what it overrode.

Intended uses:

- analysing and tuning the user's own profiles;
- diagnosis and explanation ("why does this profile print at that speed");
- creating and editing profiles.

## 2. Established facts about how Orca works

This section records findings from reading the OrcaSlicer sources (master as of 2026-08-17; installed application version 2.4.2) and the local profile library. Line references are given so they can be re-checked when Orca is updated.

### 2.1 Profile format

A profile is JSON. The reserved keys are defined in `src/libslic3r/Preset.hpp:44-84`:

| Key | Meaning |
|---|---|
| `type` | `machine` \| `process` \| `filament` \| `machine_model` |
| `name` | profile name, also the key used to resolve `inherits` |
| `from` | `system` \| `User` \| `Bundle` \| `Project` \| `Default` |
| `instantiation` | `"false"` marks an abstract template, hidden in the UI |
| `inherits` | parent name (not a path) |
| `setting_id`, `base_id`, `filament_id` | sync identifiers |
| `version` | profile/format version |

All values serialise as strings; vector options serialise as arrays of strings (`Config.cpp:1516`).

**User profiles carry no `type` field** — the type comes from the directory (`machine/`, `process/`, `filament/`). A practical consequence: the Orca CLI refuses to load them (`unknown config type`).

### 2.2 Resolving `inherits`

`inherits` refers to a **name**, not a path, and is resolved against the global collection for that profile type, across vendors. Example from the local library: `Sovol SV08 PLA` (vendor Sovol) inherits `Generic PLA @System` (vendor OrcaFilamentLibrary).

Resolution order (`PresetCollection::find_preset2`, `Preset.cpp`):

1. exact name match within the type's collection;
2. the `renamed_from` map — former names of renamed system profiles (`Preset.cpp:3813`);
3. fallback: if the name contains `Generic`, this regex is applied
   `^(?:.*?\b(?:\w+_)?)(Generic)\b\s+([^@]+?)\s*(?:@.*)?$` → `Generic $2 @System`,
   redirecting to the OrcaFilamentLibrary vendor.

If the parent cannot be found and `inherits` is non-empty, Orca treats the profile as broken and skips it.

### 2.3 Merging parent into child

`Preset.cpp:1743-1746`:

```cpp
preset.config = inherit_preset->config;   // full copy of the expanded parent
preset.config.update_diff_values_to_child_config(config, ...);
```

The merge is **flat**, not recursive: the child's keys replace the parent's keys wholesale.

The exception is vector options belonging to the variant key sets (`PrintConfig.cpp:11377`). There, elements are matched through the `*_extruder_variant` and `*_extruder_id` lists with a stride of 1 or 2, not by position. The sets (`Preset::get_extruder_names_and_keysets`, `Preset.cpp:927`):

| Type | id key | variant key | stride-1 set | stride-2 set |
|---|---|---|---|---|
| process | `print_extruder_id` | `print_extruder_variant` | `print_options_with_variant` (44 keys) | — |
| machine | `printer_extruder_id` | `printer_extruder_variant` | `printer_options_with_variant_1` (28) | `printer_options_with_variant_2` (16) |
| filament | — | `filament_extruder_variant` | `filament_options_with_variant` (49) | — |

The sets are defined at `PrintConfig.cpp:9202,9249,9317,9351`. They include `outer_wall_speed`, `filament_flow_ratio`, `retraction_length` and `machine_max_acceleration_*` — the settings most often tuned by hand.

If the parent vector's length does not match the expected `variant_index.size() * stride`, Orca takes the child's value verbatim.

### 2.4 Root of the chain

A profile with no `inherits` is applied on top of the engine's built-in defaults from `PrintConfig.cpp`. There are **616** of them; a fully expanded system profile holds **623** keys versus 114 in the source file.

The defaults are extracted from Orca itself: `OrcaSlicer --export-settings out.json` with no other arguments. Parsing `PrintConfig.cpp` (12,807 lines, defaults expressed through macros and constants) is not required.

### 2.5 Profile sources and precedence

`PresetBundle.cpp:5213-5215` — when resolving a `sub_path`, `<datadir>/system/` is checked first, then the resources directory:

1. `<datadir>/system/<Vendor>.json` + `<datadir>/system/<Vendor>/{machine,process,filament}/` — updatable vendors, these **shadow the bundle**;
2. `<resources>/profiles/<Vendor>.json` plus the matching directory — 66 vendors, 12,006 JSON files, 77 MB;
3. `<datadir>/user/<uid>/{machine,process,filament}/*.json` plus paired `.info` files.

On macOS: `datadir` is `~/Library/Application Support/OrcaSlicer`, `resources` is `/Applications/OrcaSlicer.app/Contents/Resources`.

A vendor JSON holds the lists `machine_model_list`, `machine_list`, `process_list`, `filament_list`; each item is `{name, sub_path}`. That is a ready-made name-to-file index.

Names are case-sensitive. The local library contains both `SOVOL SV08 0.4 nozzle` (vendor SovolStock, from `datadir/system`) and `Sovol SV08 0.4 nozzle` (vendor Sovol, from the bundle) — two distinct profiles, and the user profile `Sovol SV08 - Stealthchanger` inherits the former.

### 2.6 Write format

`Preset::save` (`Preset.cpp:671`), `ConfigBase::save_to_json` (`Config.cpp:1516`), `Preset::save_info` (`Preset.cpp:623`):

- when a parent exists, only the delta is saved: `config.diff(*parent_config)` — the difference against the **expanded** parent;
- the `*_extruder_id` and `*_extruder_variant` keys are always appended to the delta, whether or not they differ;
- for nullable vectors in the variant sets, `set_with_nil(src, parent, stride)` applies: elements equal to the parent's are written as the literal `nil`;
- JSON keys are sorted alphabetically (nlohmann::json stores objects in a `std::map`), and the file ends with a newline;
- indentation depends on the version: files written by the installed Orca 2.4.2 use four spaces, while master (2.5.0-dev) calls `j.dump(1, '\t')`, i.e. a tab. The writer therefore does not hard-code indentation: when overwriting it preserves the file's existing style, and when creating a file it adopts the prevailing style of the target directory, defaulting to four spaces;
- the paired `.info` file is INI-formatted: `sync_info`, `user_id`, `setting_id`, `base_id`, `updated_time`;
- deleting a profile whose `setting_id` is non-empty must not remove the `.info` file — it is marked `sync_info = delete` instead, otherwise cloud sync restores the profile.

### 2.7 Why Orca's own code is not reused

Three options were evaluated and rejected:

1. **Linking against the installed application.** The bundle contains zero `.dylib` files; the slicer is a single statically linked `MH_EXECUTE` of 249 MB. `dlopen` on an executable does not work on macOS.
2. **Building `libslic3r` from source.** `target_link_libraries(libslic3r)` pulls in OpenCV, OCCT, OpenVDB, CGAL, TBB, Boost, Draco, mcut, libigl, Qhull and OpenSSL; `deps/` lists 30+ packages. Hours of build time and several GB for roughly 2,000 lines of inheritance logic.
3. **Extracting `Preset.cpp` + `Config.cpp` + `PrintConfig.cpp` into a small target.** `PrintConfig.cpp` includes `ClipperUtils.hpp`, and `Config.hpp` includes `Point.hpp`; the dependency immediately drags in the geometry core.

Beyond cost: the C++ merge is destructive — `update_diff_values_to_child_config` overwrites a value without retaining what was there. Orca has no key provenance at all, so it would have to be built on top regardless.

Two things are reused instead: the engine defaults via `--export-settings`, and a line-by-line port of the key functions with source references in comments.

### 2.8 The CLI is not an oracle for inheritance — verified

This spec originally assumed `--export-settings` could expand a profile and serve as ground truth. **It cannot.** Three approaches were tried against the installed 2.4.2:

1. `--load-settings <profile>` returns the engine defaults plus the keys present in the given files, and never walks `inherits`. Proof: `extruder_clearance_radius` is defined only in the parent `fdm_machine_common`; the engine returned its default `40`, not the parent's `65`.
2. Selecting presets through `OrcaSlicer.conf` does not activate them — the export is still the bare defaults.
3. Passing the whole chain as a file list is rejected: `duplicate machine config file`.

Additionally, the CLI needs a machine *and* a process profile together; either alone is refused.

What Orca does leave behind is evidence of its own expansion. When it saves a user profile it stores the minimal delta against the fully expanded parent (`Preset::save`), so every profile Orca has written is a recorded answer. Recomputing that delta and comparing against the file reproduces the engine's expansion indirectly, on real data. That is the verification this project uses (§7, level 3).

### 2.9 Keys are filtered by profile type

`Preset::remove_invalid_keys` (`Preset.cpp:1766`) drops keys that do not belong to the profile's type at load time. The allowed sets come from `s_Preset_print_options`, `s_Preset_filament_options`, `s_Preset_printer_options` + `s_Preset_machine_limits_options` + `m_extruder_option_keys` (`Preset.cpp:1005, 1326, 1391, 1406`; `PrintConfig.cpp:8137`) — 356 keys for process, 160 for machine, 129 for filament in 2.4.2.

This is not theoretical: Sovol's `fdm_machine_common` sets `extruder_clearance_radius`, a process key inside a machine profile. The engine ignores it, so reporting it as effective would be wrong.

### 2.10 Vector length follows the extruder count

`extend_default_config_length` (`Preset.cpp:231`) sizes variant vectors by the profile's extruder count: `len(nozzle_diameter)` for a machine, or the explicit `*_extruder_variant` list when present; stride-2 sets get twice that.

A toolchanger child inheriting from a single-extruder parent is the case where this matters — without padding the parent, the second extruder's values are lost. Stride-2 machine limits are excluded from padding: real profiles store a single value there even on multi-extruder machines, and the deltas Orca writes confirm it.

## 3. Architecture

Five layers, each independently testable.

### 3.1 `sources` — locating the roots

Finds `datadir` and `resources`, verifies they exist, determines the active `user/<uid>`, and reads `OrcaSlicer.conf` (currently selected presets, installed printer models). Paths can be overridden through the `ORCA_DATADIR` and `ORCA_RESOURCES` environment variables — the same mechanism tests use to substitute fixtures.

Returns the roots ordered by precedence per §2.5.

### 3.2 `index` — the name map

Builds `(type, name) → entry` from the vendor JSONs of every root plus a scan of the user directories. An entry holds the file path, vendor, source (`bundle` / `datadir-system` / `user`) and, once the file is lazily read, `inherits`, `instantiation` and `setting_id`.

Reading the vendor JSONs of all 66 vendors takes 0.02 s; a full parse of all 12,006 files takes 0.9 s. No database is needed: the name index is built at startup and profile bodies are read on demand with an in-memory cache.

A reverse index — "profile → who inherits from it" — backs `find_children`.

### 3.3 `resolver` — expanding the chain

The only layer with non-trivial logic. A port of §2.2–2.4 semantics:

- walk `inherits` upward to the root, with cycle detection and a depth limit;
- resolve names by exact match → `renamed_from` → `Generic` fallback, recording in diagnostics which path succeeded;
- merge top-down: copy of the expanded parent, then the child's delta; for variant keys, match through the variant lists with stride 1 or 2;
- fill the root from the engine-defaults snapshot.

### 3.4 `writer` — writing

The resolver in reverse, implementing §2.6: compute the delta against the expanded parent, apply `nil` handling to vectors, always include `*_extruder_id` / `*_extruder_variant`, write JSON with the right indentation and alphabetical key order, and update the paired `.info`.

Write access is unrestricted: all three roots including `system/` are available, and there is no lock against a running application. A backup copy is made next to the file before every write (`<name>.bak-<timestamp>`); this is a parameter and can be turned off.

A known limitation that cannot be addressed on the MCP side: OrcaSlicer reads profiles at startup and rewrites them at exit, so edits made while the application is running will be overwritten by it.

### 3.5 `server` — MCP

A thin layer over the other four: tool descriptions, argument validation, response serialisation, and output size limits.

## 4. Data model

The resolver returns a structure rather than a plain value map:

```
ResolvedProfile
  name, type, vendor, source, file
  chain: [ChainLink]         # from the profile to the root
  values: { key -> ResolvedValue }
  diagnostics: [Diagnostic]

ChainLink
  name, vendor, source, file
  instantiation: bool        # false = abstract template
  resolution: exact | renamed_from | generic_fallback
  keys_defined: int

ResolvedValue
  value                      # effective value
  origin                     # name of the link that set it
  origin_file
  overridden: [ {link, value} ]   # what it replaced, top-down
  is_default: bool           # value came from the engine defaults

Diagnostic
  severity: error | warning | info
  code                       # missing_parent | cycle | generic_fallback |
                             # unknown_key | redundant_delta | name_collision
  message, link?, key?
```

`overridden` is what Orca itself does not have, and the reason for writing our own resolver.

## 5. MCP tools

**Orientation**

- `get_setup` — discovered roots, Orca version, vendor list, currently selected presets from `OrcaSlicer.conf`.
- `list_profiles(type, query?, vendor?, source?, compatible_with?, include_abstract=false)` — filtered search.

**Reading and provenance**

- `get_profile(type, name, mode, keys?, group?, include_defaults=false)` — modes `raw` / `resolved` / `traced`.
- `get_chain(type, name)` — the chain with each link's resolution method and diagnostics.
- `explain_key(type, name, key)` — effective value, originating link, overridden values up the chain, engine default.
- `find_children(type, name)` — which profiles inherit from this one. A mandatory check before editing anything shared.

**Comparison**

- `diff_profiles(a, b, mode)` — by deltas or by effective values.
- `compare_with_upstream(type, name)` — fetches the profile from the OrcaSlicer repository on GitHub and compares. Disk cache; network access only on a miss.

**Diagnostics**

- `validate(scope)` — broken `inherits`, cycles, keys unknown to the engine, deltas identical to the parent, duplicate names and case collisions (`SOVOL SV08` versus `Sovol SV08` already exists locally).

**Writing**

- `set_values(type, name, values)` — edit with delta recomputation, `nil` handling for vectors, and `.info` update.
- `create_profile(type, name, inherits, values)`, `rename_profile`, `delete_profile`, `normalize_profile`.

**Verification**

- `check_deltas(scope)` — recompute the delta of every profile in scope and compare it with what Orca stored (§2.8). Mismatches mean the resolver disagrees with the engine about a parent; keys already equal to the parent are reported apart as harmless.

### 5.1 Output size

A fully expanded profile is 623 keys, about 25 KB of JSON; with provenance it is three times that. Dumping it on every request is pointless. Therefore:

- by default `get_profile` returns only keys explicitly set somewhere in the chain; engine defaults are opt-in through `include_defaults`;
- filters `keys` (list or substring) and `group` are available — the group comes from the `category` field in the `PrintConfig.cpp` option definitions (`def->category = L("Quality")`) and is captured in the engine snapshot. Not every option has a category: of 934 definitions, 319 do (Quality 97, Strength 61, Support 61, Speed 44, the rest fewer). Keys without a category cannot be found through `group` and are reachable through `keys`; the response states this rather than hiding it;
- a full dump is available but must be requested explicitly.

## 6. Engine snapshot

A generated artefact shipped inside the package:

- **defaults** — 616 keys, captured via `OrcaSlicer --export-settings`;
- **variant key sets** — four sets extracted from `PrintConfig.cpp` by regex (§2.3);
- **categories and option types** — from the same source;
- **the Orca version** the snapshot belongs to.

The regeneration script lives in the repository. After an Orca upgrade it is re-run and the differential tests are executed; any divergence surfaces immediately.

## 7. Testing

Development follows TDD: the test is written before the implementation.

**Level 1 — synthetic fixtures.** A miniature profile library under `tests/fixtures`, substituted through `ORCA_DATADIR` / `ORCA_RESOURCES`. One test per edge case: a three-link chain, cross-vendor inheritance, the `Generic` fallback, `renamed_from`, a cycle, a missing parent, stride-1 and stride-2 vectors, and a parent vector whose length does not match.

**Level 2 — snapshot of the real library.** The working profiles: `SOVOL SV08 0.4 nozzle` from `datadir/system` shadowing the bundle's `Sovol SV08 0.4 nozzle`, a toolchanger profile with `nozzle_diameter: ["0.4","0.4"]`, and the user profile `0.16mm Optimal` inheriting from another vendor. A regression set.

**Level 3 — against the deltas Orca wrote.** For every profile in scope, the delta is recomputed with our resolver and compared with what the file stores (§2.8). A mismatch means our expansion of the parent differs from the engine's. Keys stored despite already equalling the parent are counted separately: they mean the file predates a change to its parent, not that the resolver is wrong.

This needs no running Orca, only its files, and covers the whole library at once. It is what caught the toolchanger vector defect.

**Level 4 — write round-trip.** Read → write unchanged → the file is byte-identical. Write a value → read it back → get exactly that value. Level 3 covers acceptance implicitly: a written delta that the recomputation reproduces is one Orca would have written itself.

## 8. Technical decisions

- Python 3.11+, dependencies managed with `uv`; stdio transport, matching the user's other MCP servers.
- MCP SDK 2.0: the high-level class is `mcp.server.MCPServer` with the `@server.tool()` decorator and `server.run(transport="stdio")`. `FastMCP` from SDK 1.x does not exist in this version.
- Location: `~/job/orca-profiles-mcp`, git from the first commit, local only.
- Platform: macOS. The `datadir` and `resources` paths live in `sources`, so supporting another OS reduces to adding path variants.

## 9. Out of scope

- Reading configuration from `.3mf` projects or from sliced G-code.
- Slicing, G-code generation, any geometry work.
- Cloud sync with Bambu/Orca (the `setting_id` / `sync_info` fields are preserved correctly, but nothing is exchanged with a server).
- A graphical interface.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Resolver diverges from the engine after an Orca upgrade | Level 3 delta verification plus one-command snapshot regeneration |
| Edits made while Orca is running get overwritten | Documented; a backup copy is made before every write |
| A bug in the `nil` vector logic breaks per-element inheritance | Dedicated stride-1 and stride-2 tests, round-trip, verification through the CLI |
| Editing a system profile affects dozens of descendants | `find_children` as a mandatory step; `set_values` warns when writing outside the user directory |
