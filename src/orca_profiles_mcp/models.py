"""Result structures for profile expansion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Bookkeeping keys: not print settings.
META_KEYS = frozenset(
    {
        "name",
        "type",
        "from",
        "inherits",
        "instantiation",
        "version",
        "setting_id",
        "base_id",
        "user_id",
        "description",
        "renamed_from",
        "is_custom_defined",
        "print_settings_id",
        "filament_settings_id",
        "printer_settings_id",
        "filament_id",
    }
)


@dataclass(frozen=True)
class Override:
    link: str
    value: Any


@dataclass
class ResolvedValue:
    value: Any
    origin: str
    origin_file: str
    overridden: list[Override] = field(default_factory=list)
    is_default: bool = False


@dataclass
class ChainLink:
    name: str
    vendor: str
    source: str
    file: str
    instantiation: bool
    resolution: str  # "self" | "exact" | "renamed_from" | "generic_fallback"
    keys_defined: int


@dataclass
class Diagnostic:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str
    link: str | None = None
    key: str | None = None


@dataclass
class ResolvedProfile:
    name: str
    type: str
    vendor: str
    source: str
    file: str
    chain: list[ChainLink] = field(default_factory=list)
    values: dict[str, ResolvedValue] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
