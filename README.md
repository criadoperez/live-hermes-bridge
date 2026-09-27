# live-hermes-bridge

<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Copyright (C) 2026 Alejandro Criado-Perez <alejandro@criadoperez.com> -->

OpenAI GPT-Live voice frontend for Hermes agents. GPT-Live (`gpt-live-1`)
handles the full-duplex spoken conversation; a Hermes agent is the brain:
reasoning, tools, memory, skills.

One bridge serves many agents: pick the backend per call in `backends.yaml`.

## How it works

- Browser holds mic/speaker over WebRTC. Audio flows browser <-> OpenAI
  Live directly; the bridge never sees audio.
- The bridge creates the Live session with **client delegation**, then
  attaches a trusted sideband WebSocket
  (`wss://api.openai.com/v1/live/sessions/{id}/attach`).
- On `session.delegation.created` the bridge keeps the transcript it
  collected from `session.*.transcript.delta` events, calls the selected
  Hermes backend (`POST {base_url}/responses`, named conversation), and
  returns the result as `session.commentary.append` with the same
  `delegation_id` for Live to speak. Progress goes as
  `session.thinking.append`.
- The Live delegation event carries an id only, no task text; the bridge
  owns the conversation snapshot.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill in OPENAI_API_KEY + backend bearers
cp backends.yaml.example backends.yaml
export $(grep -v '^#' .env | xargs)   # or use your preferred env loader
python3 -m live_hermes_bridge.server
```

Open http://127.0.0.1:8000, choose a backend, Start conversation, allow
the mic. Serve over HTTPS or localhost so the browser grants mic access.

## Configuration

`backends.yaml`: one entry per Hermes agent (`name`, `base_url`, `model`,
`key_env`, `conversation`, `live_instructions`, `backend_preamble`).
Bearer keys stay in the environment (`key_env`), never in the file.
Give each backend its own variable, e.g.:

```yaml
backends:
  - name: home-agent
    base_url: http://agent-one:8642/v1
    model: hermes-agent
    key_env: HERMES_API_KEY_ONE
    conversation: voice-home-agent
  - name: office-agent
    base_url: http://agent-two:8642/v1
    model: hermes-agent
    key_env: HERMES_API_KEY_TWO
    conversation: voice-office-agent
```

The web page lists whatever the server reports on `/api/backends`.

## Status

Prototype. Text turns first; approvals and confirmations are enforced by
the Hermes backend's own policy. The bearer for a Hermes API equals
remote execution as that host's agent user over a trusted LAN only.

## License

GNU Affero General Public License v3.0 or later. See LICENSE.
