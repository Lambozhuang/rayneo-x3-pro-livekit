# Does the brain hold its judgement when it keeps its own conversation

This study replays a recorded call through the brain as rewritten on 2026-10-29, which keeps one conversation of its own instead of a transcript rebuilt for every look (`backend/agent/src/gpt/brain.py`), to see before a device run whether the model APIs take the conversation's shape and whether the progress still flips as it did in the recorded call.

## Question

In the call `logs/20261028-162315-glasses-795c9128/` (the gate, gpt-6.1-terra at effort low) the recorded progress went 4, 3, 4, 5, 3, 5, 3, 5 between 267 s and 335 s while the white 1x6 lay one column too far right the whole time: the brain saw the recorded progress contradict its own last note and "corrected" it, because its own set_progress calls were not in the transcript it was given. Does the same model, given the same photos and the same lines said, with its own earlier replies, tool calls and their results in front of it, keep the progress where the plate says it is?

## Material

The record's looks from w100 (245 s) to the end (w144, 339 s): 43 routine looks and the hand-overs n5 and n6, 45 looks with a photo and a reply. Each look's photo is the bottom square the brain was sent at the time (`watch<w>-s<step>.jpg`, `ask<n>-s<step>.jpg`, 1080 px); the lines the user and the assistant had said by each look are read from the record's call-so-far text, the brain's own lines of the time left out. The guide is `backend/agent/guides/gate/task.toml` as it is now; the prompt is today's `gpt/prompts.py`.

## Method

`replay.py <record dir> [first look] [last look]` runs the brain's code itself with the record's model and effort, nothing else behind it: a stand-in history fed the record's lines as they became known, a stand-in camera handing out the record's photo, a stand-in voice keeping the appends, a stand-in room taking the picture bytes. Starting at w100, the first message carries every line said up to then, as the first look of a call does, and the progress is set to the record's at that look (3). Looks run one after the other, each request the whole conversation plus the new look, the reasoning items passed back encrypted (`store=False`). Replies land in `out/<id>.json`, the readable whole in `out/transcript.md`, and the replayed progress beside the record's in `out/summary.txt`; from the second run on, the brain's own record of the replay (`out/<time>-<room>/events.jsonl`) holds every request's tokens.

The model is not deterministic, and the replayed brain reads its own words rather than the recorded brain's, so single looks are not comparable; what counts is the course of the progress and whether the requests go through.

## Result (2026-10-30)

Both shapes of request went through: 48 requests to the Responses API (a smoke test of w1 to w3, then w100 to w144), the conversation growing to 46 looks, the reasoning items and the function call outputs passed back without an error.

| | record (2026-10-28) | replay |
|---|---|---|
| set_progress calls from w100 | 8, the progress 3, 4, 3, 4, 5, 3, 5, 3, 5 | 1, at w101, `done=3`, which was unchanged |
| progress at the end | 5, the build announced finished | 3, the white brick still one column too far right |
| says | 3 confirmed, 5 held and dropped | 3 (w107, w113 with the picture offer, w119), none dropped |
| model time per look | median 2.1 s | median 2.9 s, p90 3.8 s, one 18.4 s (w110) |

The replayed brain read the plate right from w107 on ("three columns too far right", then "one column too far right" after the user moved it at w113) and kept saying so for 30 looks while the recorded brain, and the assistant with it, declared the build finished at w119: at w123, given the assistant's line "All five steps are done. The gate's finished.", it wrote "The gate is not finished: the white brick still extends two columns past the blue brick, rather than one." At n6 ("I'm pretty sure we didn't do it right") it answered "You're right" with the same correction, without a set_progress call, since the progress already stood at 3.

Five replies were a tool call with no text (n5's show among them, where the prompt asks for a sentence on what to look at in the picture); the result of each call told the next look what had happened, which is what the conversation is for. The thinking append is one short sentence per look, 4343 characters of message text over the 45 looks. Token counts were not kept in this run (the brain's record was added to the script afterwards); they are the first thing to read off the next replay or the device run.

What the project does with it: the conversation goes to the device as it is; the flipping had its cause in the context, not in the model's eyes, and a limit on set_progress is not added. Still open for the device run: the growth of the input tokens over a whole call, the effect of a thinking append every look on GPT-Live, and whether the filler GPT-Live says after a hand-over survives.
