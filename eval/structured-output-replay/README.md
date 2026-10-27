# Does structured output change what the brain decides

This study checks whether asking the brain's model for a JSON object instead of tool calls changes its judgements, before the frame-quality study (`eval/brain-frame-quality/`) adopts structured output for its probe.

## Question

The brain answers with free text plus tool calls (`set_progress`, `note`, `say`). A test that wants reliable scoring would rather have the same decisions as fields of one JSON object (`output_config.format` on the Messages API). If the model decides the same things either way, the format is a constant and the test can use it; if the JSON version decides differently in a pattern, the test has to stay with free text.

## Material

The 62 looks of the recorded call `logs/20261022-091923-glasses-3767797d/` (58 routine looks, 4 hand-overs): for each, the record holds the exact input the brain sent, the call so far, the progress line and the words, the photo at the side it was sent (`watch<w>-s<step>.jpg` at 768, `ask<n>-s<step>.jpg` at 1080), the system prompt (`brain.txt`), the tool definitions (`brain-tools.json`), and what the model replied and called.

## Method

`replay.py <record dir>` sends every look again with the same model, the same system prompt, the same three text parts and the same photo, and the same thinking setting (none for a routine look, low for a hand-over), but with no tools: the reply is one JSON object whose fields are the three tools' arguments and the reply text (`SCHEMA` in the script), and the system prompt gets one appended paragraph saying so. Replies go to `out/<id>.json`. `compare.py <record dir>` puts each look's original decisions beside the replayed ones: the `set_progress` value, the number of notes and says, and the reply text, and counts the looks where they agree.

The model is not deterministic, so single disagreements mean nothing; what would count is disagreement in a pattern, such as progress moving at different looks or notes appearing where none were.

## Result (2026-10-26)

All 62 looks came back as valid JSON on the first try, the routine looks with `between_tools` and the hand-overs with adaptive thinking at low effort, so the schema (a nullable object, two arrays, a string) and both thinking settings work with `output_config.format`.

| decision | looks where the replay agrees with the original |
|---|---|
| `set_progress` value | 61 of 62 |
| whether to `say`, and how many | 62 of 62 |
| whether to `note`, and how many | 48 of 62 |
| all three | 48 of 62 |

The 14 note disagreements go both ways, 8 where the original noted and the replay did not, 6 the other way, and the notes themselves are of the same kind on both sides: a brick held in the hand and not yet placed, or the plate unchanged with the next brick not yet down. Whether such a fact is worth a note is the model's threshold, and it falls differently from call to call; nothing ties the disagreements to a step, to hands on the plate or to the kind of look. The one progress disagreement is the last look (w62, 223 s): the original noted all five steps right, the replay set the progress back to 4 and had the voice say the dark grey base sat wrong; the base's offset in that frame is the item the frame-quality labels could only give to within a stud.

The replay's `reply` field is mostly the word nothing where the original wrote a sentence of reasoning before its tool calls; the field was described as the reply text, and with the decisions already in their own fields the model had little to put there. This is a change of what the text says, not of what was decided.

Timing is not comparable from this run: the replay ran 16 calls at a time and its routine looks took a median 5.1 s against 2.8 s live, but the one look sent alone as a smoke test took 3.0 s with the same format, and the cache hit rate was the same as live (57 of 58), so the slowdown is the concurrency, not the format.

What the project does with it: asking for one JSON object instead of tool calls leaves the brain's decisions where they were, within the model's own call-to-call variation; the frame-quality study can take its probe's answer as a JSON object and score the fields directly, without a parser. This is an inference across tasks, since the probe asks for a description and the brain for decisions, and the result is stated as such there.
