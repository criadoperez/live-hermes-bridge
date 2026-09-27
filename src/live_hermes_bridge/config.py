# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
"""Runtime settings: backends file plus environment secrets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Backend:
    name: str
    base_url: str
    model: str
    key_env: str
    conversation: str
    live_instructions: str = ""
    backend_preamble: str = ""


@dataclass
class Settings:
    openai_api_key: str
    backends: dict[str, Backend] = field(default_factory=dict)
    host: str = "127.0.0.1"
    port: int = 8000

    def backend(self, name: str) -> Backend:
        try:
            return self.backends[name]
        except KeyError:
            raise KeyError(f"unknown backend {name!r}") from None

    def backend_key(self, backend: Backend) -> str:
        key = os.environ.get(backend.key_env, "")
        if not key:
            raise RuntimeError(f"secret {backend.key_env} is not set in the environment")
        return key


def load_settings(backends_path: str | Path | None = None) -> Settings:
    path = Path(backends_path or os.environ.get("LHB_BACKENDS", "backends.yaml"))
    if not path.is_file():
        raise FileNotFoundError(f"backends file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    backends: dict[str, Backend] = {}
    for entry in raw.get("backends", []):
        b = Backend(
            name=entry["name"],
            base_url=entry["base_url"].rstrip("/"),
            model=entry["model"],
            key_env=entry["key_env"],
            conversation=entry.get("conversation", f"voice-{entry['name']}"),
            live_instructions=entry.get("live_instructions", ""),
            backend_preamble=entry.get("backend_preamble", ""),
        )
        backends[b.name] = b
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in the environment")
    return Settings(
        openai_api_key=api_key,
        backends=backends,
        host=os.environ.get("LHB_HOST", "127.0.0.1"),
        port=int(os.environ.get("LHB_PORT", "8000")),
    )
