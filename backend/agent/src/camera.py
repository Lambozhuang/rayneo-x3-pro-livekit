"""The glasses' camera track as the agent receives it: the full layer is asked for, and what decodes it goes into the record.

`watch_camera(room, record, logger)` is called once per call by every architecture's agent. When the glasses' video
track is subscribed it asks for the full layer (the glasses send one; this guards against an SDK that would pick a
lower one), logs what was published, and once the first frames have had time to arrive reads the receiver's
statistics and writes a `decoder` event: the codec on the wire, the decoder libwebrtc picked and the frames decoded
so far. The glasses send H.265 (VoiceAssistantViewModel.kt), which the agent's libwebrtc decodes only on an NVIDIA
GPU, NVDEC, where the decoder is named `NVIDIA H265 Decoder` (the Rust SDK's NvidiaVideoDecoderFactory; it has no
software H.265 decoder). A call on a machine without the GPU therefore has a `decoder` event with no frames, which deploy/report.py
lists as a problem, and the vision model sees nothing.
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc

from runlog import RunLog

STATS_AFTER_S = 5  # the decoder exists once the first frames have arrived; the glasses publish within a second


def watch_camera(room: rtc.Room, record: RunLog, logger: logging.Logger) -> None:
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
