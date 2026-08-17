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

### Transports

The `WebRTC` labels above are shorthand. Each link to the server is really more than one
connection:

| Connection | Transport | Purpose |
| --- | --- | --- |
| Worker registration | WebSocket, `:7880` | The agent announces itself and receives job assignments. Agent only — the glasses have no equivalent. |
| Room signaling | WebSocket, `:7880` | SDP/ICE negotiation, participant and track events |
| Media | SRTP over UDP `:7882`, TCP `:7881` as fallback | The audio and video packets themselves |

Only the last one is WebRTC media, and it's what buys us jitter buffering, packet loss
concealment, and congestion control over flaky Wi-Fi. Streaming raw PCM over a WebSocket
would mean reimplementing all of that, and TCP head-of-line blocking turns one lost packet
into an audible stall.

The agent is an ordinary room participant, not a privileged backend service — the SFU
treats the Python worker exactly as it treats a browser tab or the glasses. The Python
`livekit` package ships `livekit_ffi.dll`, Rust bindings around libwebrtc, the same engine
Chrome uses.

On the far side the transport flips: agent → Gemini is a WebSocket, with audio and video
frames muxed into one message stream. So part of the agent's job is translating between the
two worlds, depacketizing WebRTC audio for Gemini and packetizing Gemini's speech back into
an outbound WebRTC track.

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
    token_server.py     join-token endpoint for the glasses
android/                Kotlin + Compose app for the glasses
  app/src/main/.../TokenExt.kt    where to find the token server
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

`android/` is Kotlin + Jetpack Compose, derived from
[`agent-starter-android`](https://github.com/livekit-examples/agent-starter-android)
(MIT, kept at `android/LICENSE`). It publishes microphone and camera and subscribes to the
agent's audio. It holds no Google credentials and never speaks to Gemini.

`agent/src/token_server.py` mints the join tokens. The glasses `POST /getToken` and get
back a server URL and a JWT, following LiveKit's
[standard token endpoint](https://docs.livekit.io/frontends/build/authentication/endpoint/)
so the client's built-in `TokenSource.fromEndpoint` works unmodified.

### Running it

Three processes, in this order:

```powershell
livekit-server --dev --bind 0.0.0.0     # signaling reachable from the LAN
uv run src/token_server.py              # port 3000
uv run src/agent.py start               # or `dev`
```

`.env.local` needs `LIVEKIT_URL` set to this machine's **LAN IP**, not `127.0.0.1` — that
URL is handed to the glasses verbatim, and the token server warns on startup if it looks
like loopback. The app's endpoint address lives in `android/.../TokenExt.kt`.

Then build and sideload:

```powershell
cd android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Gradle needs a JDK. Android Studio ships one, so `$env:JAVA_HOME =
"C:\Program Files\Android\Android Studio\jbr"` is enough; `local.properties` (gitignored)
points at the SDK. The debug variant is required — `app/src/debug` carries the network
security config that permits cleartext `http://` and `ws://` to a LAN IP, which a release
build refuses.

### What changed from the starter

- **One token path.** The starter tries a LiveKit Cloud sandbox, then a hardcoded token,
  then falls back to livekit.com's public homepage agent. That last fallback would silently
  put the wearer in a room with someone else's agent, so it's gone; a bad endpoint now
  fails loudly.
- **Camera on by default.** `requestedVideo` starts `true`. Reaching up to tap a toggle
  defeats the point of glasses, and it gets both permission prompts out of the way at once.
- **Own identity.** `applicationId` is `com.rayneo.x3pro.assistant` so it installs
  alongside the upstream starter instead of replacing it. The Kotlin package is untouched,
  which keeps the diff against upstream readable.
- Dropped upstream's `taskfile.yaml`, `.env.example`, `renovate.json`, and CI workflow —
  all of it existed to wire up a Cloud sandbox or to build a submodule we don't have.

### Networking notes

`--bind` only moves the signaling port. In dev mode `:7880` listens on loopback alone,
while the media ports `:7881` and `:7882` are already on every interface — so a headset
that fails to connect at all is a signaling problem, whereas one that connects but hears
silence is a media routing or advertised-address problem. If the server runs in Docker,
pass `--node-ip <lan-ip>` so the SFU advertises an address the glasses can reach.

Dev mode uses the well-known `devkey` / `secret` pair, and the token endpoint has no
authentication at all. Both are exposed to the whole local network while this is running.
That is acceptable on a trusted network for development and nowhere else.

### Open on-device questions

None of the following can be settled without the glasses connected:

- **Whether the default camera capture works.** LiveKit enumerates cameras through
  Camera2/CameraX; the X3 Pro may expose its camera unusually. The
  [earlier prototype](https://github.com/Lambozhuang/rayneo-x3-pro-gemini-live) uses
  CameraX at **640×480, 1 fps**, and 16 kHz capture / 24 kHz playback for audio — a known-good
  reference if defaults misbehave. LiveKit and the Gemini plugin negotiate audio rates
  themselves, so only the camera is likely to need attention.
- **Whether a frame ever reaches Gemini.** `video_input=True` has been wired and the agent
  logs `using video io: RoomIO > AgentSession`, but no client has published a camera track
  yet, so the video path is unproven end to end.
- **Battery and token cost.** 640×480 at 1 fps is the reference point for the
  `video_sampler` TODO in `agent.py`.
- **UI fit.** The starter's layout is designed for a phone, not a heads-up display.

## Reference

- [Gemini Live API plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/)
- [Live video input](https://docs.livekit.io/agents/multimodality/vision/video/)
- [Agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/) — the agent uses
  automatic dispatch (no `agent_name` set), so it joins every room the token server hands
  out. `token_server.py` therefore issues a fresh room name per request
- [Token endpoint spec](https://docs.livekit.io/frontends/build/authentication/endpoint/)
- [Running LiveKit locally](https://docs.livekit.io/transport/self-hosting/local/)
- [RayNeo dev docs](https://rayneo-en.gitbook.io/rayneo-devdoc/x-series/android-sdk) —
  camera and audio capture on the X-series
- [Earlier prototype](https://github.com/Lambozhuang/rayneo-x3-pro-gemini-live) —
  glasses straight to Gemini Live, no LiveKit. Reference only, for capture parameters
  known to work on this hardware.
