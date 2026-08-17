"""Entrypoint for the RayNeo X3 Pro live assistant."""

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, room_io

from config import build_session_model
from prompts import SYSTEM_INSTRUCTIONS
from tools import remember_note

load_dotenv(".env.local")

server = AgentServer()


# agent_name is deliberately left unset. Without it the server uses automatic
# dispatch and joins every new room, which is what we want while there is no
# token server to ask for the agent by name. Phase 2 can set a name here and
# have token_server.py attach a RoomAgentDispatch to the token instead.
# https://docs.livekit.io/agents/server/agent-dispatch/
@server.rtc_session()
async def rayneo_assistant(ctx: JobContext) -> None:
    session = AgentSession(
        **build_session_model(),
        # TODO(battery): cut the frame rate for the glasses by passing
        #   video_sampler=VoiceActivityVideoSampler(speaking_fps=..., silent_fps=...)
        #   here, from livekit.agents.voice. Defaults are 1 fps while the wearer
        #   speaks and 0.3 fps otherwise. media_resolution on the model in
        #   config.py is the other knob on the same cost/battery tradeoff.
        #   https://docs.livekit.io/agents/logic/sessions/#video-sampling
    )

    await session.start(
        agent=Agent(
            instructions=SYSTEM_INSTRUCTIONS,
            tools=[remember_note],
        ),
        room=ctx.room,
        # Camera frames from the glasses stream inline with the audio session.
        room_options=room_io.RoomOptions(video_input=True),
    )

    # No opening greeting on purpose. gemini-3.1-flash-live-preview rejects
    # send_client_content after the first model turn, so the plugin ignores
    # session.generate_reply() on 3.1 models and just logs a warning. The
    # wearer speaks first.
    # https://docs.livekit.io/agents/models/realtime/plugins/gemini/#gemini-3-1-compatibility


if __name__ == "__main__":
    agents.cli.run_app(server)
