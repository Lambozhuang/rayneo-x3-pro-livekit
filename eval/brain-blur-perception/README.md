# Can the brain's model see that the picture is blurry

This study asks whether the brain's model, gpt-6.1-terra as deployed, can tell from a photo alone that the picture has gone poor, so that it could say "the picture I'm getting is a bit blurry" from its own perception, the way a person would, instead of being fed the stream's bitrate by `camera.py`. It was asked for after the second pilot (2026-11-04, `user-study/pilot-2/issues.md` A1): the user did not want a separate picture-quality module if the model could judge the picture itself.

## Material

Two sets. First, the frames of `brain-frame-codec/`: the 41 frames of the 2026-10-27 ladder recording as recorded (`sq1080`) and encoded in H.265 at 1, 0.5, 0.25 and 0.1 Mbps as the glasses encode (`hevc-v1000` to `hevc-v100`), with the brick labels of `brain-frame-quality/labels.toml`. Second, real frames from two calls of 2026-11-04 on the same desk at exposure -4, the brain's own 1080 px photos as its watch looks sent them: 36 picked evenly over the call with no network cap (`logs/20261104-123046-glasses-dfdff7e6`, 181 KB a photo) and 36 over the call under a 0.25 Mbps uplink cap (`logs/20261104-103852-glasses-0013df82`, 124 KB a photo). The real frames carry the decoder's artefacts, which an encoded file does not, and they are what the experiment's brain will see.

## Method

`probe.py` asks the model about every photo twice, the same way the brain is called (gpt-6.1-terra, reasoning effort low, the photo at detail high, one chat completion with a strict JSON schema), with the plate-description prompt of `brain-frame-quality/probe.py` and one question added: the photo's sharpness as `clear` (edges and studs crisp), `slightly blurry` (soft but the studs can still be counted) or `blurry` (compression or softness hide the studs), and whether the studs on the plate can be counted. `summarize.py` prints, per condition, the share of each grade over both passes, the share of photos the two passes graded alike, the share called studs-countable and the share of brick entries whose size the model would not read.

The decision rule agreed before the run: if the real capped frames come out not-clear in at least 80 percent of the gradings and the real open frames are called blurry in at most 10 percent, the model's own perception is good enough and the stream signal goes; otherwise the stream signal stays, with its threshold at 200 kbps of received video over two 5 s windows in a row, the first 15 s of a call excepted, and 10 fps.

## Result (2026-11-04)

554 gradings, every reply valid JSON, 277 photos asked twice.

| condition | photos | clear | slightly blurry | blurry | not clear | both passes alike | studs countable | sizes can't tell | photo KB |
|---|---|---|---|---|---|---|---|---|---|
| codec study, as recorded | 41 | 100% | 0% | 0% | 0% | 100% | 89% | 6% | 218 |
| codec study, H.265 1 Mbps | 41 | 84% | 16% | 0% | 16% | 88% | 93% | 6% | 173 |
| codec study, H.265 0.5 Mbps | 41 | 62% | 35% | 2% | 38% | 93% | 89% | 8% | 150 |
| codec study, H.265 0.25 Mbps | 41 | 30% | 48% | 22% | 70% | 83% | 73% | 23% | 138 |
| codec study, H.265 0.1 Mbps | 41 | 5% | 38% | 57% | 95% | 98% | 33% | 58% | 112 |
| real call, no cap (12:30) | 36 | 71% | 24% | 6% | 29% | 86% | 82% | 15% | 181 |
| real call, 0.25 Mbps cap (10:38) | 36 | 0% | 0% | 100% | 100% | 100% | 0% | 100% | 121 |
| pilot 2 run 4, no cap, +1000 ms RTT (13:06, exposure -2) | 36 | 65% | 26% | 8% | 35% | 81% | 74% | 17% | 189 |
| pilot 2 run 5, 0.5 Mbps cap (13:10, exposure -2) | 36 | 18% | 57% | 25% | 82% | 81% | 51% | 35% | 144 |
| pilot 2 run 6, 0.25 Mbps cap (13:15, exposure -2) | 36 | 0% | 31% | 69% | 100% | 89% | 31% | 79% | 129 |

- The grades follow the bitrate down the codec ladder: clear in 100, 84, 62, 30 and 5 percent of the gradings from the recording to 0.1 Mbps, blurry in 0, 0, 2, 22 and 57 percent, and the two passes agree on 83 to 100 percent of the photos.
- The real capped call is graded blurry in every one of its 72 gradings, far more than the encoded 0.25 Mbps frames (22 percent blurry): the live stream's decode of a lossy 0.25 Mbps uplink, with 3 to 6 percent of packets dropped by the shaper, smears far worse than a clean encode at the same rate, and the model sees it. In these photos it would read no brick size at all (0 of 72 gradings studs-countable), where the call's own brain, which knows the steps, did move the build through all five.
- The real open call is graded blurry in 6 percent of the gradings (two photos: the dark first frame of the call and one with the hand moving) and slightly blurry in 24 percent, so "blurry" is the grade to speak on and "slightly blurry" is not.
- Hands lie over the plate in 64 of the 72 capped gradings and 45 of the 72 open ones, so hands do not explain the difference in grades.
- The second pilot's runs, asked for afterwards (2026-11-04 evening): the +1000 ms run grades like the open call (65 percent clear, 8 percent blurry), so delay alone leaves the picture whole. The real 0.5 Mbps cap is already far from the encoded 0.5 Mbps file: not clear in 82 percent of the gradings, blurry in 25, studs countable in half, where the encoded frames were blurry in 2 percent; the real cliff for the model sits between no cap and 0.5 Mbps, not between 0.5 and 0.25. The second pilot's 0.25 Mbps run is blurry in 69 percent and slightly blurry in 31, a little milder than the 10:38 call's 100 percent blurry (different participant, exposure -2 against -4).
- The nine frames at which that 0.25 Mbps run moved its progress (seven up, two down), graded twice each: two of the seven steps were recorded on frames graded slightly blurry with every size read (steps 2 and 3 at 125.8 s and 170.6 s), the other five on frames graded blurry with no size read; both withdrawals (177.0 s, 225.0 s) and the re-recordings after them were on blurry frames. So under that cap most steps rested on colour, place and the step list, not on studs.

Against the rule agreed before the run, the capped call comes out not clear in 100 percent (the bar was 80) and the open call blurry in 6 percent (the bar was 10): the model's own perception is good enough.

## What the project does with it

The brain is no longer fed the stream's rate. `gpt/prompts.py` tells it to remark, once a call and asking nothing, when the photo itself is blurry to it, compression or smearing hiding the studs, and not on a softness it can still count through; `camera.py` keeps writing the `stream` events for the analysis of a run. The 0.5 Mbps condition will seldom draw the remark (2 percent blurry on the encoded frames, and the model there read as well as on the recording), which is as the codec study found. A caution for the experiment: the real 0.25 Mbps stream is worse for the model than the codec study's 0.25 Mbps file, so the brain's reading under that cap rests on knowing the steps, not on the picture.
