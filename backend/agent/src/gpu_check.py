"""Checks, from inside the agent's container, that the GPU decoder the glasses' H.265 needs is there, without the glasses.

    cd backend && docker compose run --rm --no-deps agent uv run --no-sync python src/gpu_check.py

Loads the two driver libraries libwebrtc opens at run time (libcuda.so.1 and libnvcuvid.so.1, which the nvidia runtime
mounts when the service has the GPU and the `video` capability, docker-compose.yml), then joins an empty room on the
local livekit-server, which creates libwebrtc's decoder factories: the Rust SDK prints "Nvidia Decoder is supported."
when its check of the CUDA context and the NVDEC library passes, which is what admits the NVDEC factory (H.264 and
H.265), and without the GPU "NVDEC runtime library (libnvcuvid.so.1) not found". The two lines are libwebrtc's own
output; its log through the SDK did not reach Python in the check of 2026-11-03, so the `livekit` logger at INFO here
is for what else the SDK says. In a call camera.py records the decoder from the track's statistics instead. Exits
non-zero when a library is missing.
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
