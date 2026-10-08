# Brain: offline look tests (2026-10-08)

What the brain (`backend/agent/src/gpt/brain.py`) does with one look: the wearer's words, the current step and
one camera frame in; a reply for the voice and, in the tool version, `confirm_step_correct` / `end_call` out.
Each look here is standalone: a new brain per case, the conversation holds one line (the voice just read the
current step). Nothing about Live's wording or a whole session is tested here.

## Material

`frames/`: 12 frames from the last full lab run (2026-10-07, call stream 1080x1920 portrait), labelled by eye;
local only (`eval/**/frames/` is not in the repo), copied from that run's frame dump.
`cases.py`: 15 cases on them, A-L "is it right?" at a step (6 correct: A C F H K L; 4 placed wrongly: B E G J;
2 not placed: D I), M-O general questions written for the test (what is in my right hand; how many red pieces;
are the wheels the same size). The truth is the step after the answer (moved on or not) and the gist of a right
answer. `states.py`: the actual plate state of each frame as bricks, for the "perfect view" drawings.

## Runs

Each case 2x (JSON era) or 3x (tools era, M skipped in the two perfect-view runs). Latency is the model call:
median / p90 / max, seconds. "Moved on" counts A C F H L, "stayed" B D E G I J K, "kept" M N O (step unchanged). K was first
labelled correct (the old judge passed it); the wearer checked on 2026-10-08 that the right wheel sits four
columns from the left one where the plan says three, so K's right answer keeps the step, and every run is
counted that way (in the perfect-view drawing K follows the plan, so there confirming is right).
"Wrong confirm" is a confirm call on B D E G I J K (the code drops one with a missing step number, as in
sonnet-v3b). Results per call, with the model's text, in `results/<run>.json`.

| run | what changed | latency s | moved on | stayed | kept | steps right | wrong confirm | end_call |
|---|---|---|---|---|---|---|---|---|
| sol-1024 | gpt-6-sol, JSON, whole frame 1024, old wording | 2.5 / 3.4 / 4.8 | 1/10 | 14/14 | 6/6 | 21/30 | - | 0 |
| haiku-1024 | Haiku, JSON, whole frame 1024, old wording | 1.5 / 2.0 / 3.0 | 2/10 | 14/14 | 6/6 | 22/30 | - | 0 |
| haiku-1568 | Haiku, JSON, whole frame 1568, old wording | 1.6 / 2.4 / 2.6 | 4/10 | 14/14 | 6/6 | 24/30 | - | 0 |
| haiku-1024-v2 | Haiku, JSON + per-fact checks, whole frame 1024 | 1.5 / 2.4 / 3.3 | 3/10 | 14/14 | 6/6 | 23/30 | - | 0 |
| haiku-1024-w2 | Haiku, JSON, whole frame 1024, new wording | 1.5 / 2.4 / 2.8 | 3/10 | 14/14 | 6/6 | 23/30 | - | 0 |
| haiku-1024-w2ref | ... + top-down reference drawing | 1.5 / 2.2 / 2.4 | 7/10 | 9/14 | 6/6 | 22/30 | - | 0 |
| haiku-1024-w2-low | ... new wording, reasoning low | 2.4 / 5.0 / 6.2 | 7/10 | 12/14 | 6/6 | 25/30 | - | 0 |
| haiku-1024-w2ref-low | ... + reference, reasoning low | 1.5 / 3.7 / 6.2 | 7/10 | 14/14 | 6/6 | 27/30 | - | 0 |
| haiku-sq-w2 | Haiku, JSON, bottom square 1024, new wording | 1.5 / 2.1 / 2.4 | 8/10 | 13/14 | 6/6 | 27/30 | - | 0 |
| haiku-sq-w2-low | ... reasoning low | 2.1 / 5.0 / 8.0 | 9/10 | 14/14 | 6/6 | 29/30 | - | 0 |
| haiku-final | ... + unsure rule (JSON era final) | 1.8 / 2.3 / 2.5 | 8/10 | 12/14 | 6/6 | 26/30 | - | 0 |
| haiku-drawing | perfect view: drawing of the plate state instead of the photo | 1.3 / 2.0 / 2.3 | 15/15 | 18/21 | 6/6 | 39/42 | - | 0 |
| haiku-plate | perfect view: plate cut out and scaled up | 1.5 / 2.2 / 2.3 | 10/15 | 21/21 | 6/6 | 37/42 | - | 0 |
| haiku-tools | Haiku, tools, first tool prompt | 1.3 / 1.7 / 2.6 | 15/15 | 18/21 | 9/9 | 42/45 | 3 | 2 |
| haiku-tools2 | Haiku, tools, emphatic rules repeated in the system prompt | 1.6 / 2.0 / 2.8 | 13/15 | 15/21 | 6/9 | 34/45 | 6 | 1 |
| haiku-tools2-low | ... reasoning low | 2.7 / 6.0 / 7.3 | 14/15 | 18/21 | 9/9 | 41/45 | 3 | 3 |
| haiku-v3 | Haiku, tools, rewritten prompt (v3), square 1080 | 1.5 / 2.1 / 2.8 | 13/15 | 18/21 | 9/9 | 40/45 | 3 | 0 |
| haiku-v3-medium | ... reasoning medium | 3.1 / 5.9 / 9.2 | 14/15 | 20/21 | 9/9 | 43/45 | 1 | 0 |
| haiku-v3b-low | ... examples reformatted, reasoning low | 2.8 / 5.0 / 5.8 | 12/15 | 20/21 | 9/9 | 41/45 | 1 | 1 |
| sonnet-v3b | Sonnet 5.5, v3, between_tools | 2.2 / 3.2 / 7.3 | 14/15 | 21/21 | 9/9 | 44/45 | 1 | 0 |
| sonnet-v3c | Sonnet 5.5, v3 + plain examples + strict tools, between_tools | 2.7 / 4.5 / 6.5 | 13/15 | 18/21 | 9/9 | 40/45 | 3 | 0 |
| sonnet-v3c-low | ... reasoning low | 2.0 / 3.0 / 5.0 | 8/15 | 21/21 | 9/9 | 38/45 | 0 | 0 |
| haiku-v5-medium | Haiku medium, v3 + 'when the wearer disagrees' rule, no end_call (repo now) | 3.6 / 6.3 / 15.2 | 15/15 | 21/21 | 9/9 | 45/45 | 0 | 0 |

## What we learned

- **Image.** The whole portrait frame scaled to 1024 gives ~15 px per stud and both Haiku and gpt-6-sol call
  nearly every correct step wrong. The frame's **bottom square** (the table; the top of the portrait frame is
  wall) doubles that to ~27 px and fixes most of it. Sent at 1080, the stream's own size. Cropping to the plate
  was not wanted (general questions need the rest of the table) and was worse anyway: scaled up, lime reads as
  yellow and edges blur.
- **Wording.** One direction vocabulary in the task and both prompts: the plate as a picture in front of the
  wearer, up = far edge, left/right theirs, a brick vertical or horizontal. "front to back / further up /
  toward you" mixed three frames and the model read "up" as height.
- **Perception vs judgement.** With a perfect drawing instead of the photo Haiku got everything right but J
  (column counting, it echoes the facts). The errors left on photos are mostly not seeing clearly, so "not sure,
  bring it closer" is the right fallback.
- **Reference drawing** (eval/truck/refs) next to the photo: biased toward "right" and got mixed up with the
  photo. Dropped.
- **Tools vs JSON.** Tools (`confirm_step_correct`, `end_call`) keep general questions and unsure answers from
  touching the state. Without reasoning Haiku sometimes says "not right" and confirms anyway, and once hung up
  on a finished build. Repeating the tool rules in the system prompt with emphatic wording made it much worse
  (haiku-tools2): the rules belong in the tool descriptions only, in plain words (Anthropic's prompting docs).
- **Prompt v3** (repo now): XML sections, reasons instead of bare rules, a cautious default for acting, four
  examples, image before text. Example labels get copied: "Reply:" and `tool="none"` showed up in replies and
  as a call to a tool named none; the examples now carry no tool marks.
- **Reasoning.** Haiku medium is the most accurate and safe (42/45, no wrong confirm, no hang-up, short
  replies) but slow (p90 ~6 s, max 9 s; BRAIN_TIMEOUT is 12 s for this). Haiku low hung up once. Sonnet 5.5
  cannot turn thinking off (`between_tools` is the floor): without up-front thinking it reasons in the reply
  text (coordinates and all) and confirmed J twice; Sonnet low is fast, clean and never confirmed a wrong
  step, but confirmed only 8 of 18 correct ones. K (wheel gap) stays the hardest case for every setup.

## Replays of the whole run

`replay.py`: the run of 2026-10-07 in order through one brain, the timeline building up (the wearer's 17 real
utterances plus a synthetic "Is it right?" where the old loop saw a step done or wrong; Live's lines left out;
each ask gets the first judged frame after it). Haiku medium. Results in `results/replay-*.json`.

| run | prompt | where it ended | latency median / max |
|---|---|---|---|
| replay-haiku-medium (2 runs, same outcome) | v3 | stuck at step 5 from 175 s: two white 1x6 side by side read as one, every later ask "no second white brick", the wearer's "I just did" ignored | 2.9 / 7.5 s |
| replay-haiku-medium-pushback | v3 + "when the wearer disagrees" (with end_call) | after the inserted "are you seeing the two as one?" it negotiated, confirmed step 5 two asks later and caught up one step per ask to step 9; stopped at step 10, rightly (the wheel gap really was wrong); one spurious end_call with an empty reply | 4.2 / 9.1 s |
| replay-v5-pushback | same rule, no end_call (repo now) | far more "can't confirm, bring it closer": step 4 doubted twice (white or cream? five or six studs?), confirmed only at 235 s, then step 7 doubted to the end | 5.2 / 10.3 s |

A replay cannot reward "bring it closer": the recorded wearer never does, the next frame is no closer, and the
brain falls behind while the wearer builds on; later bricks then confuse its check of the current one ("step 4
needs only the single upper white 1x6, remove the extra white pieces"). The disagreement rule's note that the
camera washes out light colours also seems to make the brain doubt white bricks in general, and it thinks more
(median output 760 tokens in the last replay against ~400 before). Single looks did not show either effect
(haiku-v5-medium 45/45).

## To try on the glasses

Configs worth comparing live (all in `.env`, no rebuild): `BRAIN_PROVIDER=anthropic` with
`BRAIN_MODEL=claude-haiku-5-5` and `BRAIN_EFFORT=medium` (most accurate), `low`, `none`; and
`claude-sonnet-5-5` with `low`. The offline numbers say nothing about how long a wait feels or how Live words
the reply.

## Rerun

From `backend/agent` (keys from `backend/.env`; the model id comes from the named env var):

    uv run python ../../eval/brain/run.py anthropic BRAIN_MODEL 1080 3 ../../eval/brain/results/<run>.json medium
    uv run python ../../eval/brain/run.py anthropic BRAIN_MODEL 1080 3 <out>.json none drawing   # perfect view
    uv run python ../../eval/brain/report_tools.py    # HTML of the tool-era runs -> tmp/brain-report/

`run.py` runs the repo's brain code as it is; the JSON-era runs used earlier versions of it (git history).
