# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
"""Offline smoke tests: no network, no keys, no OpenAI calls."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

os.environ["OPENAI_API_KEY"] = "sk-test-placeholder"
os.environ["LEONARDO_API_KEY"] = "bearer-test-placeholder"

from live_hermes_bridge.config import load_settings
from live_hermes_bridge.hermes import extract_text
from live_hermes_bridge.live_api import SIDEBAND_URL


def main() -> None:
    # LHB_BACKENDS may point at the user's real file; tests use the example.
    example = Path(__file__).resolve().parent / "backends.yaml.example"
    os.environ["LHB_BACKENDS"] = str(example)
    st = load_settings(example)
    assert "leonardo" in st.backends, "leonardo backend missing"
    b = st.backend("leonardo")
    assert b.base_url == "http://leonardo.home.arpa:8642/v1", b.base_url
    assert b.model == "hermes-leonardo", b.model
    assert st.backend_key(b) == "bearer-test-placeholder"
    try:
        st.backend("does-not-exist")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown backend should raise KeyError")

    responses_body = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello from Leonardo."}],
            },
            {"type": "function_call", "name": "terminal", "call_id": "c1"},
        ]
    }
    assert extract_text(responses_body) == "Hello from Leonardo."
    assert extract_text({}) == ""

    assert "{session_id}" in SIDEBAND_URL
    assert SIDEBAND_URL.startswith("wss://api.openai.com/v1/live/sessions/")

    from fastapi.testclient import TestClient

    import live_hermes_bridge.server as srv

    # Fresh settings from the example file; ignore any cached global.
    srv.settings = None
    client = TestClient(srv.app)
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    r = client.get("/api/backends")
    assert r.json() == {"backends": ["leonardo"]}, r.text
    r = client.post("/api/session", json={"backend": "nope", "sdp": "v=0..."})
    assert r.status_code == 404, r.text
    r = client.post("/api/session", json={"backend": "leonardo"})
    assert r.status_code == 400, r.text

    print("SMOKE_OK: config, extract_text, sideband URL, health, backends, validation")


if __name__ == "__main__":
    main()
