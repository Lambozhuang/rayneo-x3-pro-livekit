# Can the Decisions API be the quick eye

This study asks OpenAI's Decisions API, which runs gpt-6-luna and returns typed answers only, a probability for a yes-or-no question and a choice with a confidence, the brain's state questions about a recorded call's photos, and times it. It was run on the evening of 2026-11-04, when the day's device runs had shown the two moments a human instructor answers in half a second, "this one?" with a brick held up and "done" with the hand leaving the plate, taking three to four seconds: up to two seconds until the brain's next look, 1.9 s of model, a second until the voice speaks.

## Question

Does a Decisions request on a camera frame come back fast enough to answer those two moments, and do its answers agree with what the brain saw?

## Material

The first 40 watch looks of `logs/20261104-164445-glasses-ef8ed836/` (the snowman, 2026-11-04 16:44), the photos as the brain was sent them (1080 px), with the task's steps and the lines said since the look before as text. The brain's own reply and set_progress calls at each look are the reference.

## Method

`probe.py <record> --looks 40 --detail high|low` sends each photo to `POST /v1/decisions` with four questions built from the task file: is a hand on the plate (predicate), which brick is in the hand (choice: each step's brick, another brick, none), how many steps are built right counted from step 1 (choice: 0 to the number of steps), is the photo blurry (predicate). It keeps the latency, the tokens and the answers beside the record's reply; `out/summary-<detail>.md` has the figures, `out/<record>-<detail>.json` every look.

## Result (2026-11-04)

| detail | latency median / p90 / max | input tokens median | steps built right agrees with the record |
|---|---|---|---|
| high (1080 px) | 407 / 874 / 2035 ms | 2355 | 37 of 40 |
| low (512 px) | 336 / 442 / 780 ms | 1455 | 40 of 40 |

The hand on the plate comes back as 0 or 1 and follows the record's "pressing the blue plate" and "hands clear" look by look. The brick in the hand is right where the brain was sure (the blue round plate at w10 to w12, the grey at w19 to w23, at 0.9 to 1.0); the lime 1x4 the brain had read as yellow comes back as "step 4" (the yellow 1x4) or "step 3" (the lime) at 0.3 to 0.6, so the colour the camera cannot settle shows as a low confidence rather than a wrong answer. The three disagreements on the count at high confidence 0.5 to 0.6 were the count moving up while the hand still pressed the brick, which the question had asked it not to count. A request costs about 0.015 cents at low.

## The whole battery an eyes-only design would need (2026-11-04, later)

`battery.py <record> [--first w100 --last w124 --step 4] [--detail low|high] [--reference]` asks ten questions a photo: the four above and, for the current step, whether its brick is on the plate, whether it sits exactly as the step says, which way it is off and by how much, its orientation, and where it lies on the desk. The misplacement of the 2026-10-28 gate call (`logs/20261028-162315-glasses-795c9128/`, w107 to w124, the white 1x6 of step 4 one column too far right the whole time, which the replayed terra of `eval/brain-thread-replay/` had read as "one column too far right") is the ground truth; the snowman call's correct placements the control.

| question | on the misplaced white brick | on a correct placement (snowman) |
|---|---|---|
| exactly as the step says (predicate) | 0.01 to 0.19 | 0.84 to 0.93 after the brick is placed, 0.0 before |
| which way off (choice) | "in the right place" at 0.2 to 0.5, "too far left" twice, never "too far right" | - |
| by how many studs (choice) | one, two, three or more, at random | - |
| orientation (predicate) | 0.9 and above, right | right |
| on the plate (predicate) | 0.8 to 1.0 once the hand is off | right |

Detail high (626 ms a request) and the step's rendered picture given as a reference image (453 ms) change none of this: the direction stays random, the "exactly as the step says" probability stays low. Ten questions a request also spread the confidences: the count of steps built right, 0.8 to 0.99 sure with four questions, came back at 0.2 to 0.5 with ten on the same frames, so the battery in use should stay small.

So the model behind Decisions reads the coarse state of the plate, hands and bricks, and tells a right placement from a wrong one, but not where a wrong one should move; those words need the brain's model, which read "one column too far right" on the same frames.

## The eyes' questions at every bitrate (2026-11-05 morning)

`bitrate.py` asks the eyes' own two batteries (`gpt/eyes.py`, four scene and four step questions, 512 px, detail low) about the codec study's 41 frames of the ladder call of 2026-10-27 (`../brain-frame-codec/out/`, exposure -6) as recorded and as decoded from H.265 at 1, 0.5, 0.25 and 0.1 Mbps, and scores them against `../brain-frame-quality/labels.toml` and the study's narrative (the blue rung at the rails' bottom ends in f20 to f25, a white 1x4 where the light aqua one goes in f30 to f35); the task is `ladder-2026-10-27.toml`, the one recorded.

| condition | hand on plate | steps built right | step's brick on plate | position right / wrong / unsure (17 frames) | colour right / wrong / unsure (17) | blurry | same count as recorded | ms |
|---|---|---|---|---|---|---|---|---|
| as recorded | 41/41 | 20/41 | 32/41 | 8 / 6 / 3 | 10 / 4 / 3 | 0 | - | 640 |
| H.265 1 Mbps | 40/41 | 20/41 | 33/41 | 8 / 8 / 1 | 12 / 3 / 2 | 0 | 31/41 | 518 |
| H.265 0.5 Mbps | 41/41 | 23/41 | 33/41 | 8 / 7 / 2 | 14 / 0 / 3 | 0 | 36/41 | 552 |
| H.265 0.25 Mbps | 40/41 | 21/41 | 35/41 | 6 / 9 / 2 | 11 / 2 / 4 | 0 | 34/41 | 530 |
| H.265 0.1 Mbps | 41/41 | 19/41 | 36/41 | 10 / 5 / 2 | 11 / 3 / 3 | 3 | 34/41 | 529 |

The bitrate changes almost nothing: the answers at 0.1 Mbps agree with those on the recorded frames as often as those at 1 Mbps do, and only 0.1 Mbps has the model call any frame blurry (3 of 41). What the table shows instead is the model's own reading of this dark ladder material at any bitrate. The hand is read right on every frame. The count of steps built right is right and sure (0.6 to 0.99) while nothing or one brick is placed, and from two bricks on it is unsure (0.1 to 0.4) and wrong by a pattern: with four or five bricks on the plate it answers 5, counting bricks rather than steps built right, on the misplaced blue rung and on the white 1x4 alike. The position of the misplaced blue rung reads as right at 0.72 and 0.79 on two frames running as recorded, and at 0.87, 0.64, 0.91 on three at 0.25 Mbps, so the step rule as it stood (0.6 on two readings) would have recorded that step done; the bar for the step's own answers is 0.8 now (`RIGHT_STEP`), and the count rule's wrong answers stay under its 0.5 mean. The white 1x4 in the light aqua's place reads as light aqua on two of the six frames at 0.7 to 0.8, so the colour question does not catch a pale brick under this exposure every time either; the finish's confirmation by the brain's model stands between that and a task ended on the wrong brick. The snowman frames of 2026-11-04, under the lab's exposure and with round plates, had read far better (40 of 40 on the count); the lab day of 2026-11-05 shows which of the two these frames resemble.

## What the project does with it

The eyes (`backend/agent/src/gpt/eyes.py`) are built on these limits: the Decisions API reads the frame every 0.7 to 2 s, in two requests of four and three questions, and says what happened in a line of facts the voice puts into words, the current step's brick in the hand, the step done, the brick on the plate but not in its place, two bricks it cannot tell apart; the brain's model is consulted once (`gpt/consult.py`) for the words it cannot produce, what is wrong and how to fix it, and for the wearer's questions about the desk. The first design of the evening, a quick look beside a brain watching every two seconds, went the same evening, after `eval/agent-sim/` ran the three parts together.
