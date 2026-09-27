# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com>
"""HTTP bridge: browser WebRTC signalling + Hermes backend fan-out.

Flow per call:
  browser --SDP offer--> POST /api/session --> OpenAI Live (client delegation)
  browser <--SDP answer-- server, then audio flows browser<->OpenAI directly
  server --sideband--> OpenAI: transcripts + delegation.created events
  server --/v1/responses--> Hermes backend (the brain), result appended
  back to Live as session.commentary.append for the voice to speak.
"""
from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path

from .config import Backend, Settings, load_settings
from .hermes import ask_hermes
from .live_api import Sideband, create_live_session

STATIC_DIR = Path(__file__).parent / "static"

# Keep each append well under the 500-token Live append limit.
MAX_APPEND_CHARS = 1500
TRANSCRIPT_TAIL_CHARS = 4000

app = FastAPI(title="live-hermes-bridge")

# Local demo only: the browser page and this server run on the same machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

settings: Settings | None = None
# app_session_id -> {"live_session_id", "backend", "user_buf", "asst_buf", "log", "sideband"}
SESSIONS: dict[str, dict] = {}


def get_settings() -> Settings:
    global settings
    if settings is None:
        settings = load_settings()
    return settings


def _snapshot(session: dict) -> str:
    tail = (session["user_buf"] + session["asst_buf"])[-TRANSCRIPT_TAIL_CHARS:]
    return tail


async def _handle_delegation(session: dict, delegation_id: str) -> None:
    """Run one delegated turn against Hermes, send the result back to Live."""
    st = get_settings()
    backend: Backend = session["backend"]
    sideband: Sideband = session["sideband"]
    await sideband.append("thinking", delegation_id, "Checking with the agent now.")
    snapshot = _snapshot(session)
    prompt = (
        f"{backend.backend_preamble}\n\n"
        f"Conversation transcript so far (latest at the end):\n{snapshot}\n\n"
        "Respond with what the voice should say aloud: concise facts and "
        "status, a few sentences at most."
    )
    try:
        bearer = st.backend_key(backend)
        answer = await ask_hermes(backend, bearer, prompt)
    except Exception as exc:  # never leave a delegation hanging silently
        answer = ""
        session["log"].append(f"backend error: {exc}")
    answer = (answer or "I could not reach the agent just now.").strip()
    session["log"].append(f"delegation {delegation_id} -> {len(answer)} chars")
    await sideband.append("commentary", delegation_id, answer[:MAX_APPEND_CHARS])


async def _on_live_event(sideband: Sideband, event: dict) -> None:
    etype = event.get("type", "")
    session = next(
        (s for s in SESSIONS.values() if s["sideband"] is sideband), None
    )
    if session is None:
        return
    if etype == "session.input_transcript.delta":
        session["user_buf"] += event.get("delta", "")
    elif etype == "session.output_transcript.delta":
        session["asst_buf"] += event.get("delta", "")
    elif etype == "session.delegation.created":
        delegation = event.get("delegation") or {}
        if delegation.get("target") == "client" and delegation.get("id"):
            asyncio.create_task(
                _handle_delegation(session, delegation["id"])
            )
    elif etype == "error":
        session["log"].append(f"live error: {event.get('error')}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "live-hermes-bridge"}


@app.get("/api/backends")
async def list_backends() -> dict:
    st = get_settings()
    return {"backends": sorted(st.backends)}


@app.post("/api/session")
async def start_session(payload: dict) -> dict:
    st = get_settings()
    backend_name = payload.get("backend", "")
    sdp_offer = payload.get("sdp", "")
    if not sdp_offer:
        raise HTTPException(status_code=400, detail="missing SDP offer")
    try:
        backend = st.backend(backend_name)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown backend")
    try:
        live_id, sdp_answer = await create_live_session(
            st.openai_api_key, sdp_offer, backend.live_instructions
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"live session failed: {exc}")
    app_id = uuid.uuid4().hex[:16]
    session = {
        "app_session_id": app_id,
        "live_session_id": live_id,
        "backend": backend,
        "created_at": time.time(),
        "user_buf": "",
        "asst_buf": "",
        "log": [],
    }
    sideband = Sideband(st.openai_api_key, live_id, _on_live_event)
    session["sideband"] = sideband
    SESSIONS[app_id] = session
    asyncio.create_task(sideband.run())
    return {
        "app_session_id": app_id,
        "live_session_id": live_id,
        "sdp_answer": sdp_answer,
    }


@app.get("/api/sessions/{app_id}")
async def session_state(app_id: str) -> dict:
    session = SESSIONS.get(app_id)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session")
    return {
        "app_session_id": app_id,
        "live_session_id": session["live_session_id"],
        "backend": session["backend"].name,
        "user_transcript": session["user_buf"][-TRANSCRIPT_TAIL_CHARS:],
        "assistant_transcript": session["asst_buf"][-TRANSCRIPT_TAIL_CHARS:],
        "log": session["log"][-20:],
    }


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "call.html")


def main() -> None:
    import uvicorn

    st = get_settings()
    uvicorn.run(app, host=st.host, port=st.port)


if __name__ == "__main__":
    main()
