# What GPT-Live, the Decisions API and the GPT-6 models can do (2026-11-04)

This note holds what was found on 2026-11-04 about the three APIs the GPT path now rests on, from OpenAI's documentation (developers.openai.com, where platform.openai.com redirects), the LiveKit plugin's source (livekit-plugins-openai 1.8.3, `realtime/gpt_live_model.py`), the OpenAI Python SDK (2.54.0) and our own measurements. The design it led to is in `docs/design/2026-11-04-eyes-and-consult.md`.

## GPT-Live (`gpt-live-1`)

- The session takes `instructions` (immutable after start, 16,384 tokens at most), a text history (128 messages, 8,192 tokens), an audio format, a voice (31 built in, `marin` the default, immutable) and a delegation target. There is no field for pace, response length, language, turn detection or interruption: all of that is prompt. `delegation.responses.text.verbosity` exists but "does not configure the Live model's spoken delivery" (API reference, `live/primary-websocket`).
- Three context channels, each 500 tokens an append: `session.commentary.append`, "information the model should speak aloud, paraphrasing the appended text"; `session.thinking.append`, silent context "not a secrecy boundary"; `session.instructions.append`, standing rules that "can interrupt speech in progress" (guides `live-conversations`, `live-delegation`). None of the acknowledgements confirms that anything was spoken.
- The prompting guide (`live-prompting`) gives a template with three headings, Backchannel policy, Interruption policy and Delegation policy, and recipes for pace ("the fastest clear pace with minimal pauses"), patience ("wait while the caller completes each step"), selected requests only, response length ("for routine questions, give one or two short sentences") and the personality during tool calls. A hand-over is to be written as `Generate <|SpawnThinking|>` and its absence as `Do not generate <|SpawnThinking|>`.
- Client delegation (`delegation.type: client`, the API's default) sends `session.delegation.created` with an id and no text; the application answers by appending. `acknowledgement_delay_ms` (0 to 800) delays the model's automatic spoken acknowledgement, and any append cancels pending acknowledgements; the LiveKit plugin does not expose the field.
- The model takes no image or video, in any mode; a vision backend returns text (model page, `live-delegation`).
- Price $0.05 a minute, billed by the second, the backend's tokens apart. Sessions expire; the limit is not stated.
- Two integrations with the Decisions API exist, `delegation.type: decisions` and `triggers` on transcript events; both take the transcript, not frames.
- Field reports (community thread 1402227, 1398585): `instructions.append` unreliable and apt to cut speech, `commentary.append` inconsistent, a model that promises an action and never delegates; OpenAI staff point to the `<|SpawnThinking|>` wording.

## The Decisions API (`POST /v1/decisions`)

- One model, `gpt-6-luna`. Input is text, images (base64 or URL, detail low, high, auto, original) and JSON in conversation items; no files, no audio, no stored state between requests. Questions, 1 to 400 a request, of three types: predicate (a probability), choice (2 to 255 options, each with a probability, and a confidence), score (2 to 10 ordered levels). No text, no tools; a dependent question is a second request. An image may go inside a question's instructions, to be compared with the shared input's.
- Price $0.10 per million input tokens, output free. Caching applies to a shared prefix of 1,024 tokens or more, which ours does not reach.
- Measured (`eval/brain-decisions/`): 0.34 s median at detail low (512 px, about 1,450 tokens), 0.41 s at high (1080 px, about 2,350), p90 0.4 to 0.9 s, a tail of 1.5 to 2 s now and then, a 503 "Decision inference is unavailable" twice in 150 requests. Hand on the plate as 0 or 1; the brick in the hand right where the camera's colour is plain, a 0.3 to 0.6 confidence where it is not (lime read as yellow, as terra reads it); the step count agreeing with terra on 37 of 40 looks at high and 40 of 40 at low; "exactly as the step says" 0.84 to 0.93 on a right placement and 0.0 to 0.25 on the misplaced white 1x6 of the 2026-10-28 gate call; the direction of the misplacement random, at high and with the step's rendered picture as reference too; ten questions in one request lowering the count's confidence from 0.8 to 0.4 on the same frames.

## gpt-6.1-terra and gpt-6-luna on the Responses API

- Terra: "a fast, efficient model for visual reasoning"; $1 / $0.05 cached / $5 per million tokens; reasoning effort `none` supported. Luna: "our most efficient model for focused, high-volume tasks"; $0.10 / $0.01 / $0.50. Both 1,050,000 tokens of context, image input, tool calling on the Responses API.
- Fast mode is the old priority tier, twice the price, "up to 2.5x faster" on the model it is quoted for; `service_tier: fast` and `priority` are the same thing. Ultrafast (6x) is for Astra and 6.1 Sol only.
- Image tokens follow the patch formula (width/32 by height/32, times 1.2): a 1080 px square about 1,390 tokens at high, 310 at low (512 px). Our records agree, about 1,450 uncached tokens a look.
- The Responses API has a WebSocket mode (`client.responses.connect()`), a persistent connection with a `response.create` event per request, `store=false` allowed, connections of up to 60 minutes. Measured (`eval/brain-speed/`): 1,335 ms a look against 1,636 over HTTP on the same 30 looks, the same replies; a 768 px image halves the tokens and leaves the time at 1,670 ms; luna as the brain 1,270 to 1,360 ms but heedless of the rules.
- A look's time is in reading the image and the prefix: in the day's device runs looks with the fewest output tokens took 1.8 s and those with the most 2.0 s.

## Sources

- https://developers.openai.com/api/docs/guides/live, `live-prompting`, `live-delegation`, `live-conversations`, `voice-latency-cost`, `api/reference/resources/live/primary-websocket`
- https://developers.openai.com/api/docs/guides/decisions, `decisions-voice`
- https://developers.openai.com/api/docs/models/gpt-6.1-terra, `models/gpt-6-luna`, `docs/pricing`, `guides/fast-mode`, `guides/ultrafast-mode`, `guides/websocket-mode`, `guides/images-vision`, `guides/prompt-caching`
- https://docs.livekit.io/agents/models/realtime/gpt-live/
- https://community.openai.com/t/important-feedback-improvements-for-gpt-live-1-api/1402227 and `/t/1398585`
