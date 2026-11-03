"""Checks, from inside the agent's container, that the GPU decoder the glasses' H.265 needs is there, without the glasses.

    cd backend && docker compose run --rm --no-deps agent uv run --no-sync python src/gpu_check.py

Loads the two driver libraries libwebrtc opens at run time (libcuda.so.1 and libnvcuvid.so.1, which the nvidia runtime
mounts when the service has the GPU and the `video` capability, docker-compose.yml), then joins an empty room on the
local livekit-server, which creates libwebrtc's decoder factories: with the GPU the Rust SDK logs
"NvidiaVideoDecoderFactory created with 6 supported formats", H.264 and H.265 among them, and without it
"NVDEC runtime library (libnvcuvid.so.1) not found". The `livekit` logger is set to INFO so that those lines show; the
agents framework keeps it at WARN in a call, where camera.py records the decoder from the track's statistics instead.
Exits non-zero when a library is missing, so the deploy can refuse to go on.
"""

import asyncio
import ctypes
import logging
import os
import sys

from livekit import api, rtc

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
logging.getLogger("livekit").setLevel(logging.INFO)


def libraries() -> bool:
    ok = True
    for name in ("libcuda.so.1", "libnvcuvid.so.1"):
        try:
            ctypes.CDLL(name)
            print(f"{name}: loads")
        except OSError as e:
            print(f"{name}: not found ({e}); the container has no GPU, or NVIDIA_DRIVER_CAPABILITIES lacks video")
            ok = False
    return ok


async def factories() -> None:
    url = os.environ["LIVEKIT_URL"]
    token = api.AccessToken().with_identity("gpu-check").with_grants(api.VideoGrants(room_join=True, room="gpu-check")).to_jwt()
    room = rtc.Room()
    await room.connect(url, token)
    print(f"joined {url}; the decoder factory lines above say what libwebrtc found")
    await asyncio.sleep(1)
    await room.disconnect()


if __name__ == "__main__":
    if not libraries():
        sys.exit(1)
    asyncio.run(factories())
