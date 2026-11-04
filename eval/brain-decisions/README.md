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

## What the project does with it

The quick look (`backend/agent/src/gpt/quick.py`) asks these four questions about the newest frame once a second at detail low, and acts on two readings in a row at 0.7 confidence or better: the current step's brick in the hand is told to the user, and a higher count with no hand on the plate moves the progress. A hand leaving the plate without the count moving wakes the brain for a look. The brain gets every reading in its next message as a hint with its confidence, the colour question included.
