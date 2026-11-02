# What the codec and the glasses' own encoder settings cost the brain's reading

This study asks what the brain's model (Claude Sonnet 5.5) loses from the video's bitrate when the video is encoded as the glasses encode it, in the H.264 they send today and in the H.265 they could send, so the bandwidth the system needs rests on the right encoder settings and the gain of a codec change is known before it is made.

## Question

`brain-frame-quality/` found that the frame's side decides what the model reads and the bitrate comes second, with 1080 holding to 1 Mbps and giving between 0.5 and 0.25 Mbps. Its encodes used two settings the glasses do not: H.264 high profile, where the glasses negotiate constrained baseline, and a keyframe every second, where the glasses send one keyframe at the start and then none unless the receiver asks (the root README's camera paragraph says how that was read from libwebrtc and a call's link log). The first flatters the picture a little, the second costs it a lot at low rates, since an I-frame at 0.25 Mbps takes most of a second's bits. This study encodes as the glasses do, in both codecs, and asks the same question of the same frames.

## Material

The second material of `brain-frame-quality/`: the ladder call of 2026-10-27 at exposure compensation -6 (`logs/20261027-165157-glasses-ad279efb/recording/`), its 41 frames (`../brain-frame-quality/out/frames.csv`) and their labels (`../brain-frame-quality/labels.toml`), shared so the two studies compare frame for frame. Nothing from the first material is used.

## Plan

1. Frames, picture, probe, labels and score as in `brain-frame-quality/`, unchanged, at the side 1080 only, since that is what the glasses send and keep under a weak network (`MAINTAIN_RESOLUTION`).
2. Encoding as libwebrtc sets MediaCodec on the glasses: constant bitrate, no B-frames, one keyframe at the start and none after, 15 fps, H.264 constrained baseline or H.265 Main; this PC's AMD encoder (`h264_amf`, `hevc_amf`) standing in for the glasses' Qualcomm one.
3. Conditions: the frame as recorded (the upper reference), then each codec at 1, 0.5 and 0.25 Mbps, 7 conditions; 1 Mbps is the check that the gentle rates still read as the reference, 0.5 and 0.25 are where the sibling study saw the picture give.
4. Thinking at effort low in every call, as the brain's hand-over runs; the sibling study found it produces no thinking for this question, so it is one run per condition, no thinking, and the sibling's repeat runs give the noise: up to 6 whole frames and 17 sizes of about 115 between two runs of one condition.
5. Out of scope: other sides, other models, the frame rate, the gap between the AMD and the Qualcomm encoder, and WebRTC's frame dropping when the encoder overshoots, which a file encode never does.

## Method

1. `encode.py <recording dir> <h264|hevc> <kbps> ...` encodes the recording at each rate with the settings of the plan into `out/<codec>-v<kbps>.mp4`, prints the rate held and the number of keyframes, decodes the study's frames from it and cuts the bottom 1080x1080 square at JPEG quality 85 into `out/<codec>-v<kbps>/`; it copies the shared frame list to `out/frames.csv` and the unencoded squares to `out/sq1080/` once.
2. `probe.py <pictures> low` and `score.py <condition> ...` are the sibling study's scripts pointed at this directory's `out/`.
3. `chart.py` draws `out/chart.png`, eleven panels against the bitrate, one line per codec and model from each model's recorded-frame point: whole frames, bricks found and sizes right as shares, then orientation right, the 1x6 and 1x4 sizes right, the extra bricks and guesses as counts, and the photo's size and the call's timing as medians.

## Result (2026-10-29)

41 frames, one call per frame per condition, `claude-sonnet-5-5` at effort low, which produced no thinking in any of the 287 calls; every reply was valid JSON. The encoder held each rate within 1% and wrote one keyframe per file. "Photo" is the median size of the brain's JPEG of the decoded frame, a rough measure of the detail the encode left in it. Columns as in `brain-frame-quality/`.

| condition | whole frames | bricks found | size right | orientation right | 1x6 right | guesses | extra | photo |
|---|---|---|---|---|---|---|---|---|
| 1080 as recorded | 33/41 | 119/120 | 111/118 | 116/118 | 56/58 | 7 | 3 | 218 KB |
| H.264 at 1 Mbps | 29/41 | 116/120 | 105/115 | 113/115 | 52/57 | 4 | 7 | 140 KB |
| H.264 at 0.5 Mbps | 29/41 | 115/120 | 103/114 | 108/114 | 52/57 | 6 | 8 | 123 KB |
| H.264 at 0.25 Mbps | 23/41 | 110/120 | 82/108 | 102/108 | 39/53 | 3 | 12 | 106 KB |
| H.265 at 1 Mbps | 36/41 | 120/120 | 113/119 | 118/119 | 57/58 | 5 | 2 | 173 KB |
| H.265 at 0.5 Mbps | 30/41 | 118/120 | 107/117 | 115/117 | 52/57 | 5 | 4 | 150 KB |
| H.265 at 0.25 Mbps | 30/41 | 119/120 | 103/118 | 116/118 | 48/58 | 4 | 2 | 138 KB |

What the numbers say, with the sibling study's noise of up to 6 whole frames and 17 sizes between two runs of one condition:

- H.264 as the glasses send it holds to 0.5 Mbps and gives at 0.25. At 1 and 0.5 Mbps the rows sit 4 whole frames and 6 to 8 sizes under the reference, at the edge of the noise, with the same bricks found; at 0.25 Mbps the picture gives, 23 whole frames, 82 of 108 sizes, the 1x6 read right in 39 of 53 and 12 extra bricks, which is the loss the sibling study saw at that rate.
- H.265 at 0.25 Mbps reads like H.264 at 0.5 to 1 Mbps. Its rows at 1 and 0.5 Mbps are the reference within noise (36 and 30 whole frames, 113 and 107 sizes), and at 0.25 Mbps it still finds 119 of 120 bricks and reads 103 of 118 sizes, 30 whole frames; what it loses there is the 1x6 count, 48 of 58. So H.265 buys about a factor of two in bitrate for the same reading, which is the codec's usual gain and shows here as a step from "gives" to "holds" at 0.25 Mbps.
- The glasses' real H.264 settings read as the sibling study's did. That study encoded with high profile and a keyframe every second, two departures from the device that pull opposite ways; its 1080 rows at 0.5 and 0.25 Mbps (32 and 24 whole frames, 104 and 99 sizes, without thinking) are within noise of these at 0.5 and a little above at 0.25, so its bitrate conclusion stands and the departures roughly cancelled.
- The photo's size follows the reading: the JPEG of a decoded H.265 frame at 0.25 Mbps (138 KB) is as large as that of an H.264 frame at 1 Mbps (140 KB), both well under the recorded frame's 218 KB, and the sizes the model reads right follow the same order.

### The same conditions with gpt-6.1-terra

One run of every condition with gpt-6.1-terra, reasoning off (the OpenAI model the GPT path could hand its looks to), through `probe.py <pictures> none --model=gpt-6.1-terra`; its replies land in `out/replies/<pictures>-none-gpt-6.1-terra/`. The chart draws it dashed beside Sonnet.

| condition | whole frames | bricks found | size right | orientation right | 1x6 right | guesses | extra | whole call |
|---|---|---|---|---|---|---|---|---|
| 1080 as recorded | 37/41 | 118/120 | 113/115 | 114/115 | 58/58 | 2 | 3 | 3.9 s |
| H.264 at 1 Mbps | 35/41 | 117/120 | 113/115 | 113/115 | 56/58 | 2 | 3 | 3.5 s |
| H.264 at 0.5 Mbps | 29/41 | 116/120 | 99/113 | 110/113 | 49/58 | 2 | 4 | 3.5 s |
| H.264 at 0.25 Mbps | 23/41 | 116/120 | 80/113 | 111/113 | 37/58 | 2 | 5 | 3.4 s |
| H.265 at 1 Mbps | 36/41 | 117/120 | 113/114 | 113/114 | 58/58 | 1 | 3 | 3.6 s |
| H.265 at 0.5 Mbps | 36/41 | 118/120 | 114/116 | 115/116 | 58/58 | 1 | 2 | 3.7 s |
| H.265 at 0.25 Mbps | 30/41 | 117/120 | 104/113 | 111/113 | 52/58 | 2 | 3 | 3.6 s |

The two models draw the same picture: H.264 holds at 1 Mbps, slips at 0.5 (terra 29 whole frames and 99 sizes against Sonnet's 29 and 103) and gives at 0.25 (23 and 80 against 23 and 82); H.265 holds to 0.5 and at 0.25 reads like H.264 at 0.5 to 1 Mbps (30 whole frames and 104 sizes against Sonnet's 30 and 103). terra reads a few more whole frames at the top (37 against 33 on the recorded frame, within the noise), guesses less (1 or 2 against 3 to 7), invents fewer bricks as the rate falls (5 against 12 at H.264 0.25 Mbps), and answers about a second sooner on half the output tokens, as in `brain-frame-quality/`. So the bitrate and codec bounds are the picture's, not one model's.

What the project does with it: in H.264 the system can run down to about 0.5 Mbps of video before the model's reading suffers, and a move to H.265 would push that to about 0.25 Mbps at no cost to the reading at the rates above it; the glasses encode H.265 in hardware (docs/glasses-spec.md), so the move is a codec setting on the publish side and a decoder on the agent's. The bound holds for the AMD encoder standing in for the Qualcomm one and for a steady rate; under a weak network WebRTC also drops frames and asks for keyframes, which this file encode does not show.
