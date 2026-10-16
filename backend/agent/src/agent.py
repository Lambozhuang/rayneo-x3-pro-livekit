"""Entrypoint for the RayNeo X3 Pro live assistant.

Two architectures share this process, chosen once at start by AGENT_BACKEND
(backend/.env, required):

  gemini  gemini/   Gemini Live: one native-audio model that hears, sees the
                    camera frames itself and talks, with no task loaded.
  openai  gpt/      GPT-Live speaks the LEGO build; what needs eyes it hands
                    to the brain, one vision call on the newest camera frame,
                    which also moves the step.

Both register with livekit-server under AGENT_NAME and wait to be dispatched;
the api puts that name into every join token it signs, so the agent turns up
in exactly the rooms the backend created and nowhere else. The glasses see the
same participant either way: audio and captions, and on the GPT path the step
list as participant attributes. frames.py and runlog.py are shared; guide.py
and prompts.py (the build) serve the GPT path; everything else belongs to one
architecture.
"""

import os

from dotenv import load_dotenv
from livekit import agents

load_dotenv()  # backend/.env, found by walking up from this file

backend = os.environ.get("AGENT_BACKEND")
if not backend:
    raise SystemExit("AGENT_BACKEND is not set: use gemini or openai (backend/.env)")
if backend == "gemini":
    from gemini.agent import server
elif backend == "openai":
    from gpt.agent import server
else:
    raise SystemExit(f"AGENT_BACKEND={backend!r}: use gemini or openai")

if __name__ == "__main__":
    agents.cli.run_app(server)
