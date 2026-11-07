# The glasses show the agent as five dots that move with the conversation (2026-11-06)

This note records the call screen agreed on 2026-11-06, drawn as mock-ups on a monitor while the API credit was out, and what it is for: the wearer should see the agent register their words and their hands the instant it does, so that the wait for the voice is felt as a wait and not as nothing happening.

## What was wrong

The screen until then had two columns drawn for the captions, the build's at the left and the agent's at the right, and the captions had gone on 2026-11-05; the right column held a framed word, "Listening" or "Speaking" with a dot, and nothing else. The word had to be read while the wearer's eyes were on the bricks, and it came late: "Listening" from the SFU's speaker detection, "Speaking" from the agent's state attribute over the signalling channel, both well after the sound itself. Nothing at all changed on the screen in the stretches that make the system feel slow: between the wearer finishing a sentence and the voice starting, between a brick picked up and the voice saying whether it is the step's, and the two to four seconds between a brick put down and the brain's verdict.

## What the wearer sees now

| Moment | The dots | What drives them | How much earlier than before |
|---|---|---|---|
| The mic is open, nothing is happening | five dim grey dots, breathing | the agent is there and the mic is on | unchanged |
| The wearer speaks | white bars rising with the voice | the microphone's level on the glasses | a few hundred ms, and no network in between |
| The wearer has finished and no reply has come | a white light running along the dots | the mic's burst has ended and no sound has come from the agent since | this state did not exist |
| The agent speaks | blue bars moving with the voice | the decoded audio's level on the glasses | in step with the sound at the ear |
| The agent has judged the brick in the hand | all five dots green or red, fading over 1.2 s | the attribute `rayneo.agent`, set the instant the second line sends its commentary | 0.65 to 0.85 s before the voice, which is GPT-Live's reaction time |
| A brick is down and the brain judges it | a blue light running along the dots | `rayneo.agent` reads "looking" from the look's start to its verdict | the whole judgement, several seconds, was invisible |
| The connection is lost, the agent is gone | amber or red dots blinking, and a line of words above them | the SDK's connection and agent states, as before | unchanged; these are the only states that keep words |

The rule under the table: whatever the glasses can know locally they show from the sound itself, and whatever only the agent knows it tells them the instant it knows, so the dots always lead the voice. The wait is not hidden: the running light lasts exactly as long as the reply takes, and a high-latency network shows as a longer run, which is what the slice experiments will vary.

## The layout

A band along the top: the title and the time left over a line, the step list from the left edge to a square at the right, every step on one line (the longest name takes under 200 dp of the 400 available), and in the square what the camera sees or, while the agent names one, the agent's picture. Under the band the eye is clear down to the dots along the bottom edge, in the middle, so the lower part of the eye, where the wearer sees the plate, holds only the five small dots.

The user chose this from mock-ups drawn with PIL at the panels' 640x480 (scratch, outside the repo): three forms for the element (a ring, a glowing orb, a row of dots) in nine states each and an animated scene for each; then five layouts, the old one and four that keep the lower middle clear. The dots were picked as the most natural; among the layouts, the band with the dots along the bottom edge, with the step list widened so no name wraps. The camera and the picture now share one square: the two squares of the old layout were a reason it was left-heavy, and while the picture is up the wearer looks at the picture and has the real table in front of them.

## Mechanics

On the glasses, `SpeechEdgeLog` (the two audio sinks that already time the wearer's last loud frame and the agent's first) now also keeps a level, the frame's RMS against a full scale of 4000 with its square root taken, rising at once and decaying over about 150 ms. `Voices.kt` samples the two sinks once a frame for who is sounding and for the wait: the wearer's burst ended and the agent has made no sound since, capped at 8 s so that a slow network does not see the dots give up before the reply; a burst at the mic that begins while the agent's voice is in the room or within 300 ms after it is taken as that voice through the open-ear speakers and counts for nothing. `Act.kt` reads `rayneo.agent` and logs every change under `rayneo-agent` and as an `agent` event for the lab report. `AgentDots.kt` draws the dots on a canvas from lambdas read at draw time, so a frame redraws the canvas and recomposes nothing; `Phase.kt` merges the sources with a fixed priority as before, now with LOOKING and with the local sound in place of the SFU's and the agent's speaking states.

On the agent, `Build.act` is one more participant attribute, `rayneo.agent`, published with the step list by `publish_build`: `Build.act_now("yes")`, `"not"` and `"looking"` give it the kind and a running count, so two acts of one kind in a row both reach the glasses as a change, and `act_now("")` clears it. `gpt/moments.py` sets and publishes it right before the brick line's commentary; `gpt/brain.py` sets "looking" before a look that `look_now` called and clears it with the verdict, in the same message as the step when the step moves, and the next look clears a "looking" left by a look that failed or was cancelled.

`MockScreen` (`glasses.ps1 -Mock`) plays a 43 s scene of the states with a made-up loudness curve, so the layout and the motion can be looked at on the glasses without a server or API credit.

## To verify on the glasses

Whether the dots at the bottom edge are noticed in the corner of the eye while the wearer looks at the bricks, or should move up; whether the full scale of 4000 makes the bars move naturally for both voices; whether the agent's voice comes back through the microphone and the 300 ms rule catches it; whether 8 s is the right cap for the wait; whether the picture is legible at 200 dp; and, from the logs, how far the flash leads the voice (`rayneo-agent` on the glasses against `moment_say` and the voice's first word in the agent's record).
