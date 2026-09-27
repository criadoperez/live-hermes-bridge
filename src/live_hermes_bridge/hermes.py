# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
"""Calls to a Hermes agent backend over its OpenAI-compatible API."""
from __future__ import annotations

import httpx

from .config import Backend


def extract_text(payload: dict) -> str:
    """Pull the assistant text out of a /v1/responses response body."""
    texts: list[str] = []
    output = payload.get("output") or []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "output_text":
                texts.append(part.get("text", ""))
    if texts:
        return "\n".join(t for t in texts if t).strip()
    # Fallback for chat-completions shaped bodies, should not normally happen.
    try:
        return payload["choices"][0]["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError):
        return ""


async def ask_hermes(
    backend: Backend,
    bearer: str,
    user_text: str,
    timeout_s: float = 180.0,
) -> str:
    """Send one voice turn to the Hermes backend, return speakable text."""
    body = {
        "model": backend.model,
        "conversation": backend.conversation,
        "input": user_text,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(
            f"{backend.base_url}/responses",
            headers={"Authorization": f"Bearer {bearer}"},
            json=body,
        )
        resp.raise_for_status()
        return extract_text(resp.json())
