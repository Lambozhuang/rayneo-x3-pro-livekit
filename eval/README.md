# Small studies

This directory holds the small offline studies that settle one design question each before the experiment, such as how little picture quality the vision model can work with. Each study is one directory named after its question, and everything that study needs sits inside it: its README, its scripts, its labels and the summary of its result. Studies read their material from `logs/` (call records and the glasses' recordings, not in git) and write their generated files to their own `out/`, which git ignores; what is kept is the code, the hand-made inputs and the written result.

A study's README says, in order: the question, the material used (which run, which frames), the method step by step as the scripts run it, the result with the numbers that matter, and what the project does with the result. It is written when the study ends, so the next reader does not have to rerun it to know what it found.

| study | question |
|---|---|
| `brain-frame-quality/` | how few pixels and how low a video bitrate the brain's model (Claude Sonnet 5.5) can judge a build from, measured on frames of a recorded call |
| `structured-output-replay/` | whether asking the brain's model for one JSON object instead of tool calls changes what it decides, by replaying a recorded call's looks |
