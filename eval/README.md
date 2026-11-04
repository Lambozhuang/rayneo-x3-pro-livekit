# Small studies

This directory holds the small offline studies that settle one design question each before the experiment, such as how little picture quality the vision model can work with. Each study is one directory named after its question, and everything that study needs sits inside it: its README, its scripts, its labels and the summary of its result. Studies read their material from `logs/` (call records and the glasses' recordings, not in git) and write their generated files to their own `out/`, which git ignores; what is kept is the code, the hand-made inputs and the written result.

A study's README says, in order: the question, the material used (which run, which frames), the method step by step as the scripts run it, the result with the numbers that matter, and what the project does with the result. It is written when the study ends, so the next reader does not have to rerun it to know what it found.

| study | question |
|---|---|
| `brain-frame-quality/` | how few pixels and how low a video bitrate the brain's model (Claude Sonnet 5.5) can judge a build from, measured on frames of a recorded call |
| `brain-frame-codec/` | what the video's bitrate costs the brain's model when the video is encoded as the glasses encode it, in H.264 and in H.265, on the second material of `brain-frame-quality/` |
| `structured-output-replay/` | whether asking the brain's model for one JSON object instead of tool calls changes what it decides, by replaying a recorded call's looks |
| `brain-thread-replay/` | whether the brain, keeping one conversation of its own (2026-10-29), holds the progress where the plate says it is, by replaying the looks of the 2026-10-28 call in which it flipped eight times |
| `voice-script/` | whether GPT-Live, with the voice's prompt, carries a scripted build conversation as designed (says where the brick goes once the brain says it is the right one, says a step is done when the progress moves, waits when the brain has not looked yet), with no glasses, brain or camera |
| `brain-blur-perception/` | whether the brain's model can tell from the photo alone that the picture has gone poor, on the codec study's frames at five rates and on real frames of an open and a 0.25 Mbps call, so that it can remark on it itself instead of being fed the stream's bitrate |
| `brain-speed/` | which of the image's size, a persistent WebSocket to the Responses API and the cheaper gpt-6-luna shorten the brain's look, on 30 looks of a recorded call: the WebSocket takes 0.3 s off, the size nothing, and luna does not keep to the rules |
| `brain-decisions/` | what the Decisions API (gpt-6-luna, typed answers, 0.3 s a reading) reads off the camera frame: the hand, the brick in the hand, the step count, a right placement from a wrong one, but not where a wrong one should move; the eyes of `gpt/eyes.py` are built on it |
| `agent-sim/` | whether the whole agent, GPT-Live, the eyes and the consult, holds together without the glasses, on a recorded call's photos and the wearer's lines played at their times |
