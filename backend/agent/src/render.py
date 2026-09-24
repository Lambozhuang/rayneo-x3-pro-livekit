"""The reference model: the finished build, rendered here and streamed to the
glasses as a video track.

The wearer needs to see what they are building. Cortés et al. gave their
builders a live view of the instructor's figure; ours is a 3D model of the
finished build (`model.glb` in the guide's directory, one node per brick),
rendered in this process and published into the room as a second video track
from the agent participant. The glasses only decode and show it; nothing about
the model lives on the device. That is the cloud-rendering shape (split
rendering in 3GPP terms), and it makes the downlink picture a network path the
experiment can measure alongside the voice.

Rendering is moderngl on a headless GL context: on Linux an EGL surfaceless
context on Mesa, no display needed, software rasterisation is plenty for a
few thousand triangles; on Windows the default WGL context. The GL context is
bound to the thread that created it, so a dedicated thread renders and pushes
frames at `fps` into the rtc.VideoSource; the asyncio loop never waits on it.

What is shown is `ModelState`: rotation on or off, a preset view, one brick
highlighted. The tools (tools.py) change it from the model's function calls,
and Build changes the highlight as steps advance. The next frame reflects it.
The background is black, which on the glasses' see-through display is
transparent.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from livekit import rtc

logger = logging.getLogger("rayneo-agent.model")

VIEWS: dict[str, tuple[float, float]] = {  # name -> (yaw, pitch) in degrees
    "front": (0, 18),
    "back": (180, 18),
    "left": (-90, 18),
    "right": (90, 18),
    "top": (25, 78),
    "front-left": (-40, 25),
    "front-right": (40, 25),
}

_VS = """#version 330
uniform mat4 mvp; uniform mat4 model;
in vec3 in_pos; in vec3 in_norm; out vec3 n;
void main() { gl_Position = mvp * vec4(in_pos, 1.0); n = mat3(model) * in_norm; }"""
_FS = """#version 330
uniform vec3 color; in vec3 n; out vec4 f;
void main() {
    vec3 l = normalize(vec3(0.4, 0.8, 0.6));
    float d = 0.35 + 0.65 * max(dot(normalize(n), l), 0.0);
    f = vec4(pow(color * d, vec3(1.0 / 2.2)), 1.0);
}"""


@dataclass
class ModelState:
    """What the glasses see. Changed from the asyncio side, read once per
    frame by the render thread; the fields are independent so there is no
    invariant to protect and no lock."""

    spin: bool = True
    view: str = "front-left"  # a key of VIEWS; the spin starts from it
    highlight: str | None = None  # node name (a step's `node`), or None for all in colour
    # Only these nodes are drawn, each in its own colour: the build up to the
    # current step, later bricks not yet there. None draws the whole model.
    upto: frozenset[str] | None = None

    def show(self, view: str) -> None:
        if view == "spin":
            self.spin = True
        else:
            self.view = view
            self.spin = False


@dataclass(frozen=True)
class StreamConfig:
    # The glasses show the model in a 269x202 px box (42% of a 640x480 eye),
    # so 320x240 is already a little more than the display can use.
    width: int = 320
    height: int = 240
    fps: int = 15
    codec: str = "vp8"  # vp8 | h264 | av1 | vp9
    max_bitrate: int = 1_500_000

    @classmethod
    def from_env(cls) -> StreamConfig:
        w, h = os.environ.get("MODEL_STREAM_SIZE", "320x240").lower().split("x")
        return cls(
            width=int(w), height=int(h),
            fps=int(os.environ.get("MODEL_STREAM_FPS", "15")),
            codec=os.environ.get("MODEL_STREAM_CODEC", "vp8").lower(),
            max_bitrate=int(os.environ.get("MODEL_STREAM_BITRATE", "1500000")),
        )


def stream_enabled() -> bool:
    return os.environ.get("MODEL_STREAM", "on").lower() not in ("off", "0", "false", "no")


class _Renderer:
    """One GL context, one framebuffer, the model's bricks as vertex arrays.
    Built and used on the render thread only."""

    def __init__(self, glb: Path, width: int, height: int) -> None:
        import moderngl
        import trimesh

        self.w, self.h = width, height
        backend = os.environ.get("MODEL_GL_BACKEND") or ("egl" if sys.platform.startswith("linux") else None)
        self.ctx = moderngl.create_standalone_context(**({"backend": backend} if backend else {}))
        self.prog = self.ctx.program(vertex_shader=_VS, fragment_shader=_FS)
        self.fbo = self.ctx.simple_framebuffer((width, height), components=4)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self._triangles = moderngl.TRIANGLES

        scene = trimesh.load(glb, force="scene")
        centre = scene.bounds.mean(0)
        self.parts: list[tuple[str, object, np.ndarray]] = []  # (node, vao, rgb)
        for node in sorted(scene.graph.nodes_geometry):
            transform, gname = scene.graph[node]
            g = scene.geometry[gname]
            v = trimesh.transform_points(g.vertices, transform) - centre
            tri = v[g.faces].astype("f4")  # (F, 3, 3): flat shading, one normal per face
            nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
            data = np.concatenate([tri.reshape(-1, 3), np.repeat(nrm, 3, 0)], axis=1).astype("f4")
            vao = self.ctx.simple_vertex_array(self.prog, self.ctx.buffer(data.tobytes()), "in_pos", "in_norm")
            mat = g.visual.material
            rgb = np.array(mat.baseColorFactor[:3]) / 255.0 if getattr(mat, "baseColorFactor", None) is not None else np.full(3, 0.8)
            self.parts.append((node, vao, rgb))
        self.radius = float(np.linalg.norm(scene.extents)) * 0.5
        # Orthographic by default: bricks keep their true proportions and rows
        # stay parallel, which is what a builder compares against; a 35-degree
        # perspective made the near end look bigger. MODEL_PROJECTION=perspective
        # brings the old look back. The eye sits 3.3 radii out either way; the
        # orthographic half-height fits the bounding sphere the same as the
        # perspective did (1.04 r).
        if os.environ.get("MODEL_PROJECTION", "ortho").lower().startswith("persp"):
            self.proj = _perspective(np.radians(35), width / height, self.radius * 0.1, self.radius * 20)
        else:
            self.proj = _ortho(self.radius * 1.04, width / height, self.radius * 0.1, self.radius * 20)

    @property
    def nodes(self) -> list[str]:
        return [p[0] for p in self.parts]

    def frame(self, yaw: float, pitch: float, highlight: str | None, only: set[str] | None = None) -> bytes:
        """One frame. `highlight` names the brick drawn in colour (a little
        brighter) among grey ones; `only` restricts drawing to those nodes,
        for "the build up to this step" where every drawn brick keeps its own
        colour and the rest do not exist yet."""
        # 3.3 radii back, so the bounding sphere (radius r) fits the frame's
        # height at any angle: 3.3 * tan(35°/2) = 1.04 r. At 3.0 it was 0.95 r
        # and a corner of the model touched the bottom edge now and then.
        eye = self.radius * 3.3 * np.array(
            [np.sin(yaw) * np.cos(pitch), np.sin(pitch), np.cos(yaw) * np.cos(pitch)], "f4"
        )
        view = _look_at(eye, np.zeros(3, "f4"))
        model = np.eye(4, dtype="f4")
        self.fbo.use()
        self.fbo.clear(0.0, 0.0, 0.0, 1.0)
        self.prog["model"].write(model.T.tobytes())
        self.prog["mvp"].write((self.proj @ view @ model).T.tobytes())
        for node, vao, rgb in self.parts:
            if only is not None and node not in only:
                continue
            if highlight is None or only is not None and node != highlight:
                c = rgb
            elif node == highlight:
                c = np.clip(rgb * 1.15 + 0.05, 0, 1)  # its own colour, a little brighter
            else:
                c = np.full(3, 0.55 + 0.25 * float(rgb @ [0.3, 0.59, 0.11]))  # light grey
            self.prog["color"].value = tuple(map(float, c))
            vao.render(self._triangles)
        raw = np.frombuffer(self.fbo.read(components=4), "u1").reshape(self.h, self.w, 4)
        return np.ascontiguousarray(raw[::-1]).tobytes()  # GL rows are bottom-up

    def release(self) -> None:
        self.ctx.release()


class ModelStream:
    """Publishes the rendered model as a video track of the local participant.

    `start()` publishes and begins the render thread, `stop()` ends both. The
    first frame is rendered before publishing so a GL problem fails loudly at
    start-up rather than as a black track.
    """

    def __init__(self, glb: Path, state: ModelState, config: StreamConfig | None = None) -> None:
        self.glb = glb
        self.state = state
        self.config = config or StreamConfig.from_env()
        self.nodes: list[str] = []
        self._source: rtc.VideoSource | None = None
        self._publication: rtc.LocalTrackPublication | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None

    async def start(self, participant: rtc.LocalParticipant) -> None:
        c = self.config
        self._source = rtc.VideoSource(c.width, c.height)
        self._thread = threading.Thread(target=self._run, name="model-render", daemon=True)
        self._thread.start()
        # Wait for the first frame (or the failure) before publishing.
        await asyncio.get_running_loop().run_in_executor(None, self._ready.wait)
        if self._error is not None:
            raise RuntimeError(f"model render failed: {self._error!r}") from self._error
        track = rtc.LocalVideoTrack.create_video_track("model", self._source)
        codec = getattr(rtc.VideoCodec, c.codec.upper())
        self._publication = await participant.publish_track(
            track,
            rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_CAMERA,
                simulcast=False,
                video_codec=codec,
                video_encoding=rtc.VideoEncoding(max_framerate=c.fps, max_bitrate=c.max_bitrate),
            ),
        )
        logger.info(
            "model stream: %s %dx%d@%d %s nodes=%s", self.glb.name, c.width, c.height, c.fps, c.codec, self.nodes
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        c = self.config
        try:
            renderer = _Renderer(self.glb, c.width, c.height)
            self.nodes = renderer.nodes
            t = time.perf_counter()
            renderer.frame(0.0, 0.0, None)
            logger.info("model render: first frame %.1f ms, %s", 1000 * (time.perf_counter() - t), renderer.ctx.info.get("GL_RENDERER"))
        except BaseException as e:  # noqa: BLE001 - reported to start()
            self._error = e
            self._ready.set()
            return
        self._ready.set()
        angle = 0.0
        period = 1.0 / c.fps
        next_at = time.perf_counter()
        last_view = self.state.view
        render_ms: list[float] = []
        while not self._stop.is_set():
            st = self.state
            yaw0, pitch = VIEWS.get(st.view, VIEWS["front-left"])
            if st.view != last_view:
                angle, last_view = 0.0, st.view  # a new preset: spin resumes from it
            if st.spin:
                angle += 0.5 * period  # rad/s: one turn in ~12 s
            t = time.perf_counter()
            data = renderer.frame(np.radians(yaw0) + angle, np.radians(pitch), st.highlight, only=st.upto)
            render_ms.append(1000 * (time.perf_counter() - t))
            assert self._source is not None
            self._source.capture_frame(rtc.VideoFrame(c.width, c.height, rtc.VideoBufferType.RGBA, data))
            if len(render_ms) >= c.fps * 60:
                logger.info("model render: %.1f ms/frame avg, %.1f max over %ds", np.mean(render_ms), np.max(render_ms), len(render_ms) // c.fps)
                render_ms.clear()
            next_at += period
            delay = next_at - time.perf_counter()
            if delay > 0:
                self._stop.wait(delay)
            else:
                next_at = time.perf_counter()  # fell behind: do not try to catch up
        renderer.release()


def _perspective(fovy: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1 / np.tan(fovy / 2)
    return np.array(
        [[f / aspect, 0, 0, 0], [0, f, 0, 0],
         [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)], [0, 0, -1, 0]], "f4",
    )


def _ortho(half_h: float, aspect: float, near: float, far: float) -> np.ndarray:
    return np.array(
        [[1 / (half_h * aspect), 0, 0, 0], [0, 1 / half_h, 0, 0],
         [0, 0, -2 / (far - near), -(far + near) / (far - near)], [0, 0, 0, 1]], "f4",
    )


def _look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    fwd = target - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    m = np.eye(4, dtype="f4")
    m[0, :3], m[1, :3], m[2, :3] = right, up, -fwd
    m[:3, 3] = -m[:3, :3] @ eye
    return m
