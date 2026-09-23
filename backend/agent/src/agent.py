"""Entrypoint for the RayNeo X3 Pro live assistant.

Two implementations share this process, chosen once at start by AGENT_BACKEND:

  gemini  gemini/   Gemini Live: one native-audio model that hears, sees the
                    camera frames itself, and judges the bricks. The original.
  openai  gpt/      GPT-Live voice model with a gpt-6-luna backend; the camera
                    is judged by a separate vision call, the code moves the step.

Both register with livekit-server under AGENT_NAME and wait to be dispatched;
the api puts that name into every join token it signs, so the agent turns up
in exactly the rooms the backend created and nowhere else. guide.py (the build
and the run's position in it) and render.py (the reference model stream) are
shared; everything else is per backend, so the two can differ freely.
"""

import os

from dotenv import load_dotenv
from livekit import agents

load_dotenv()  # backend/.env, found by walking up from this file

backend = os.environ.get("AGENT_BACKEND", "gemini")
if backend == "gemini":
    from gemini.agent import server
elif backend == "openai":
    from gpt.agent import server
else:
    raise SystemExit(f"AGENT_BACKEND={backend!r}: use gemini or openai")

if __name__ == "__main__":
    agents.cli.run_app(server)
