# How little picture the brain needs

This study finds the lowest resolution and the lowest video bitrate at which the brain's model (Claude Sonnet 5.5) still reads the bricks on the plate correctly, so the glasses send no more video than the model uses and the brain's two look sizes (`BRAIN_SIDE`, `BRAIN_WATCH_SIDE`) rest on a measurement instead of a guess.

## Question

The brain looks at one frame per look: the bottom square of the 1080x1920 frame, scaled to 1080 px for a hand-over and 768 px for a routine look, as a JPEG at quality 85 (`backend/agent/src/frames.py` `bottom_square`, `gpt/brain.py` `_jpeg`). It never sees motion, so the video's frame rate reaches it only as the frame's age and as the bits each frame gets at a given bitrate. Seeing is the same whether a question came with the frame or not, so the study measures seeing alone, with one fixed question, and leaves the two kinds of look out as a variable.

## Material

The recorded call `logs/20261022-091923-glasses-3767797d/` (the flag build, `backend/agent/guides/flag/task.toml`, 231 s, GPT-Live with the brain on Sonnet 5.5): its recording at 15 fps and about 43 Mbps at QP 18–19 (`recording/video.mp4`, 3433 frames, `video.csv`). Earlier runs are not used: their prompts and pictures differed.

## Plan

1. Frames. About 40 frames spread evenly over the recording, so every step of the build and both states, a hand on the plate and no hand, are covered; frames with no plate in view are dropped. The same frames go through every condition.
2. Picture. Each frame is cut and scaled exactly as the brain's photo is: the bottom 1080x1080 square, `Image.thumbnail` to the side, JPEG quality 85.
3. Probe. One fixed prompt for every condition, shaped like the brain's but with no task in it: a role, the direction convention the system uses (the plate as a picture lying in front of the wearer, up is the far edge, vertical means the long side runs up and down), and a fixed shape, one JSON object with an entry per brick: its colour and size in studs, vertical or horizontal, and where it sits relative to the bricks next to it (which brick it touches on which side, which edges are level, how many studs it is offset), or for a brick on its own which region of the plate; where the photo does not let an item be read, "can't tell" in its place instead of a guess, and no entry for a brick wholly under a hand; and a hands field on hands and anything hidden. No step list and no word on what is being built, so the model has to read the plate rather than recognise it.
4. Labels. Every frame gets, in the same words, the bricks on the plate with size, colour, orientation and relation to their neighbours, and whether a hand hides anything (`labels.toml`). A label says only what the frame shows: an item the photo does not let one read, because a hand covers it, is labelled can't tell, and the right reply says can't tell there; a definite value is a guess and counts as wrong even when it matches the brick. Hands are part of a real call, so frames with hands stay in, and saying what cannot be seen is part of what is scored.
5. Conditions, in two groups, each holding everything else fixed:
   - Pixels: side 1080, 768, 512 and 384, from the recording as it is.
   - Bitrate: at the smallest side the pixel group still reads correctly, the recording scaled to that side and re-encoded with x264 as WebRTC would send it (high profile, no B-frames, a keyframe every second, CBR with a VBV buffer, zero-latency tuning) at 4, 2, 1 and 0.5 Mbps, 15 fps; the recording unencoded at the same side as the upper reference.
6. Thinking. Every condition runs first without thinking, as the routine look does (Sonnet 5.5 takes `between_tools` for that). The conditions where correctness starts to fall are run again with adaptive thinking at effort low, as the hand-over does, to see whether thinking recovers what the picture lost. The model is `claude-sonnet-5-5`, one call per frame per condition.
7. Score. Per brick and per item: size and colour, orientation, relation to its neighbours. The first two are compared by script; the relation, written in words, is judged by a person for the same meaning. Each condition reports the three rates and the share of frames read entirely right. From the descriptions the script also derives what the system would need, how many steps are done and whether the current brick is right, against the task file, as a second layer.
8. Out of scope: the frame rate on its own (it acts only through the bits per frame, held at 15 fps here); the gap between x264 and the glasses' hardware encoder, which makes the bitrate bound optimistic and is said so in the result; the decisions the two kinds of look make with what they saw.

Scripts, labels and this README are in git; `out/` holds the frames, the re-encoded videos and every model reply as JSON with its timing and token counts, and is not.

## Method

The scripts run in the order below, with `uv run python` from `eval/` (its `pyproject.toml` has the two libraries they need); every generated file goes to `out/`.

1. `pick_frames.py <recording dir>` takes every 86th frame of `video.mp4`, 40 frames 5.7 s apart, decodes each losslessly to `out/frames/` and cuts it as the brain's photo is cut into `out/sq<side>/` for the sides 1080, 768, 512 and 384; `out/frames.csv` maps each frame id to its index, its second in the recording and the glasses' wall clock. The plate is in view in all 40; f00, the recording's first frame, is left out of the labels and so of the scores, since the camera had not yet set its exposure and the frame is dark.
2. `labels.toml` is what a person read off the 1080 squares, in the probe's own words: for each frame the hands (none, over, on), what they hide, and for each brick its colour, size, orientation and relation to its neighbours, each item either as seen or as can't tell when a hand covers it. A brick wholly under a hand has no line; a brick the hand holds down on the plate is marked `held`. The wearer first placed a white 1x4, the wrong brick, and swapped it for the 1x6 at about 65 s, and first placed the dark grey base about two studs too far right (f33–f35), which the labels record as seen.
3. `probe.py <pictures> <thinking>` asks the model about every frame of one condition with the fixed prompt (`PROMPT` in the script) and the question "Describe the plate.", calling it as the brain does (the same model, the photo first, the prompt as a cached system block, the reply streamed to time the first output), eight calls at a time, one reply per frame into `out/replies/<pictures>-<thinking>/`. The reply is one JSON object (`output_config.format`, `SCHEMA` in the script) in the shape of the labels: bricks with colour, size, orientation and position, and hands; `eval/structured-output-replay/` checked that this form of answer leaves the model's judgements unchanged. `none` is no thinking, which Sonnet 5.5 takes as `between_tools`; `low` is adaptive thinking at effort low.
4. `score.py <condition> ...` matches each reply's bricks to the label by colour and counts for each condition the bricks found, the sizes right, the orientations right, the guesses (a definite value where the label says can't tell), the extra bricks, and the frames read whole (every brick found, every size and orientation right with can't tell counted as a value, nothing extra); then the sizes right by the brick's size, and a matrix of frames by condition with a letter per kind of error. A brick with every item can't tell is rightly left out; a held brick counts as found when the hands text names it. The position and the hands text are not scored by script.
5. `sheet.py <condition> ...` writes `out/sheet.html`, every frame's 1080 square beside its label and the replies of the conditions named, in the label's form, for reading the positions and the hands text, which the script does not judge.

## Result

### Pixels (2026-10-26)

39 frames, one call per frame per condition, `claude-sonnet-5-5`, the reply a JSON object; every reply was valid JSON. "Whole" is a frame with every brick found, every size and orientation right (can't tell included) and nothing extra; "guess" is a definite value where the label says can't tell. `score.py` gives the per-frame matrix.

| condition | whole frames | bricks found | size right | orientation right | guesses | extra | median call | input tokens |
|---|---|---|---|---|---|---|---|---|
| 1080, no thinking | 25/39 | 91/92 | 71/89 | 88/89 | 4 | 0 | 4.4 s | 2516 |
| 1080, thinking low | 25/39 | 92/92 | 66/90 | 89/90 | 5 | 0 | 3.9 s | 2517 |
| 768, no thinking | 23/39 | 90/92 | 66/88 | 87/88 | 4 | 1 | 3.8 s | 1779 |
| 768, thinking low | 21/39 | 90/92 | 56/88 | 87/88 | 4 | 1 | 3.7 s | 1780 |
| 512, no thinking | 14/39 | 88/92 | 40/87 | 82/87 | 4 | 2 | 3.9 s | 1356 |
| 384, no thinking | 18/39 | 86/92 | 46/85 | 82/85 | 2 | 0 | 3.8 s | 1191 |

Sizes read right, by the brick's true size (bricks found whose size shows):

| condition | 1x4 | 1x6 | 2x4 | 2x6 |
|---|---|---|---|---|
| 1080, no thinking | 3/3 | 33/48 | 29/29 | 5/5 |
| 1080, thinking low | 3/3 | 32/48 | 25/29 | 5/5 |
| 768, no thinking | 2/2 | 35/48 | 24/29 | 4/5 |
| 768, thinking low | 2/2 | 29/48 | 20/29 | 4/5 |
| 512, no thinking | 2/2 | 17/47 | 15/29 | 5/5 |
| 384, no thinking | 4/4 | 19/44 | 16/29 | 5/5 |

What the numbers say:

- Which bricks are on the plate, their colours and whether they lie vertical or horizontal are read right at every side: bricks found 91 to 86 of 92, orientation 88 to 82. The side does not decide these.
- Size is what the side decides, and the step is between 768 and 512: sizes right 71 and 66 of about 89 at 1080 and 768, 40 and 46 at 512 and 384; whole frames 25 and 23 against 14 and 18. At 512 and below the 2x4 bricks are read as 2x2 or 2x3 in half the frames and the 1x6 as 1x4 in two thirds; the 2x6 base, the largest brick and nearest the camera, is read right everywhere. 384 scoring a little above 512 is within the noise of 39 frames; both are bad.
- The 1x6 bricks are the weak point at every side: 33 of 48 right at 1080, nearly every miss read as 1x4. This is the model's counting of a long thin brick, not the picture, and it is what the brain said in the live run ("the white brick looks like a 1x4").
- Thinking at effort low is no thinking for this question: adaptive thinking produced no thinking tokens in any of the 80 calls, and the rows are the same within noise (768 low is a few sizes worse). The brain thinks in about two thirds of its live hand-overs because it has tools and a question to answer; a description alone does not make it think. High effort was tried in the first run (9.8 s a call, no better at counting) and is out of consideration.
- Guesses: 4 or 5 per condition at every side, the same frames each time (f06, f36, f37): where a hand covers the end of a brick the model gives a definite size rather than can't tell, whatever the picture quality. Saying can't tell is a matter of the prompt and the model, not of pixels.
- The first run, with the reply as free text and a parser, scored sizes lower at every side (55 of 86 at 1080, 2x4 24 of 29 against 29 of 29 here). Its replies are kept in `out/replies-prompt1/` and `out/replies-hidden/` and are not reported; the two runs differ in prompt, labels and output form at once, so the difference is not attributed.

Tokens and time, medians over the 39 frames without thinking:

| side | photo | input tokens | output tokens | first output | whole call |
|---|---|---|---|---|---|
| 1080 | 246 KB | 2516 | 294 | 1.73 s | 4.37 s |
| 768 | 122 KB | 1779 | 287 | 1.48 s | 3.75 s |
| 512 | 54 KB | 1356 | 309 | 1.06 s | 3.90 s |
| 384 | 30 KB | 1191 | 300 | 1.06 s | 3.77 s |

The photo's share of the input is about side² / 750 tokens (1550 at 1080, 790 at 768, 350 at 512, 200 at 384); the rest, about 950, is the prompt. The side only moves the time to the first output, by 0.7 s from 1080 to 384; the output, about 300 tokens at about 135 tokens a second, takes 2.2 s whatever the side, so the calls all take about 4 s. A smaller picture buys little time once the reply is this long; the brain's live routine looks reply much shorter and take 2.8 s.

What the project does with it: 768 reads as well as 1080 within a few bricks and nothing in the picture is lost going from 1080 to 768, so the hand-over's `BRAIN_SIDE` can drop to 768 and the video needs no more than 768 px across the plate's square; 512 loses the sizes. Counting the 1x6 is a model limit at every side and has to be met in the task or the prompt, not with pixels. The bitrate group follows at 768.
