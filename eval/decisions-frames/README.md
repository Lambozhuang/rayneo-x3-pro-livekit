# What the Decisions API reads off one frame

This study asks whether OpenAI's Decisions API (`gpt-6-luna`, typed answers only) can tell, from one of the brain's photos and the task's text, which of the moments of a build the photo shows and whether the current step's brick is held, placed and placed right. It was set up on the evening of 2026-11-05, before the Decisions path is designed a second time, so that the questions are chosen on measured answers rather than on the run of 2026-11-04.

## Question

Given one 1080 px frame and the step's text, how reliably does the API answer the eight questions a single frame can settle: is the plate in view, is a hand on it, is a brick held, is it the step's brick, is the step's brick on the plate, is it placed right, what is wrong with it, and which way it has to move.

## Material

`logs/material-2026-11-05/situations/`, ten frames picked by hand from calls the user ran themselves on 2026-11-04 and 2026-11-05 without the lab console and with the connection excellent throughout, one or three frames for each of seven moments: nothing happening, the step's brick held, another brick held, a hand pressing a brick on the plate, the step placed right, the step wrong (orientation, one row too low, a gap one column too wide), and a picture that cannot be read (the plate out of view, the hand and brick smeared by motion). `situations.toml` lists them with the task, the step the builder was on and the answers a person gives from the frame; what a person cannot settle from the frame is left unscored.

A second frames file for the brick types (which brick is held) comes later; the folder `logs/material-2026-11-05/bricks/` holds its twelve frames.

## Method

`probe.py situations.toml [--detail low|high] [--reference] [--dry]` sends one request a frame: a developer message written from the task file (the scene, the direction words, the build's bricks, the steps placed before, the current step), the frame as a user image, and the same eight questions every time, seven predicates and two choices; `--reference` adds the step's rendered picture before the frame, `--dry` prints the texts and sends nothing. A predicate counts as yes at 0.5 and above; `off_direction` is read only when the frame's wrong_how is "wrong position", since the questions are answered independently and a dependent question is resolved on our side. The answers, the time and the usage of every request go to `out/`, with a table of expected against got.

## Result (2026-11-05 evening, from the user's home over one kept connection)

| run | frames | scored answers right | request time median / max | input tokens median |
|---|---|---|---|---|
| situations, 1080 px, detail high | 10 | 47 of 57 | 735 / 1626 ms | 2610 |
| situations, 720 px, detail high | 10 | 49 of 57 | 412 / 1060 ms | 1979 |
| situations, 512 px, detail low | 10 | 49 of 57 | 469 / 1136 ms | 1710 |
| bricks, 1080 px, detail high | 12 | 34 of 36 | 566 / 1824 ms | 1895 |
| bricks, 720 px, detail high | 12 | 34 of 36 | 510 / 999 ms | - |

The moment a frame shows is read right at every size: the plate in view, a hand on the plate and the step's brick on the plate with no hand on it were answered right on every scored frame of every run, at 0 or 1 with almost nothing between, and the step's brick on the plate was 1.00 on the three misplaced bricks as on the right one, which is what a trigger for the placement check wants. A brick held in the air was read right on all but the frame of an empty hand resting at the plate's edge (0.69 at 1080, 0.80 at 512, 0.01 at 720) and the frame of a hand pressing a brick onto the plate (0.58 to 0.62, 0.27 at 512), where the hand does touch a brick.

Whether a placement is right is not read: "placed exactly as the step describes" was 0.84 to 1.00 on all four placed frames, the three wrong ones included, and "what is wrong" caught only the brick standing vertical instead of horizontal (0.43 to 0.62); the rung one row too low and the gap one column too wide came back as "nothing" at every size, and the direction to move was wrong or refused. The step texts ask for counting studs and comparing positions, which this model answers in one pass without checking.

Which brick is held reads well: the choice over the task's bricks named 11 of 12 at 1080 px (the lime 1x4 as the yellow one, 0.93) and 12 of 12 at 720 px (lime at 0.80, tan 1x6 at 0.54). The predicate "the held brick is the current step's brick" was less steady than the choice on the same frames: 0.06 on the dark grey 2x6 at 1080 px, 0.24 and 0.25 on the tan 1x6 and the dark grey 2x6 at 720 px, 0.55 to 0.64 on the lime, and it also gives high values when no brick is held (0.88 on two situation frames), so it can only be read when a brick is held. The frame with the hand and brick smeared by motion got 0.64 to 0.83 for the step's brick, not a value near the middle.

## What the project does with it

The Decisions API takes the moments: whether the plate is in view, whether a hand is on it, whether a brick is held and which, and whether the step's brick lies on the plate with the hand gone, which is the moment the brain's model is asked to judge the placement. The placement itself stays with the brain's model. The frame goes at 720 px, which answered as well as 1080 px in half the time. The design of the evening of 2026-11-05 is in `docs/design/2026-11-05-two-lines.md`.
