"""Application layer: the operations the MCP server exposes.

Kept separate from server.py so it can be tested without the MCP transport.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .index import ProfileIndex
from .models import META_KEYS, ResolvedValue
from .resolver import Resolver
from .snapshot import EngineSnapshot
from .sources import PROFILE_TYPES, discover
from .validate import validate_library
from .writer import Writer

ORCA_RUNNING_NOTE = (
    "if OrcaSlicer is running right now, it will rewrite profiles from its "
    "in-memory state on exit and this change will be lost"
)


def _value_payload(rv: ResolvedValue, traced: bool) -> Any:
    if not traced:
        return rv.value
    payload = {
        "value": rv.value,
        "origin": rv.origin,
        "origin_file": rv.origin_file,
        "is_default": rv.is_default,
        "overridden": [{"link": o.link, "value": o.value} for o in rv.overridden],
    }
    # only interesting when the elements do not all come from the same link
    if rv.element_origins and len(set(rv.element_origins)) > 1:
        payload["element_origins"] = rv.element_origins
    return payload


@dataclass
class Service:
    index: ProfileIndex
    resolver: Resolver
    snapshot: EngineSnapshot
    writer: Writer
    setup: Any
    upstream: Any = None

    # --- orientation ---

    def _ambiguous_user_dir_note(self) -> str | None:
        """Say so when more than one profile tree exists.

        Orca writes into user/<account-id> while signed in and user/default
        while signed out, and its config records neither. Guessing silently
        means profiles can land where the running application never looks.
        """
        dirs = getattr(self.setup, "user_dirs", ()) or ()
        if len(dirs) < 2:
            return None
        others = ", ".join(d.name for d in dirs if d != self.setup.user_dir)
        return (
            f"several user profile directories exist; using "
            f"{self.setup.user_dir.name!r} (chosen as the most recently written). "
            f"Also present: {others}. Orca uses 'default' when signed out and "
            f"the account directory when signed in — set ORCA_USER_DIR to pick "
            f"explicitly if profiles do not appear in the application"
        )

    def get_setup(self) -> dict:
        return {
            "datadir": str(self.setup.datadir),
            "resources": str(self.setup.resources),
            "app_version": self.setup.app_version,
            "engine_snapshot_version": self.snapshot.orca_version,
            "user_id": self.setup.user_id,
            "user_dir": str(self.setup.user_dir) if self.setup.user_dir else None,
            "user_dirs": [str(d) for d in (getattr(self.setup, "user_dirs", ()) or ())],
            "user_dir_warning": self._ambiguous_user_dir_note(),
            "vendor_roots": [
                {"source": r.source, "path": str(r.path)}
                for r in self.setup.vendor_roots
            ],
            "vendors": sorted({e.vendor for e in self.index.all() if e.vendor}),
            "counts": {t: len(self.index.all(t)) for t in PROFILE_TYPES},
            "selected_presets": self.setup.selected,
        }

    def list_profiles(
        self,
        type: str | None = None,
        query: str | None = None,
        vendor: str | None = None,
        source: str | None = None,
        compatible_with: str | None = None,
        include_abstract: bool = False,
        limit: int = 200,
    ) -> dict:
        found = []
        for entry in self.index.all(type):
            if entry.type == "machine_model":
                continue
            if vendor and entry.vendor != vendor:
                continue
            if source and entry.source != source:
                continue
            if query and query.lower() not in entry.name.lower():
                continue
            raw = self.index.load_raw(entry)
            abstract = raw.get("instantiation", "true") == "false"
            if abstract and not include_abstract:
                continue
            if compatible_with:
                compatible = raw.get("compatible_printers") or []
                if compatible and compatible_with not in compatible:
                    continue
            found.append(
                {
                    "type": entry.type,
                    "name": entry.name,
                    "vendor": entry.vendor,
                    "source": entry.source,
                    "inherits": raw.get("inherits"),
                    "abstract": abstract,
                    "file": str(entry.file),
                }
            )
        found.sort(key=lambda p: (p["type"], p["name"]))
        return {
            "total": len(found),
            "returned": min(len(found), limit),
            "profiles": found[:limit],
        }

    # --- reading ---

    def get_profile(
        self,
        type: str,
        name: str,
        mode: str = "resolved",
        keys: str | list[str] | None = None,
        group: str | None = None,
        include_defaults: bool = False,
        limit: int = 400,
    ) -> dict:
        if mode not in ("raw", "resolved", "traced"):
            raise ValueError(
                f"unknown mode {mode!r}; expected raw, resolved or traced"
            )
        entry = self.index.get(type, name)
        if entry is None:
            raise KeyError(f"profile not found: {type}/{name}")

        if mode == "raw":
            return {
                "name": name,
                "type": type,
                "mode": "raw",
                "file": str(entry.file),
                "values": self.index.load_raw(entry),
            }

        resolved = self.resolver.resolve(type, name)
        traced = mode == "traced"

        selected: dict[str, ResolvedValue] = {}
        omitted_defaults = 0
        for key, rv in resolved.values.items():
            if rv.is_default and not include_defaults:
                omitted_defaults += 1
                continue
            if group and self.snapshot.categories.get(key) != group:
                continue
            if keys:
                if isinstance(keys, str):
                    if keys.lower() not in key.lower():
                        continue
                elif key not in keys:
                    continue
            selected[key] = rv

        ordered = dict(sorted(selected.items())[:limit])
        payload = {
            "name": name,
            "type": type,
            "mode": mode,
            "vendor": resolved.vendor,
            "source": resolved.source,
            "file": resolved.file,
            "chain": [link.name for link in resolved.chain],
            "total_keys": len(selected),
            "returned_keys": len(ordered),
            "omitted_defaults": omitted_defaults,
            "usable": resolved.usable,
            "values": {k: _value_payload(rv, traced) for k, rv in ordered.items()},
            "diagnostics": [
                {"severity": d.severity, "code": d.code, "message": d.message}
                for d in resolved.diagnostics
            ],
        }
        if group:
            uncategorised = sum(
                1 for k in resolved.values if k not in self.snapshot.categories
            )
            payload["note"] = (
                "the group filter only covers keys that carry a category in the "
                f"engine; {uncategorised} keys of this profile have none"
            )
        return payload

    def get_chain(self, type: str, name: str) -> dict:
        resolved = self.resolver.resolve(type, name)
        return {
            "name": name,
            "type": type,
            "usable": resolved.usable,
            "chain": [
                {
                    "name": link.name,
                    "vendor": link.vendor,
                    "source": link.source,
                    "file": link.file,
                    "abstract": not link.instantiation,
                    "resolution": link.resolution,
                    "keys_defined": link.keys_defined,
                }
                for link in resolved.chain
            ],
            "diagnostics": [
                {
                    "severity": d.severity,
                    "code": d.code,
                    "message": d.message,
                    "link": d.link,
                }
                for d in resolved.diagnostics
            ],
        }

    def explain_key(self, type: str, name: str, key: str) -> dict:
        resolved = self.resolver.resolve(type, name)
        rv = resolved.values.get(key)
        if rv is None:
            raise KeyError(f"key {key!r} is not present in profile {name!r}")
        return {
            "name": name,
            "type": type,
            "key": key,
            "value": rv.value,
            "origin": rv.origin,
            "origin_file": rv.origin_file,
            "is_default": rv.is_default,
            "element_origins": rv.element_origins,
            "overridden": [{"link": o.link, "value": o.value} for o in rv.overridden],
            "engine_default": self.snapshot.defaults.get(key),
            "category": self.snapshot.categories.get(key),
            "chain": [link.name for link in resolved.chain],
        }

    def find_children(self, type: str, name: str) -> dict:
        children = self.index.children_of(type, name)
        return {
            "name": name,
            "type": type,
            "count": len(children),
            "children": [
                {
                    "name": c.name,
                    "vendor": c.vendor,
                    "source": c.source,
                    "file": str(c.file),
                }
                for c in children
            ],
        }

    def diff_profiles(self, type: str, a: str, b: str, mode: str = "resolved") -> dict:
        if mode not in ("raw", "resolved"):
            raise ValueError(f"unknown mode {mode!r}; expected raw or resolved")

        def values_of(name: str) -> dict[str, Any]:
            if mode == "raw":
                entry = self.index.get(type, name)
                if entry is None:
                    raise KeyError(f"profile not found: {type}/{name}")
                # `inherits` is kept: two profiles with identical bodies but
                # different parents are not the same profile.
                keep = META_KEYS - {"inherits"}
                return {
                    k: v
                    for k, v in self.index.load_raw(entry).items()
                    if k not in keep
                }
            return {
                k: rv.value for k, rv in self.resolver.resolve(type, name).values.items()
            }

        values_a, values_b = values_of(a), values_of(b)
        differences = {}
        for key in sorted(set(values_a) | set(values_b)):
            va, vb = values_a.get(key), values_b.get(key)
            if va != vb:
                differences[key] = {"a": va, "b": vb}
        return {"a": a, "b": b, "type": type, "mode": mode, "differences": differences}

    def compare_with_upstream(self, type: str, name: str, ref: str = "main") -> dict:
        if type not in PROFILE_TYPES:
            raise ValueError(
                f"cannot compare {type!r} against upstream; expected one of "
                f"{', '.join(PROFILE_TYPES)}"
            )
        entry = self.index.get(type, name)
        if entry is None:
            raise KeyError(f"profile not found: {type}/{name}")
        # The client carries its ref, so a cached one must not serve another:
        # it would fetch the first ref's files and label them with the second.
        if self.upstream is None or getattr(self.upstream, "ref", ref) != ref:
            from .upstream import UpstreamClient

            self.upstream = UpstreamClient(
                cache_dir=self.setup.datadir / ".orca-profiles-mcp-cache", ref=ref
            )

        vendor = entry.vendor
        local_raw = {
            k: v for k, v in self.index.load_raw(entry).items() if k not in META_KEYS
        }
        sub_path = self.upstream.find_sub_path(vendor, type, name) if vendor else None
        remote_raw = (
            self.upstream.fetch_profile(vendor, sub_path)
            if vendor and sub_path
            else None
        )
        if remote_raw is None:
            return {
                "name": name,
                "type": type,
                "vendor": vendor,
                "found_upstream": False,
                "note": "no such profile in the OrcaSlicer repository for this ref",
                "differences": {},
            }

        remote_values = {k: v for k, v in remote_raw.items() if k not in META_KEYS}
        differences = {}
        for key in sorted(set(local_raw) | set(remote_values)):
            local_value, remote_value = local_raw.get(key), remote_values.get(key)
            if local_value != remote_value:
                differences[key] = {"local": local_value, "upstream": remote_value}
        return {
            "name": name,
            "type": type,
            "vendor": vendor,
            "found_upstream": True,
            "ref": ref,
            "differences": differences,
        }

    def check_deltas(self, scope: str = "user") -> dict:
        from .delta_check import check_library_deltas

        return check_library_deltas(self.index, self.resolver, self.snapshot, scope)

    def validate(
        self,
        scope: str = "user",
        code: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Check the library and summarise; the full list is opt-in via limit.

        A user library easily produces hundreds of diagnostics, most of them
        repetitions of a handful of causes. The counts say what is wrong, and
        `code`/`severity` narrow the list to the part worth reading.
        """
        diagnostics = validate_library(self.index, self.resolver, self.snapshot, scope)
        by_code = Counter(d.code for d in diagnostics)
        by_severity = Counter(d.severity for d in diagnostics)

        selected = [
            d
            for d in diagnostics
            if (code is None or d.code == code)
            and (severity is None or d.severity == severity)
        ]
        # errors first: they are the ones that stop a profile from loading
        rank = {"error": 0, "warning": 1, "info": 2}
        selected.sort(key=lambda d: (rank.get(d.severity, 3), d.code, d.link or ""))

        affected = Counter(d.link for d in selected if d.link)
        return {
            "scope": scope,
            "count": len(diagnostics),
            "matched": len(selected),
            "returned": min(len(selected), limit),
            "by_severity": dict(by_severity),
            "by_code": dict(by_code.most_common()),
            "profiles_affected": len({d.link for d in diagnostics if d.link}),
            "most_affected": [
                {"name": n, "diagnostics": c} for n, c in affected.most_common(5)
            ],
            "filters": {"code": code, "severity": severity, "limit": limit},
            "diagnostics": [
                {
                    "severity": d.severity,
                    "code": d.code,
                    "message": d.message,
                    "link": d.link,
                    "key": d.key,
                }
                for d in selected[:limit]
            ],
        }

    # --- writing ---

    def _report(self, report: dict) -> dict:
        warnings = list(report.get("warnings") or [])
        note = self._ambiguous_user_dir_note()
        if note:
            warnings.append(note)
        return {
            **report,
            "warnings": warnings,
            "orca_running_warning": ORCA_RUNNING_NOTE,
        }

    def set_values(
        self,
        type: str,
        name: str,
        values: dict[str, Any],
        backup: bool = True,
        force: bool = False,
    ) -> dict:
        return self._report(
            self.writer.set_values(type, name, values, backup=backup, force=force)
        )

    def create_profile(
        self, type: str, name: str, inherits: str, values: dict[str, Any]
    ) -> dict:
        return self._report(self.writer.create_profile(type, name, inherits, values))

    def rename_profile(self, type: str, name: str, new_name: str) -> dict:
        return self._report(self.writer.rename_profile(type, name, new_name))

    def delete_profile(self, type: str, name: str, force: bool = False) -> dict:
        return self._report(self.writer.delete_profile(type, name, force=force))

    def normalize_profile(
        self, type: str, name: str, backup: bool = True, force: bool = False
    ) -> dict:
        return self._report(
            self.writer.normalize_profile(type, name, backup=backup, force=force)
        )


def build_service() -> Service:
    setup = discover()
    index = ProfileIndex.build(setup)
    snapshot = EngineSnapshot.load()
    resolver = Resolver(index, snapshot)
    return Service(
        index=index,
        resolver=resolver,
        snapshot=snapshot,
        writer=Writer(index, resolver, snapshot),
        setup=setup,
    )
