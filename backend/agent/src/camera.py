"""The glasses' camera track as the agent receives it: the full layer is asked for, what decodes it goes into the record,
and the stream's rate at the decoder is sampled for the brain.

`watch_camera(room, record, logger)` is called once per call by every architecture's agent and returns a `Stream`. When
the glasses' video track is subscribed it asks for the full layer (the glasses send one; this guards against an SDK
that would pick a lower one), logs what was published, and once the first frames have had time to arrive reads the
receiver's statistics and writes a `decoder` event: the codec on the wire, the decoder libwebrtc picked and the frames
decoded so far. From then on it reads the statistics every STREAM_EVERY_S and keeps the received kbps and decoded fps
of the last window in the `Stream`, with a `stream` event in the record each time; `Stream.weak` is true below
WEAK_KBPS or WEAK_FPS, which is where the brain's photos lose the studs (the glasses send about 4000 kbps at 15 fps,
about 330 under a 0.5 Mbps cap and about 110 under 0.25, with 1 fps windows), and gpt/brain.py tells the model so
once a minute while it lasts, so that the voice can say the picture is poor instead of asking the wearer to pose. The glasses send H.265 (VoiceAssistantViewModel.kt), which the agent's libwebrtc decodes only on an NVIDIA
GPU, NVDEC, where the decoder is named `NVIDIA H265 Decoder` (the Rust SDK's NvidiaVideoDecoderFactory; it has no
software H.265 decoder). A call on a machine without the GPU therefore has a `decoder` event with no frames, which deploy/report.py
lists as a problem, and the vision model sees nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from livekit import rtc

from runlog import RunLog

STATS_AFTER_S = 5  # the decoder exists once the first frames have arrived; the glasses publish within a second
STREAM_EVERY_S = 5  # how often the received rate is read; the glasses' own link statistics come every 5 s too
WEAK_KBPS = 1000  # received video below this is a weak picture: a 0.5 Mbps cap gives about 330 kbps, 0.25 about 110
WEAK_FPS = 10  # decoded frames per second below this is a weak picture: the glasses send 15


@dataclass
class Stream:
    """The camera stream at the agent's decoder over the last STREAM_EVERY_S: received kbps, decoded fps, and when they
    were read; None before the first window. `weak` says the brain's photos are likely too poor for studs."""
    kbps: float | None = None
    fps: float | None = None
    at: float | None = None

    @property
    def weak(self) -> bool:
        return self.kbps is not None and (self.kbps < WEAK_KBPS or (self.fps is not None and self.fps < WEAK_FPS))


def watch_camera(room: rtc.Room, record: RunLog, logger: logging.Logger) -> Stream:
    stream = Stream()

    @room.on("track_subscribed")
    def _subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if publication.kind != rtc.TrackKind.KIND_VIDEO:
            return
        if publication.simulcasted:  # the rtc SDK raises otherwise; the glasses send one layer
            publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)
        logger.info(
            "video from %s: published %dx%d %s simulcast=%s",
            participant.identity, publication.width, publication.height,
            publication.mime_type, publication.simulcasted,
        )
        asyncio.create_task(_record_decoder(track, participant.identity, record, logger), name="camera_decoder")
        asyncio.create_task(_sample_stream(track, stream, record, logger), name="camera_stream")

    return stream


async def _record_decoder(track: rtc.Track, who: str, record: RunLog, logger: logging.Logger) -> None:
    await asyncio.sleep(STATS_AFTER_S)
    try:
        stats = await track.get_stats()
    except Exception as e:  # the call ended before the stats could be read
        logger.warning("video decoder: no statistics from the track: %s", e)
        return
    codecs = {s.codec.rtc.id: s.codec.codec.mime_type for s in stats if s.HasField("codec")}
    for s in stats:
        if not s.HasField("inbound_rtp"):
            continue
        codec = codecs.get(s.inbound_rtp.stream.codec_id)
        implementation = s.inbound_rtp.inbound.decoder_implementation or None
        frames = s.inbound_rtp.inbound.frames_decoded
        logger.info("video decoder: %s by %s, %d frames decoded %d s after subscribing", codec, implementation or "none", frames, STATS_AFTER_S)
        record.event("decoder", who=who, codec=codec, implementation=implementation, frames=frames, after_s=STATS_AFTER_S)


async def _sample_stream(track: rtc.Track, stream: Stream, record: RunLog, logger: logging.Logger) -> None:
    """Every STREAM_EVERY_S, the received bytes and decoded frames since the reading before, as kbps and fps, into
    `stream` and the record; logged when the picture turns weak or strong. Ends when the track can give no
    statistics, which is the call's end."""
    last: tuple[float, int, int] | None = None
    was_weak = False
    while True:
        await asyncio.sleep(STREAM_EVERY_S)
        try:
            stats = await track.get_stats()
        except Exception:
            return
        for s in stats:
            if not s.HasField("inbound_rtp"):
                continue
            now = time.monotonic()
            got = (now, s.inbound_rtp.inbound.bytes_received, s.inbound_rtp.inbound.frames_decoded)
            if last is not None and now > last[0]:
                dt = now - last[0]
                stream.kbps = (got[1] - last[1]) * 8 / 1000 / dt
                stream.fps = (got[2] - last[2]) / dt
                stream.at = now
                record.event("stream", kbps=round(stream.kbps), fps=round(stream.fps, 1), weak=stream.weak)
                if stream.weak != was_weak:
                    logger.info("video stream: %.0f kbps %.1f fps, the picture is %s", stream.kbps, stream.fps,
                                "weak" if stream.weak else "good again")
                    was_weak = stream.weak
            last = got
            break
