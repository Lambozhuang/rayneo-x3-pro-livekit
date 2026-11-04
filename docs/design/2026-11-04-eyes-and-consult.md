# How the agent came to be a mouth, a pair of eyes and a consult (2026-11-04)

This note records the design work of the evening of 2026-11-04: the question it started from, what was found about the models, the five structures weighed, the measurements that decided between them, and what is still open until the glasses have run the result. The code is in `backend/agent/src/gpt/`, the measurements in `eval/brain-decisions/`, `eval/brain-speed/` and `eval/agent-sim/`, the versions under the git tags named below.

## The question

Two pilots had been run on the structure of the week before, one vision model (gpt-6.1-terra) watching the camera every two seconds with a conversation of its own and speaking to GPT-Live through tools, and the afternoon's fixes to it had been patches on symptoms: lines came late, the voice talked too much, colours were called wrong, a step was reopened on a colour. The user asked to stop patching and start again from two ends: what a human instructor does in this role, and what the available models can do, with no preconceptions about where the time goes.

The role is the one of ITU-T P.1321 Annex B: an instructor with the picture and a builder with loose bricks, over a video link. A human in it leads, gives each step as its brick and its place together, answers "this one?" and "done" with a word within a second, corrects in small relative steps, asks for the hand to move when it is in the way, asks about a colour rather than asserting it and takes the builder's word, gives an acknowledgement no answer, and says nothing while the builder works.

## What was found about the models

GPT-Live has no parameters for pace, length, interruption or backchannels; its behaviour is set by its prompt, and OpenAI's Prompting GPT-Live guide gives a template with a backchannel policy, an interruption policy and a delegation policy written with the token `<|SpawnThinking|>`. It paraphrases a commentary rather than reading it, and it hands over now and then whatever the prompt says.

The time of a terra look was in reading the image and the prefix, not in writing: looks with the fewest output tokens took 1.8 s and those with the most 2.0 s. A persistent WebSocket to the Responses API took 0.3 s off every look (1.34 s against 1.64 s on the same looks); a smaller image saved tokens and no time; gpt-6-luna as the talking brain was faster but spoke at 20 of 30 looks and moved the progress nine times where the plate moved twice (`eval/brain-speed/`).

OpenAI's Decisions API runs gpt-6-luna and returns typed answers only, a probability for a yes-or-no question and a choice with its confidence, in about 0.3 s with a 512 px frame (`eval/brain-decisions/`). On the recorded frames it read the hand on the plate as a clean 0 or 1, the brick in the hand by colour with the camera's colour confusions showing as low confidence, the count of steps built right agreeing with terra on 37 to 40 of 40 looks, and a right placement (0.84 to 0.93) from a wrong one (0.0 to 0.25). It could not say which way a wrong brick was off, at detail high or with the step's rendered picture as a reference either, and seven questions in one request spread its confidences where four had been firm. GPT-Live's own integrations of Decisions, the `decisions` delegation type and transcript triggers, take text only, so they played no part.

## The five structures weighed

| | eyes | who speaks to the voice | who records progress | terra calls a call | "this one?", "done" | correction |
|---|---|---|---|---|---|---|
| A | terra every 2 s, woken by the wearer's words; a quick look on the Decisions API every second | terra, and the quick look for two lines | both | about 70 | 1.5 to 2 s | terra at its next look |
| B | as A | terra only; the quick look wakes it | terra | about 70 | 2.7 to 3.5 s | as A |
| C | as A | terra, and the quick look for the brick in the hand | terra | about 70 | brick 1.5 s, done 2.7 s | as A |
| D | Decisions only | the eyes' facts, the voice composes | the eyes | 0 | 1.5 to 2.3 s | "not quite, want the picture?" |
| E | Decisions, adaptive rate | the eyes' facts; terra's sentence when words are needed | the eyes; terra may correct | about 5 | 1.5 to 2.3 s | "not quite" at once, the sentence 1 to 3 s later |

A was built first and ran in simulation (tag `instructor-a`). Its weakness was two judges: terra and the quick look could both speak and both move the progress, and the user found that confusing. B and C were its conservative cuts, with less to say and no gain in time; they were not built. D fell to the measurement: the eyes cannot say which way a brick is off, and composing a correction from typed answers would have meant enumerating every mistake a task allows, which is the overfitting the project avoids. E took D's division of labour and gave the one thing it lacked to the model that has it: a correction's words, a question's answer, asked once with the frame, while the voice says the first beat. E is what runs (tag `instructor-e`). D stays one switch away for the comparison on the device: with `BRAIN_CONSULT=off` the eyes alone judge, a misplaced brick gets "not quite" with the place said once more and the picture offered, and a question about the desk gets the eyes' latest reading in words; E is the default because a wearer who hears "one column too far right" fixes it faster than one sent to the picture, and because questions about the desk need words.

## What the simulation then settled

`eval/agent-sim/` ran the whole agent on two recorded calls without the glasses. Seven runs found and settled: a request of seven questions spread the confidences, so a reading is two requests of four and three; a word of the current step in the scene questions pulled the count to zero, so it goes only with the step questions; the confidence swings between near-identical frames, so a rule asks two readings to agree on a value with their mean confidence over a bar; the misplacement rule had waited on the count, which reads 4 or 5 at 0.1 to 0.4 on a busy plate, so it waits on the step's own answers only; the first consult of a call paid for a cold WebSocket, so the connection opens at the start; the transcript comes through in pieces, so words are classified with the lines before them and an unclear classification goes to the consult as well; "I placed it" goes to the consult at once, its answer dropped if the eyes settle the step first.

In the last runs the brick in the hand was confirmed 0.3 s after the eyes' line, a step done 0.3 s after the hand left, a misplaced white brick called "not quite" with "three columns too far right" 2.2 s later, and "I put it there" on the lime brick the camera shows as yellow settled in 3.5 s by the consult. The voice spoke 30 to 40 percent of the time at 8 to 12 words a turn.

## Open until the glasses have run it

How often a right placement is called "not quite" on live frames at fifteen a second, where the simulation had one frame every two seconds; how long the first consult of a call takes on the lab PC; how often GPT-Live still hands over, and how it takes "let me look"; whether the eyes' doubt line about two colours reads as a question to the wearer; what the eyes make of the plate under a 0.25 Mbps cap, where the frames are blurred (`eval/brain-blur-perception/` graded them with terra, not luna). The device checks are listed in `docs/TODO.md`.
