"""Reading profiles from the OrcaSlicer repository on GitHub, with a disk cache."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

RAW_BASE = "https://raw.githubusercontent.com/SoftFever/OrcaSlicer"
LIST_KEY = {
    "machine": "machine_list",
    "process": "process_list",
    "filament": "filament_list",
}


class HttpTransport:
    def get_json(self, url: str) -> dict | None:
        try:
            response = httpx.get(url, timeout=30, follow_redirects=True)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return None


@dataclass
class UpstreamClient:
    cache_dir: Path
    ref: str = "main"
    transport: object = field(default_factory=HttpTransport)

    def _url(self, relative: str) -> str:
        return f"{RAW_BASE}/{self.ref}/resources/profiles/{relative}"

    def _cache_path(self, relative: str) -> Path:
        return self.cache_dir / self.ref / f"{quote(relative, safe='')}.json"

    def _get(self, relative: str) -> dict | None:
        cache_path = self._cache_path(relative)
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cache_path.unlink(missing_ok=True)
        data = self.transport.get_json(self._url(relative))
        if data is None:
            return None
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def fetch_vendor(self, vendor: str) -> dict | None:
        return self._get(f"{vendor}.json")

    def fetch_profile(self, vendor: str, sub_path: str) -> dict | None:
        return self._get(f"{vendor}/{sub_path}")

    def find_sub_path(self, vendor: str, ptype: str, name: str) -> str | None:
        data = self.fetch_vendor(vendor)
        if not data:
            return None
        for item in data.get(LIST_KEY[ptype]) or []:
            if item.get("name") == name:
                return item.get("sub_path")
        return None
