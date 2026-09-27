# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
"""OpenAI Live session management: create a WebRTC session, attach sideband."""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
from websockets.exceptions import ConnectionClosed

LIVE_BASE = "https://api.openai.com/v1/live"
SIDEBAND_URL = "wss://api.openai.com/v1/live/sessions/{session_id}/attach"


async def create_live_session(
    openai_key: str,
    sdp_offer: str,
    instructions: str,
    voice: str = "marin",
) -> tuple[str, str]:
    """Create a GPT-Live session with client delegation.

    Returns (live_session_id, sdp_answer). The browser applies the answer
    as its remote description and waits for ``session.started``.
    """
    body = {
        "session": {
            "model": "gpt-live-1",
            "instructions": instructions,
            "audio": {"output": {"voice": voice}},
            "delegation": {"type": "client"},
        },
        "transport": {"type": "webrtc", "sdp": sdp_offer},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{LIVE_BASE}/sessions",
            headers={"Authorization": f"Bearer {openai_key}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    return data["session"]["id"], data["transport"]["sdp"]


def _connect(url: str, openai_key: str):
    """Open the sideband websocket, tolerating old/new ``websockets`` APIs."""
    import websockets

    headers = {"Authorization": f"Bearer {openai_key}"}
    try:
        return websockets.connect(url, additional_headers=headers)
    except TypeError:
        return websockets.connect(url, extra_headers=headers)


class Sideband:
    """Trusted backend connection attached to one Live session.

    The primary (browser WebRTC) connection carries audio. This sideband
    receives transcript and delegation events and sends appends back.
    Never send ``session.start`` or audio frames on this socket.
    """

    def __init__(self, openai_key: str, live_session_id: str, on_event) -> None:
        self.openai_key = openai_key
        self.live_session_id = live_session_id
        self.on_event = on_event
        self.outbox: asyncio.Queue[dict] = asyncio.Queue()

    async def append(
        self, kind: str, delegation_id: str | None, content: str
    ) -> None:
        """Queue a session.*.append event (kind: thinking|commentary|instructions)."""
        await self.outbox.put(
            {
                "type": f"session.{kind}.append",
                "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                "delegation_id": delegation_id,
                "content": content,
            }
        )

    async def run(self) -> None:
        url = SIDEBAND_URL.format(session_id=self.live_session_id)
        try:
            async with _connect(url, self.openai_key) as ws:
                sender = asyncio.create_task(self._sender(ws))
                try:
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        await self.on_event(self, event)
                except ConnectionClosed:
                    # Expected at hangup: OpenAI closes the sideband when the
                    # primary connection ends (reason connection_lost or
                    # remote_hangup). The Live session ends on OpenAI's side;
                    # there is no extra close call for our bridge to make.
                    pass
                finally:
                    sender.cancel()
        except ConnectionClosed:
            pass

    async def _sender(self, ws) -> None:
        while True:
            msg = await self.outbox.get()
            await ws.send(json.dumps(msg))
