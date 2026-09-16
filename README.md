# RayNeo X3 Pro live AI assistant

A voice-and-vision assistant for RayNeo X3 Pro AR glasses, built on LiveKit and the
Gemini Live API. The first use case is helping the wearer build with LEGO: the model has
to see well enough to count the studs on a brick.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.png">
  <img alt="Architecture: the glasses and the Python agent meet in one self-hosted
LiveKit room; the agent alone talks to Gemini Live, over a WebSocket"
       src="docs/architecture-light.png">
</picture>

<sub>Sources: `docs/architecture-*.svg`; `python docs/make_diagram.py` regenerates them
and the PNGs.</sub>

The two halves meet in one place, a LiveKit room. The glasses publish microphone and
camera tracks into it; the agent joins the same room, forwards audio and video to Gemini
Live over a WebSocket, and publishes Gemini's speech back as its own audio track. The
glasses hold no Google credentials and do not know which model is in use.

Three processes, all in one compose project with host networking (WebRTC needs the
server's UDP ports reachable at the address it advertises; a bridge network only adds NAT):

- **livekit-server** verifies join tokens and forwards media.
- **api** is the door: the glasses `POST /getToken` with a credential, `auth.py` turns it
  into a user id or a 401, `server.py` signs a ten-minute JWT with that identity and a
  `room_config` naming the agent. Login, entitlements and billing would go here.
- **agent** registers under `AGENT_NAME` and joins only rooms whose token names it. It
  alone holds the Gemini key; nothing connects to it directly.

`AUTH_MODE` selects who may start a session: `dev` accepts everyone (private LAN),
`static` wants one shared bearer token, `jwt` verifies a token from an account system and
takes the user id from `sub`. See `backend/api/src/auth.py`.

`config.py` has the one abstraction: `build_session_model()` returns the keyword
arguments for `AgentSession`. Today that is one realtime speech-to-speech model; a
half-cascade setup would return `{"llm": ..., "tts": ...}` from the same function. The
model id comes from `GEMINI_MODEL` in `.env`, never from source, so models can be A/B'd.

## Layout

```
backend/
  docker-compose.yml    livekit-server + api + agent, host networking
  .env.example          copy to .env and fill in; one file for all three
  api/src/server.py     POST /getToken, LiveKit's standard token endpoint
  api/src/auth.py       AUTH_MODE = dev | static | jwt
  agent/src/agent.py    entrypoint: session start, usage and transcript logging
  agent/src/config.py   env + session model factory, frame encode options
  agent/src/guide.py    build guide loader and the state of one run
  agent/src/prompts.py  system instructions
  agent/src/tools.py    @function_tool definitions: get_step, step_done, reopen_previous_step, restart_build, end_call
  agent/guides/         build guides (TOML), chosen with BUILD_GUIDE
  agent/src/framedump.py, inspect_frame.py   see "Seeing what the model saw"
android/                Kotlin + Compose app for the glasses
deploy/
  setup.sh              first-time setup on a Linux host: key pair, livekit.yaml, .env
  livekit.lab.yaml      livekit-server config for a private LAN
  glasses.ps1           launch/stop the app on the glasses over adb
  watch.py              coloured live view of the agent log
  stop.ps1              end a session: stop the app, then compose down on the lab PC
```

## Running the backend

On a Linux host with Docker:

```shell
deploy/setup.sh lab                 # once: generates a key pair, writes livekit.yaml and backend/.env
cd backend
docker compose up -d --build        # livekit-server :7880, api on API_PORT, agent
docker compose logs -f agent        # "registered worker", then per call "session for user=", "build:", "step 1/3", "user:", "assistant:", "usage:"
docker compose logs -f --no-log-prefix agent | python3 ../deploy/watch.py   # the same as a coloured conversation
docker compose down
```

`watch.py` keeps only the conversation, the build's progress, timings and warnings. Two timing
lines per reply: `model:` is the model's own (`ttft`, first server message of a generation to
its first audio; `duration`; this turn's tokens, image tokens spelled out), and `latency:` is
`reply_ms`, measured on the glasses from the wearer's last word to the agent's audio arriving
and sent over as a data packet (`ReplyLatency.kt`). The second is the one a wearer feels and
the one the experiment is about; the SDK's `e2e_latency` is empty for Gemini, whose turn
detection never reports when the wearer stopped.

`setup.sh` takes the Gemini key from `$GOOGLE_API_KEY`, or asks at a terminal, or leaves it
blank for you to paste into `backend/.env`. It prints the ufw rules the glasses need if ufw
is active. `LIVEKIT_URL` stays on loopback for the agent's own connection;
`LIVEKIT_PUBLIC_URL` (`ws://<lan-ip>:7880`) is what `/getToken` hands the glasses.

Without Docker, against `docker run --rm -it --network host livekit/livekit-server --dev`
(key pair `devkey`/`secret`):

```shell
cd backend/api;   uv sync; uv run src/server.py
cd backend/agent; uv sync; uv run src/agent.py start
```

`uv run src/agent.py console` talks to the model in the terminal without a room, for
checking prompt and tools. On Windows set `PYTHONUTF8=1` first or the TUI crashes on a
`cp1252` console.

**Never set the root logger to `DEBUG`.** That enables the `websockets` client logger,
which prints outgoing headers including `x-goog-api-key`. `--log-level debug` on the agent
CLI is scoped to LiveKit's loggers and is fine. If it happens, rotate the key.

## The glasses

```powershell
cd android
./gradlew :app:assembleDebug        # needs a JDK; Android Studio's jbr works
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The debug variant is required: `app/src/debug` carries the network security config that
allows cleartext `http://` and `ws://` to a LAN IP. Only `arm64-v8a` is built, the device's
only ABI. The `applicationId` is `com.rayneo.x3pro.assistant`.

From the dev laptop with the glasses on USB:

```powershell
.\deploy\glasses.ps1 -Ip 192.168.50.147   # launch, pointed at that backend (-Install builds first, -Log tails gestures, -Stop kills it)
```

The app stores the token endpoint and credential in SharedPreferences; `glasses.ps1`
passes them as intent extras (`-e token_endpoint ... -e credential ...`), and the connect
screen has the same two fields. The temple touchpad is a touchscreen to Android: tap
starts the call, double tap ends it, swipes are logged (`adb logcat -s rayneo-input`) but
unused. Under the status the screen lists the build's steps by name with the current one
highlighted; the agent publishes them as participant attributes (`guide.py`, `BuildSteps.kt`).
The bottom of the screen shows the last three turns, the wearer's in green: those are
the model's transcript of what it heard, not a local one, so a word the network dropped is
missing there too. The mic is switched on only once the agent reports that it is listening, and the
banner says "Ready" at that moment; before it nothing is heard. The agent opens with one
sentence and waits for the wearer to say they are ready. (LiveKit's pre-connect buffer would keep speech from the second or two before that, but
delivers it in a late burst, which makes the first reply slow for a reason unrelated to the
network under test; `VoiceAssistantScreen.kt` says where to flip it.) The call screen leaves by
itself when the room ends, whether the agent hung up or the connection was lost for good.

USB carries adb, not media. `adb reverse` forwards TCP only, and libwebrtc on the glasses
binds to the Wi-Fi interface, so no ICE pair ever reaches a loopback SFU. The glasses and
the server must share an IP network.

### Two screens

The X3 Pro has a 640x480 panel per eye. Android reports one 1280x480 display at density
160; the left 640 px go to the left eye, the right 640 px to the right. A phone layout is
cut in half, so every screen draws its content twice through `ui/Eyes.kt`. Rules:

- State lives above `Eyes`; a `remember` inside the content runs once per eye and drifts.
  Session and effect code stays outside too.
- `Eyes` keeps a 24 dp black margin; the optics distort at the panel edges. Do not use
  window insets at the root, they span all 1280 px and break the mirror symmetry.
- The display is additive: black emits nothing, so the background is black and there is no
  light theme.
- Check layouts with `adb shell uiautomator dump`, not `screencap`; the capture is
  post-correction and misreports positions.

### Camera

The sensor is mounted sideways (`android.sensor.orientation=90`), so the field of view is
portrait and frames reach the agent as 1080x1920. Focus is fixed. The app publishes one
layer at 1920x1080, 15 fps, H264 on the hardware encoder, 4 Mbps, `MAINTAIN_RESOLUTION`
(`VoiceAssistantViewModel.kt`). It uses libwebrtc's `HardwareVideoEncoderFactory` directly
because the SDK's simulcast wrapper compares unrotated frame width with rotated encoder
width and crop-scales every frame of this sensor. VP8 is software on this SoC and stays
blurry at any size.

`VideoStatsLog.kt` logs encoder resolution, fps and bitrate every 5 s under `rayneo-video`.
`FrameDump.kt` can save frames as they leave the capturer, to separate camera softness
from transport softness.

## The model

`GEMINI_MODEL` in `.env` picks the Live model; the default deployment runs `gemini-3.8-live`
(livekit-agents 1.8.2 or later knows the 3.8 ids). Things that shape the code:

- Tool calls are asynchronous by default on 3.8: the model may keep talking while a tool
  runs, and answers the result when it comes back. The build guide reaches the model only
  through tools, so that is the channel for anything mid-session.
- Proactive audio is always on: the model may decide not to answer an utterance.
- `thinking_level` is not accepted; 3.8 Live reasons inline with a fixed latency profile.
  `gemini-3.8-live-extended-thinking` takes `low`/`medium`/`high`, but requires NON_BLOCKING
  tools and a new `interaction_status` turn protocol the plugin does not parse yet; untested.
- The earlier `gemini-3.1-flash-live-preview` gaps (no `generate_reply`, no mid-session
  context updates, no `session.run` tests) are closed on this plugin version. Verification is
  still a real conversation, judged from the agent log.

### Guided build

`BUILD_GUIDE` names a TOML file in `agent/guides`: a title and an ordered list of steps, each
just the part to pick up, what to tell the wearer, and an optional one-line `name` for the list
on the glasses. The agent process holds the position
(`guide.py`, in `session.userdata`); the model sees one step at a time through `get_step`,
judges from the camera when the step is built and calls `step_done` to advance, can go back one
with `reopen_previous_step` when a step was passed too early, and can `restart_build` or
`end_call`. The prompt carries the title and the steps' one-line names (the same list the
wearer sees on the glasses, so both sides can say "step two"), not the instructions, so the
model cannot narrate steps from memory. The code tracks progress but does not check the bricks: hand-written
geometry (an earlier version compared colour, size, orientation and relative position in
code) does not generalise past a flat 2D layout, and the real cure for the model over-declaring
completion is to ground it against a reference image, not to encode every shape. That is the
next step: a stronger full-duplex model for the dialogue and a separate photo model that sees
one fresh frame against a reference (see TODO). The log has `build:`, `step n/m start`, `step
n/m done` and `build finished` lines with timings, so a run can be scored from the log next to
the dumped frames. Tools stay fast anyway: the model talks over them, and a slow one would
have it narrating the wait.

### Video

Frames are sampled at 1 fps while the wearer speaks and 0.3 fps otherwise
(`VoiceActivityVideoSampler`), encoded as JPEG at their captured size (`IMAGE_ENCODE_OPTIONS`
in `config.py`; the plugin default would shrink them to 1024) and streamed inline with the
audio. The Live API spends a fixed budget per frame regardless of pixel size: 70 tokens by
default, 280 with `GEMINI_MEDIA_RESOLUTION=MEDIA_RESOLUTION_HIGH`. Audio is about
1500 tokens/min. `input_image_tokens` in the `usage:` log line is the whole cost of the
camera, and also the only sign that video reaches the model at all: a broken video path
does not fail, it produces confident answers about a picture the model never saw. Check
vision with content you know. `livekit-agents[google,images]` is required for the same
reason; without Pillow the plugin drops every frame with a logged `ImportError`.

What the detail budget buys, measured on LEGO at the lab: a 16x16 baseplate and a 1x4 brick
half a metre away are read correctly at either budget. A 1x6 at that distance is about
30 px wide in the 1080p frame and is misread at every budget, including a 12 MP still.
Held 25 cm from the camera it is about 260 px and readable, yet the model still answered
"8 studs" until the system prompt told it to count one by one and never assume a standard
size. Distance and prompt matter more than pixels here.

### Seeing what the model saw

- `FRAME_DUMP_DIR=/app/frames` in `.env` makes `framedump.py` write every frame the sampler
  passes to `backend/frames/<call timestamp>/NNN-full.jpg` (as received, JPEG 95) and
  `NNN-sent.jpg` (exactly as uploaded). `FRAME_DUMP_MAX` caps the count, default 60. Nothing
  is deleted automatically. The container writes as root, so on the host delete with
  `docker run --rm -v "$PWD/frames:/f" backend-agent sh -c "rm -rf /f/2026*"`.
- `inspect_frame.py` sends a saved frame through `generate_content` at `low` / `high` /
  `ultra_high` per-part media resolution (about 265 / 1100 / 2200 image tokens on Gemini 3)
  and prints each answer. Right only at `high` or above means the Live budget was the
  limit; never right means camera or model. The model id is `--model` or
  `GEMINI_INSPECT_MODEL`.

  ```shell
  cd backend
  docker compose run --rm agent uv run --no-sync python src/inspect_frame.py --model gemini-3.6-flash frames/<call>/005-full.jpg
  ```

## The lab PC

Ubuntu on the glasses' network, reached over ssh. It runs the recipe above:
`docker compose up -d --build` while testing, `docker compose down` after. The machine has
other jobs, so nothing is installed as a service. `AGENT_MP_CONTEXT=spawn` in `.env` is
only for a host whose CPU lacks AVX2; see the note in `agent.py`.

## When it breaks

A bad `GOOGLE_API_KEY` logs `Gemini Realtime API error: 1007 ... API key not valid`, the
session closes and the job ends without retry. The wearer hears silence and the banner turns
red: "Agent left" if an agent was in the room and went, "No agent" if none arrived within
the SDK's 20 s; both say to double tap out. A connection the SDK is still retrying shows
"Reconnecting"; one it has given up on returns the app to the connect screen. That banner
reads the SDK engine's own state (`EngineState.kt`, by reflection): the public room state,
and so the components' `Session`, stays "connected" through a soft reconnect, which is what a
Wi-Fi drop triggers first.

The glasses switch Wi-Fi off by themselves one minute after they decide they have been taken
off (`RayneoSuspendManagerService`, the system's deep-suspend policy; the wear sensor also
misfires mid-session, and the same event blanks the screen). `glasses.ps1` turns that policy off
at launch with `settings put global deep_suspend_disabled_persist 1`, which survives reboots:
the glasses then stay awake and online off the head, at a battery cost; `glasses.ps1 -RestoreSleep`
puts it back when the experiment is over. If the banner still sticks at "Reconnecting", check
`adb shell settings get global wifi_on`; `adb shell svc wifi enable` brings the network back.

## Reference

- [Gemini Live API plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/)
- [Live video input](https://docs.livekit.io/agents/multimodality/vision/video/)
- [Agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/)
- [Token endpoint spec](https://docs.livekit.io/frontends/build/authentication/endpoint/)
- [Running LiveKit locally](https://docs.livekit.io/transport/self-hosting/local/)
- [RayNeo dev docs](https://rayneo-en.gitbook.io/rayneo-devdoc/x-series/android-sdk)
- [agent-starter-android](https://github.com/livekit-examples/agent-starter-android), the
  app's origin (MIT, `android/LICENSE`)
- [Earlier prototype](https://github.com/Lambozhuang/rayneo-x3-pro-gemini-live), glasses
  straight to Gemini Live without LiveKit
