# Where the brain's look can be made faster

This study times the brain's model under the levers OpenAI's documentation offers, on the looks of a recorded call, to see which of them shorten a look without changing what the brain decides. It was run on the evening of 2026-11-04, after the day's device runs had the brain at 1.9 s a look (median, effort none, priority tier) with the time spent on reading the photo rather than on writing: looks with the fewest output tokens took 1.8 s and those with the most 2.0 s.

## Question

Of the image's size (1080 or 768 px a side), the transport (one HTTP request a look, or one persistent WebSocket to the Responses API with a `response.create` event a look) and the model (gpt-6.1-terra, or the ten times cheaper gpt-6-luna), which shorten a look, and does the brain still say and record the same?

## Material

The first 30 watch looks of `logs/20261104-164445-glasses-ef8ed836/` (the snowman, 2026-11-04 16:44): the photos as the brain was sent them (1080 px, the bottom square) and the lines said at each look, read from the record as `eval/brain-thread-replay/replay.py` reads them.

## Method

`probe.py <record> --looks 30 --variants ...` runs each variant as one conversation of its own through the brain's code (`backend/agent/src/gpt/brain.py`), the 30 looks in the record's order, with today's prompt, effort none and the priority tier, so every request has a call's shape: the instructions, every look so far, the newest photo. For 768 the record's photo is scaled down and re-encoded as the brain would encode it. The WebSocket variant uses `brain.py`'s `OpenAIWsModel`, written for this study and kept. Per look it keeps the model's wall time, the tokens and the tool calls beside the record's; `out/summary.md` has the table.

## Result (2026-11-04)

| variant | model ms median / p90 / max | uncached tokens median | set_progress calls in 30 looks | says |
|---|---|---|---|---|
| the record, as it ran (terra, 1080, HTTP) | 1716 / 2453 / 3353 | - | 2 | 6 |
| terra, 1080, HTTP | 1636 / 2114 / 4213 | 1437 | 2 | 6 |
| terra, 768, HTTP | 1670 / 2185 / 2418 | 744 | 2 | 6 |
| terra, 1080, WebSocket | 1335 / 1692 / 2987 | 1436 | 2 | 7 |
| luna, 1080, HTTP | 1364 / 1764 / 2061 | 1475 | 4 | 26 |
| luna, 768, HTTP | 1268 / 1707 / 2017 | 785 | 9 | 20 |

The image's size does not change the time: 768 halves the tokens and leaves the look at 1.7 s. The WebSocket takes 0.3 s off every look, the same replies. Luna is faster still but does not keep to the brain's rules: it spoke at 20 to 26 of 30 looks where terra spoke at 6, and moved the progress 4 to 9 times where the plate moved twice.

## What the project does with it

The brain's OpenAI calls go over the WebSocket (`BRAIN_TRANSPORT=ws`, `gpt/brain.py` `OpenAIWsModel`); the photo stays at 1080 px; terra stays the brain. Luna's speed is used another way: as the quick look, answering typed questions through the Decisions API (`eval/brain-decisions/`).
