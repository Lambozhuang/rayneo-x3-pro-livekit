"""Environment configuration for the GPT path.

Everything named in .env so it can be changed without a rebuild: the voice
model (GPT-Live, priced by the second), the backend model it delegates
reasoning and tool calls to, which judge watches the camera (JUDGE=cv, no
model, the default; or vlm, a vision model in a separate Responses call), and
the camera loop's knobs. The backend model never sees a picture. The experiment
switches are logged as one `experiment:` line at the start of every call, so a
run's conditions can be read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

from livekit.plugins.openai.realtime import GPTLiveModel
from openai import AsyncOpenAI

logger = logging.getLogger("rayneo-agent.config")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy backend/.env.example to backend/.env and fill it in.")
    return value


def language() -> str:
    """The language the agent speaks, whatever it hears."""
    return os.environ.get("AGENT_LANGUAGE", "English")


@dataclass(frozen=True)
class Settings:
    live_model: str
    voice: str
    backend_model: str
    backend_effort: str
    # The judge (JUDGE): cv = judge_cv.py on every gated frame, no model; vlm =
    # judge_vlm.py, the check_* model in its own Responses call per frame.
    judge: str
    check_model: str
    check_effort: str
    check_detail: str
    # The camera loop (watch.py): the plate must have been still this long
    # before a frame is judged (gate.py), at least this many seconds between
    # two judged frames, and how many consecutive verdicts must agree before a
    # step counts or a wrong placement is spoken (progress.py).
    gate_still: float
    watch_gap: float
    watch_confirm: int
    # The camera's focal length in px for the CV judge; blank = fitted from the
    # first frames that show the whole plate.
    focal_px: float | None
    # Which [colours.<name>] table of the task file the CV judge uses (JUDGE_COLOURS).
    colours: str

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            live_model=require_env("OPENAI_LIVE_MODEL"),
            voice=os.environ.get("OPENAI_VOICE", "marin"),
            backend_model=require_env("OPENAI_BACKEND_MODEL"),
            backend_effort=os.environ.get("OPENAI_BACKEND_EFFORT", "low"),
            judge=os.environ.get("JUDGE", "cv"),
            check_model=os.environ.get("OPENAI_CHECK_MODEL", ""),
            # gpt-6-sol with no reasoning was the stable VLM setting (eval/RESULTS.md)
            check_effort=os.environ.get("OPENAI_CHECK_EFFORT", "none"),
            check_detail=os.environ.get("OPENAI_CHECK_DETAIL", "high"),
            gate_still=float(os.environ.get("GATE_STILL", "1.0")),
            watch_gap=float(os.environ.get("GPT_WATCH_GAP", "0.5")),
            watch_confirm=int(os.environ.get("GPT_WATCH_CONFIRM", "2")),
            focal_px=float(os.environ["JUDGE_FOCAL_PX"]) if os.environ.get("JUDGE_FOCAL_PX") else None,
            colours=os.environ.get("JUDGE_COLOURS", "livekit"),
        )
        require_env("OPENAI_API_KEY")  # the SDK and the plugin read it themselves
        if s.judge not in ("cv", "vlm"):
            raise RuntimeError(f"JUDGE={s.judge!r}: must be cv or vlm")
        if s.judge == "vlm":
            require_env("OPENAI_CHECK_MODEL")
        logger.info(
            "session model: %s voice=%s backend=%s effort=%s judge=%s%s",
            s.live_model, s.voice, s.backend_model, s.backend_effort, s.judge,
            f" vision={s.check_model} effort={s.check_effort} detail={s.check_detail}" if s.judge == "vlm" else "",
        )
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


def build_live_model(settings: Settings, backend_instructions: str) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The voice persona goes on the
    Agent; only the backend's instructions are set here."""
    return GPTLiveModel(
        model=settings.live_model,
        voice=settings.voice,
        delegation="responses",
        responses_options={
            "model": settings.backend_model,
            "instructions": backend_instructions,
            "reasoning": {"effort": settings.backend_effort},
        },
    )


def openai_client() -> AsyncOpenAI:
    return AsyncOpenAI()
