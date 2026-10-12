# RayNeo X3 Pro live AI assistant

A voice assistant on RayNeo X3 Pro AR glasses that guides the wearer through a LEGO build, on LiveKit, with GPT-Live or Gemini Live.

## Overview

The project is a test bed for how the network between the glasses and the server changes a voice-and-vision assistant. The LEGO build is the workload: the wearer picks one of 13 five-brick builds on the glasses, then talks the build through with the assistant, which sees through the glasses' camera, says which brick to find and where it goes, checks each brick placed and keeps the step list on the glasses current. The agent has two architectures: GPT-Live with a separate vision model, and Gemini Live alone.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.png">
  <img alt="Architecture: the glasses reach our server over Wi-Fi, the link under test; livekit-server and the Python agent share that server; only the agent talks to OpenAI, GPT-Live over a WebSocket"
       src="docs/architecture-light.png">
</picture>

There are two machines: the glasses, and a server on the same Wi-Fi network. The glasses talk only to the server; only the server talks to the model APIs (OpenAI, Anthropic, Google).

The glasses run the app in `android/`: it sends the mic and camera to the server, plays the assistant's speech and shows the steps. It holds no model keys.

The server runs three programs:

- **livekit-server**, LiveKit's media server: the glasses and the agent join the same room on it; it checks their join tokens and passes audio and video between them.
- **api** (`backend/api/`): lists the builds, and gives the glasses their join token with the build they picked.
- **agent** (`backend/agent/`): joins the room as the assistant, with that build loaded, and holds the model keys. It runs one of the two architectures below, picked by `AGENT_BACKEND`.

A call starts with the glasses asking the api for the builds; the wearer picks one, the glasses get a join token for it and join the room, and the agent joins too. It ends when the wearer ends it on the glasses.

### GPT-Live and a vision model (`AGENT_BACKEND=openai`, `agent/src/gpt/`)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/agent-dark.png">
  <img alt="Inside the agent: audio to a GPT-Live session whose persona holds every step's wording; video to FrameTap; the session delegates to the brain with an id, the brain takes the newest frame and the call's turns to a vision model and answers with commentary on that id, and the step list to the glasses; the task file feeds both"
       src="docs/agent-light.png">
</picture>

Two models. GPT-Live (`gpt-live-1`) is the voice: it hears the wearer and speaks, both at once, and decides itself when to talk; it takes audio only, so it cannot see. The brain (`gpt/brain.py`) is the eyes: it sends the camera picture to a vision model (OpenAI or Anthropic) and keeps the build's progress.

1. GPT-Live's prompt holds every step, so what the steps or the conversation answer, it answers itself.
2. What needs eyes, or a brick placed, it hands over to the agent: GPT-Live sends a hand-over (a "delegation") with an id, sometimes with the wearer's words.
3. The brain sends one request to the vision model: the newest camera frame, the call so far, the progress, the wearer's words.
4. The brain's reply goes back to GPT-Live as text attached to that id (a "commentary"), and GPT-Live says it in its own words.
5. When the vision model judges that more or fewer steps are built right, it says so through its one tool, `set_progress`: the step list on the glasses changes and the same commentary tells GPT-Live.

### Gemini Live (`AGENT_BACKEND=gemini`, `agent/src/gemini/`)

One model, Gemini Live (`GEMINI_MODEL`), hears, sees and speaks. Camera frames go to it while the wearer speaks (`VIDEO_SPEAKING_FPS`, 0.5 a second) and one at a time when it calls its `look` tool; every frame it gets stays in its context, so they are rationed (`gemini/sampler.py`). It judges the bricks itself and moves the build through its own tools (`gemini/tools.py`: `get_step`, `look`, `step_done`, `reopen_previous_step`, ...). A local VAD (Silero) tells the agent when the wearer is talking; when to answer stays Gemini's. This architecture writes no call record (see Logs).

<sub>`python docs/make_diagram.py` and `docs/make_agent_diagram.py` regenerate the figures.</sub>

## Running

**Server** (Linux with Docker; the lab PC is Ubuntu on the glasses' network, over ssh, nothing installed as a service). The three programs run as Docker containers, all in `backend/docker-compose.yml`. They use the server's own network rather than Docker's (`network_mode: host`): livekit-server tells the glasses which IP address and UDP ports to send media to, and that has to be the server's real LAN address, not a container's.

```shell
deploy/setup.sh lab              # once: key pair, livekit.yaml, backend/.env
cd backend
GIT_COMMIT=$(git describe --always --dirty) docker compose up -d --build
docker compose logs -f --no-log-prefix agent | python3 ../deploy/watch.py
docker compose down              # after testing
```

`backend/.env` (see `.env.example`) takes `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` for an Anthropic brain, the model ids, `AUTH_MODE` (`dev` lets anyone in, `static` wants one shared token, `jwt` an account system's token) and `LIVEKIT_PUBLIC_URL` (`ws://<lan-ip>:7880`, what the glasses get). `setup.sh` prints the ufw rules the glasses need if ufw is on. Without Docker, against `docker run --rm -it --network host livekit/livekit-server --dev`: `uv run src/server.py` in `backend/api`, `uv run src/agent.py start` in `backend/agent`.

**Glasses** (Windows with adb):

```powershell
cd android
./gradlew :app:assembleDebug        # needs a JDK; Android Studio's jbr works
adb install -r app/build/outputs/apk/debug/app-debug.apk
.\deploy\glasses.ps1 -Ip 192.168.50.147   # launch against that server (-Install builds first, -Stop, -Task <name>)
```

The debug build is required: it allows cleartext `http://` / `ws://` to a LAN IP. Glasses and server must share an IP network: USB carries adb only, and libwebrtc binds to Wi-Fi. `glasses.ps1` also turns off the policy that switches the glasses' Wi-Fi off a minute after they think they were taken off; `-RestoreSleep` puts it back. On the glasses: swipe to pick a build, tap to call, double tap to end the call or leave.

## Logs

The agent log (`docker compose logs agent`, coloured by `deploy/watch.py`) of the GPT-Live architecture, by prefix:

| prefix | what |
|---|---|
| `experiment:` | every setting of the run |
| `user:` / `assistant:` | both transcripts, when a turn ends |
| `live:` | who speaks when; `live: sent` every event to GPT-Live but mic audio; `live: event` GPT-Live's own (delegations, receipts, errors) |
| `delegation:` | a hand-over, with the wearer's words |
| `brain:` | per request: frame, timings, tokens, reply, one line per tool call |
| `voice:` | when GPT-Live started saying an answer |
| `step` | progress changes |
| `camera:`, `link:` | first frame; the glasses joining, leaving, link quality |
| `gpt-live:` | session start and close, seconds billed |

Each call of that architecture also leaves a record in `backend/runs/<UTC start>-<room>/`: `events.jsonl` (the log's story with every field), the photos sent to the brain, both prompts as sent. `python deploy/pull_run.py [<call>]` copies the newest (or that) record into `logs/` and writes `report.html` (timeline, waits, what went wrong) and `rounds.html` (each request's input and output in full). The container writes records as root; delete them with `docker run --rm -v "$PWD/runs:/r" backend-agent sh -c "rm -rf /r/2026*"` in `backend/`.

**Never set the root logger to `DEBUG`**: the `websockets` logger then prints request headers, API keys included. `--log-level debug` on the agent CLI is fine. If it happens, rotate the key.

## Code

```
backend/
  docker-compose.yml    livekit-server + api + agent
  .env.example          copy to .env; one file for all three
  api/src/              server.py (/getToken, /tasks), auth.py (AUTH_MODE)
  agent/src/agent.py    entrypoint, AGENT_BACKEND picks gpt/ or gemini/
  agent/src/gpt/        GPT-Live and a vision model: agent, config, prompts, brain
  agent/src/gemini/     Gemini Live: agent, config, prompts, tools, sampler; render.py serves it
  agent/src/guide.py    task file loader and the build's progress
  agent/src/frames.py   FrameTap: keeps the newest camera frame
  agent/src/runlog.py   one record per call (RUN_DIR)
  agent/guides/         the builds the glasses pick from, one task.toml each
android/                the glasses app
tasks/                  the task sheet (sheet.html) and its bricks
deploy/                 setup.sh, livekit.lab.yaml, glasses.ps1, record.ps1, watch.py,
                        pull_run.py, report.py, rounds.py
docs/                   the figures and their scripts
logs/                   records pulled from the lab (not in git)
```

**agent/src/gpt/**: `prompts.py` builds both prompts from the task file; `brain.py` answers each hand-over (its docstring has the details: the frame's crop, timeouts, a newer hand-over cancelling an older one); `agent.py` wires the session, the brain and the logs.

**agent/src/gemini/**: `prompts.py` the model's instructions, `tools.py` its tools, `sampler.py` which frames it gets (its docstring has the measurements behind the rationing), `agent.py` the session.

**Task file** (`guides/<task>/task.toml`): per step a name for the list on the glasses, the brick, where it goes against the bricks before it, and the brick's cells as drawn (for the sheet, not the models). The 13 numbered ones are those of `tasks/sheet.html`.

**android/**: the panel is 640x480 per eye, reported as one 1280x480 display at density 160, so every screen draws its content twice through `ui/Eyes.kt`:

- State lives above `Eyes`; a `remember` inside runs once per eye and drifts.
- `Eyes` keeps a 24 dp black margin (the optics distort at the edges); no window insets at the root, they span all 1280 px.
- The display is additive: black emits nothing, so the background is black, no light theme.
- Check layouts with `adb shell uiautomator dump`; `screencap` is post-correction and misreports.

The camera sensor is mounted sideways: frames arrive as 1080x1920 portrait, fixed focus. The app sends one 1920x1080 layer, 15 fps, H264 on the hardware encoder at 4 Mbps (`VoiceAssistantViewModel.kt`), through libwebrtc's `HardwareVideoEncoderFactory` directly: the SDK's simulcast wrapper crop-scales this sensor's frames, and VP8 is software here and blurry. `VideoStatsLog.kt` logs the encoder every 5 s under `rayneo-video`. The "Reconnecting" banner reads the SDK engine's own state (`EngineState.kt`), since the public room state stays "connected" through the soft reconnect a Wi-Fi drop triggers.

## Reference

Where to look, by source; what each covers, not what it says.

**LiveKit docs** (also searchable through the livekit-docs MCP server)
- [GPT-Live plugin](https://docs.livekit.io/agents/models/realtime/plugins/gpt-live/): delegation modes, the three context channels, starting speech, turns and transcripts
- [Video](https://docs.livekit.io/agents/multimodality/vision/video/), [Agent sessions](https://docs.livekit.io/agents/logic/sessions/): frame sampling, live video input, `video_sampler`, idle users
- [Gemini Live plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/), [Gemini vision recipe](https://docs.livekit.io/reference/recipes/gemini_live_vision/): video input and the proactivity option on the Gemini side
- [Subagent delegation](https://docs.livekit.io/agents/logic/patterns/subagent-delegation/): a fast voice model with a slower reasoning model behind it
- [Agent dispatch](https://docs.livekit.io/agents/server/agent-dispatch/), [Token endpoint spec](https://docs.livekit.io/frontends/build/authentication/endpoint/), [Running LiveKit locally](https://docs.livekit.io/transport/self-hosting/local/)

**LiveKit code** ([livekit/agents](https://github.com/livekit/agents))
- [examples/voice_agents/gpt-live](https://github.com/livekit/agents/tree/main/examples/voice_agents/gpt-live): the client-delegation example this agent is built on, and its README on append receipts
- `livekit-plugins-openai/.../realtime/gpt_live_model.py` (also in `backend/agent/.venv`): how the appends, `generate_reply`, `pending_transcript` and the turn split are implemented

**OpenAI**
- Guides: [live](https://developers.openai.com/api/docs/guides/live), [live-conversations](https://developers.openai.com/api/docs/guides/live-conversations), [live-delegation](https://developers.openai.com/api/docs/guides/live-delegation), [live-prompting](https://developers.openai.com/api/docs/guides/live-prompting), [decisions-voice](https://developers.openai.com/api/docs/guides/decisions-voice), [live-partner-integrations](https://developers.openai.com/api/docs/guides/live-partner-integrations), [WebRTC quickstart](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live): sessions, append timing, compaction, delegation and images, how to lay out the prompt; `developers.openai.com/api/docs/llms.txt` indexes them
- [Voice agent evaluation](https://developers.openai.com/cookbook/examples/audio/voice_agent_evaluation) and its harness ([duplex_voice_agent_evaluation](https://github.com/openai/openai-cookbook/tree/main/examples/audio/duplex_voice_agent_evaluation)): testing a GPT-Live agent without people, telling speech from silence on the audio
- [Community thread on gpt-live-1](https://community.openai.com/t/important-feedback-improvements-for-gpt-live-1-api/1402227): field reports on appended instructions and commentary
- [Microsoft Foundry event reference](https://learn.microsoft.com/azure/foundry/openai/gpt-live-reference): every client and server event with its fields

**Pipecat** (GPT-Live with a second model of its own)
- [OpenAI Live service](https://docs.pipecat.ai/api-reference/server/services/s2s/openai-live) and [examples/realtime](https://github.com/pipecat-ai/pipecat/tree/main/examples/realtime) (`realtime-openai-live-client-delegation*.py`, `-responses-delegation.py`)
- `src/pipecat/services/openai/live/llm.py`, `src/pipecat/workers/llm/backend_llm_worker.py`: how the backend's context is kept across hand-overs, spoken vs silent results, overlapping hand-overs

**Google** (Gemini Live)
- [Live guide](https://ai.google.dev/gemini-api/docs/live-guide), [Live tools](https://ai.google.dev/gemini-api/docs/live-tools), [Gemini 3.8 Live](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live): proactive audio, video input, async function scheduling, model differences
- [Cookbook quickstarts](https://github.com/google-gemini/cookbook/tree/main/quickstarts) (`Get_started_LiveAPI.py`, `Get_started_LiveAPI_tools.ipynb`, `Get_started_Live_Thinking.ipynb`): camera streaming, tool scheduling, background reasoning

**Twilio**: [GPT-Live resources](https://www.twilio.com/en-us/blog/developers/twilio-openai-gpt-live-1-api-resources), phone-call samples, audio only

**This project's own ground**
- [RayNeo dev docs](https://rayneo-en.gitbook.io/rayneo-devdoc/x-series/android-sdk)
- [agent-starter-android](https://github.com/livekit-examples/agent-starter-android), the app's origin (MIT, `android/LICENSE`)
- [Earlier prototype](https://github.com/Lambozhuang/rayneo-x3-pro-gemini-live), glasses straight to Gemini Live without LiveKit
