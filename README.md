# RayNeo X3 Pro live AI assistant

A live voice-and-vision assistant for RayNeo X3 Pro AR glasses, built on LiveKit and the
Gemini Live API.

## Architecture

```
┌─────────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  RayNeo X3 Pro      │  WebRTC │  livekit-server  │  WebRTC │  Python agent    │
│  (android/)         │────────▶│  (self-hosted,   │◀────────│  (agent/)        │
│                     │         │   local Docker   │         │                  │
│  publishes mic      │         │   or binary)     │         │  joins the room, │
│  publishes camera   │         │                  │         │  streams A/V to  │
│  subscribes to      │◀────────│                  │────────▶│  Gemini Live     │
│  agent audio        │         └──────────────────┘         └────────┬─────────┘
└─────────────────────┘                                              │
                                                                     │ WebSocket
                                                                     ▼
                                                            ┌──────────────────┐
                                                            │  Gemini Live API │
                                                            │  (speech-to-     │
                                                            │   speech + video)│
                                                            └──────────────────┘
```

Both halves live in this repo and meet at exactly one place: **a LiveKit room**. The
glasses publish microphone and camera tracks into it; the agent joins the same room,
forwards that audio and video to Gemini Live, and publishes Gemini's speech back as its
own audio track. The glasses never talk to Gemini directly — they hold no Google
credentials and know nothing about which model is in use.

That seam is why the phases are ordered the way they are. A browser publishes tracks the
same way the glasses will, so once phase 1 passes, the server is known-good and any later
failure is on the client side by elimination.

### Layout

```
agent/                  Python worker
  pyproject.toml
  .env.example          copy to .env.local and fill in
  src/
    agent.py            entrypoint, server, session start
    config.py           env + session model factory
    prompts.py          system instructions
    tools.py            @function_tool defs
android/                Kotlin + Compose app for the glasses (phase 2)
```

`config.py` holds the only real abstraction: `build_session_model()` returns keyword
arguments for `AgentSession`. Today that's a single realtime speech-to-speech model.
Swapping in a half-cascade setup later means returning `{"llm": ..., "tts": ...}` from
that one function; `agent.py` doesn't change.

The model string is never hardcoded — it's read from `GEMINI_MODEL` so we can A/B models
by editing `.env.local`.

## Phase 1 — the agent

### 1. Run livekit-server locally

Dev mode uses the well-known key pair `devkey` / `secret` and binds to `127.0.0.1:7880`.

Download `livekit_<version>_windows_amd64.zip` from
[the releases page](https://github.com/livekit/livekit/releases/latest), unzip
`livekit-server.exe` somewhere on your PATH, then:

```shell
livekit-server --dev
```

On Windows it logs `CPU monitoring unsupported` and disables capacity management. That's
expected and harmless for local development.

Docker works too, if you'd rather:

```shell
docker run --rm -it -p 7880:7880 -p 7881:7881 -p 7882:7882/udp livekit/livekit-server --dev
```

### 2. Configure the agent

```shell
cd agent
cp .env.example .env.local
# then put your Gemini API key in GOOGLE_API_KEY
```

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). The plugin
reads it via `GOOGLE_API_KEY`; it never touches LiveKit Cloud.

### 3. Install and run

```shell
uv sync
uv run src/agent.py console   # talk to the agent in your terminal
```

`console` mode runs a full session locally and does **not** connect to livekit-server —
useful for checking the model, prompt, and tool calling in isolation. To exercise the
actual room transport instead:

```shell
uv run src/agent.py dev       # registers with livekit-server, waits for a room
```

Ask it to remember something ("remember that I parked in section B") to see the
placeholder `remember_note` tool fire in the logs.

Two notes on `dev` with the pinned SDK (1.6.10): it prints a deprecation warning pointing
at `lk agent dev`, which is LiveKit Cloud-oriented and not what we want, and its
in-process auto-reload has been removed, so restart it by hand after edits. `dev` still
works fine against a self-hosted server. For a long-running worker use `start`, and for
debugging one specific room use `connect --room <name>`.

### Two traps on Windows

**Console mode can die on a `UnicodeEncodeError`.** The TUI prints emoji, and if stdout
lands on a `cp1252` codepage it crashes in `rich`'s legacy Windows renderer. Force UTF-8
once per shell session:

```powershell
$env:PYTHONUTF8 = "1"     # PowerShell
uv run src/agent.py console
```

```shell
export PYTHONUTF8=1       # bash / git-bash
uv run src/agent.py console
```

**Don't set the root logger to `DEBUG`.** Doing so enables the `websockets` client logger,
which dumps outgoing headers — including the `x-goog-api-key` header, in plaintext, with
your Gemini key in it. The `--log-level debug` flag on `dev`/`start` is scoped to LiveKit's
own loggers and does *not* leak the key; a blanket `logging.basicConfig(level=DEBUG)` in
your own script does. If you ever do it by accident, rotate the key.

Metrics and usage come from the agent's own log output; there's no separate
instrumentation.

## Notes on the model

We target `gemini-3.1-flash-live-preview`, which has
[documented compatibility gaps](https://docs.livekit.io/agents/models/realtime/plugins/gemini/#gemini-3-1-compatibility)
with LiveKit Agents. Two shape the code:

- **No opening greeting.** The model rejects `send_client_content` after the first model
  turn, so `session.generate_reply()` is ignored with a warning. The wearer speaks first.
  This is why `agent.py` has no greeting call where the quickstart has one.
- **No mid-session instruction or context updates.** `update_instructions()` and
  `update_chat_ctx()` don't take effect, which also rules out agent handoffs. We run a
  single agent, so this costs us nothing today.

- **The test framework can't test 3.1.** `session.run(user_input=...)` is built on
  `generate_reply()`, so it raises `RealtimeError: generate_reply is not compatible with
  'gemini-3.1-flash-live-preview'`. Behavioral tests via `pytest` are therefore off the
  table while 3.1 is the target model — verification has to go through a real audio
  conversation. The same tests pass against a 2.5 model, so they're useful for checking
  prompt and tool wiring, just not the model we ship.

Also: affective dialog and proactive audio are unsupported on 3.1 and are not set, tool
calls are synchronous (the model waits for the result), and `thinking_config` uses
`thinkingLevel` rather than `thinkingBudget`, defaulting to `minimal` for latency.

None of this affects live audio. Real speech turns arrive over the realtime audio path,
not `send_client_content`, and the docs confirm voice conversations, tool calling, and
audio I/O all work normally on 3.1.

Video input is enabled via `RoomOptions(video_input=True)`. Frames stream inline within
the Gemini realtime protocol, sampled at 1 fps while the wearer speaks and 0.3 fps
otherwise. Each frame costs tokens, so there's a marked `TODO` in `agent.py` where a
custom `video_sampler` goes when we tune for battery.

## Phase 2 — Android client

Not started. `android/` is intentionally empty until phase 1 passes.

Planned: Kotlin + Jetpack Compose starting from
[`agent-starter-android`](https://github.com/livekit-examples/agent-starter-android),
using the LiveKit Android SDK to publish mic + camera and subscribe to the agent's audio.
A `token_server.py` (~40 lines, same language and credentials as the agent) lands in
`agent/src/` at that point so the glasses can fetch a join token.

Two things to expect when the headset joins: run the server with `--bind 0.0.0.0` and
point `LIVEKIT_URL` at this machine's LAN IP, and if the server is in Docker, pass
`--node-ip <lan-ip>` so the SFU advertises an address the glasses can actually reach.

## Reference

- [Gemini Live API plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/)
- [Live video input](https://docs.livekit.io/agents/multimodality/vision/video/)
- [Agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/) — the agent uses
  automatic dispatch (no `agent_name` set) while there's no token server
- [Running LiveKit locally](https://docs.livekit.io/transport/self-hosting/local/)
- [RayNeo dev docs](https://rayneo-en.gitbook.io/rayneo-devdoc/x-series/android-sdk) —
  camera and audio capture on the X-series
- [Earlier prototype](https://github.com/Lambozhuang/rayneo-x3-pro-gemini-live) —
  glasses straight to Gemini Live, no LiveKit. Reference only, for capture parameters
  known to work on this hardware.
