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
| `decisions-frames/` | what OpenAI's Decisions API (gpt-6-luna, typed answers only) reads off one of the brain's frames and the step's text: the moment the frame shows, which brick is held, whether the placement is right; on frames picked by hand from the user's own runs of 2026-11-04 and 2026-11-05 |
