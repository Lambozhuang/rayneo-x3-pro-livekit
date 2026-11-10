"""The GPT path: GPT-Live speaks, the brain looks by itself every few seconds, and a second line reads every frame.

    glasses --audio--> SFU --> this process --ws--> gpt-live-1 (knows every step)
            --video-->     --> FrameTap (frames kept for the brain and the moments, none to the voice)
    brain: a frame every few seconds + the lines said since its last look --> one vision call --> what it sees,
           kept to itself, maybe tell, say, set_progress or show
            <--thinking (tell: a fact for later) or commentary (say: the user hears it now; the progress moved)-- brain
    moments: every frame --> the Decisions API --> which moment it shows: a brick held and which (one commentary,
           "Camera: yes, that's the one."), the step's brick on the plate with the hand gone (the brain looks now)
            <--audio-- SFU <-- this process <-- gpt-live-1
            <--step list (participant attributes)-- this process (the step is the brain's)

The voice owns the conversation and answers from the steps and from what the
brain has told it; it is told not to hand anything over, and a hand-over it makes
all the same is closed at once (brain.py). No VAD is passed to the session: the
model listens while it speaks and stops on its own.

In a trial of the placement game of the user study (guide.game == "place", gpt/place.py) a judge stands where the brain
stands: it looks once per placement, when the second line says the brick lies on the plate with the hand gone, and the
voice says its verdict in a fixed phrase; the second line says nothing about the brick in the hand. In free play
(guide.game == "free", a guide with no steps) the brain watches as in a build with rules that answer only what the user
asks, the voice keeps company, and the second line does not run, having no step's brick to judge. In game B of the
user study, build and report (the glasses ask for it on an ordinary sheet, Build.game == "report", gpt/report.py), the
brain watches the same way with the reporting rules, and the game shows the sheet in three batches, hears the voice's
sentence for the next one and ends the trial on the brain's report of the last. In game A, pick the brick (guides/a-<k>,
gpt/pick.py), no brain runs: the game names the colours, reads every frame with the Decisions line's model itself and has
the voice say the verdicts.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    MetricsCollectedEvent,
    room_io,
)
from livekit.agents.llm import ChatMessage
from livekit.agents.metrics import RealtimeModelMetrics

from camera import watch_camera
from env import language, require_env
from frames import FrameTap
from gpt.brain import SAY, SAY_ANSWERING, TELL, TOOLS, Brain, make_model
from gpt.config import Settings, build_live_model
from gpt.moments import Moments
from gpt.place import PlaceGame
from gpt.pick import HUES, PickGame
from gpt.prompts import (FREE_START, PICK_START, REPORT_START, free_brain, free_persona, pick_persona, place_persona,
                         place_start, report_brain, report_persona, voice_persona)
from gpt.report import NEXT_SAID, ReportGame
from guide import Build, picked_game, picked_guide, publish_build
from qoe import LabRun, deliver, write_report
from runlog import RunLog

logger = logging.getLogger("rayneo-agent")

OVER_QUIET_S = 2.0  # the voice has said the build is done once it has been silent this long after it; it pauses up to a second between sentences
OVER_CAP_S = 15.0  # the call ends this long after the last step even if the voice said nothing

server = AgentServer()


# Explicit dispatch: the api puts AGENT_NAME into every token it signs, and
# the agent joins only rooms that name it.
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    settings = Settings.from_env()
    lang = language()
    guide = picked_guide(ctx.job.metadata)
    # "" for a build; "place" or "free" from the guide's file; "report" when the glasses asked for game B on this sheet.
    game = guide.game or picked_game(ctx.job.metadata)
    logger.info(settings.experiment_line(guide.name) + (f" game={game}" if game else ""))
    # The lab console's run, when the glasses were started by it (qoe.py); the record goes to the console at the end.
    lab = LabRun.from_metadata(ctx.job.metadata)
    # The call's record (runlog.py): what happened, in order, with every field; deploy/report.py reads it.
    record = RunLog(os.environ.get("RUN_DIR"), ctx.room.name)
    if lab and not record.dir:
        raise RuntimeError("a lab run needs RUN_DIR: the record is what goes to the console")
    record.event("call", wall_ms=record.wall_ms, room=ctx.room.name, lab=asdict(lab) if lab else None, guide=guide.name, game=game or None, language=lang, commit=os.environ.get("GIT_COMMIT") or None,
                 settings=asdict(settings), steps=[s.name for s in guide.steps])
    tap = FrameTap(on_first=lambda f: record.event("camera", first_frame=f"{f.width}x{f.height}"))
    build = Build(guide=guide, run=ctx.room.name, game=game)
    session = AgentSession(video_sampler=tap, llm=build_live_model(settings))
    model = make_model(settings.brain_provider, settings.brain_model, settings.brain_detail)
    if game == "pick":
        # Game A, pick the brick: no brain; the game paces the picks, reads the frames with the Decisions model itself
        # and gives the voice its lines.
        if not settings.moments_on:
            raise RuntimeError("the pick game needs MOMENTS=on: the Decisions line is what reads the brick in the hand")
        brain = PickGame(session, build, tap, record, settings)
    elif game == "report":
        # Game B, build and report: the brain watches as in free play, with the reporting rules and no task text (it
        # does not know the sheet), and say is its one tool: the voice hears nothing but the answers to its hand-overs,
        # since a tell reaches it as a silent fact and it answered the second question from one before the brain's say,
        # which is what ends the trial (the run of 2026-11-09 14:49). The game shows the batches, hears the voice's
        # sentence for the next one and ends the trial on the brain's report of the last.
        brain = ReportGame(Brain(session, build, tap, model, settings.brain_effort, settings.brain_watch_side,
                                 settings.brain_watch_every, lang, settings.brain_timeout, record,
                                 instructions=report_brain(guide, lang), tools=[SAY_ANSWERING], answer_delegations=True),
                           build, record)
    elif game == "free":
        brain = Brain(session, build, tap, model, settings.brain_effort, settings.brain_watch_side,
                      settings.brain_watch_every, lang, settings.brain_timeout, record,
                      instructions=free_brain(guide, lang), tools=[TELL, SAY])
    elif game == "place":
        # The judge has the brain's surface (start_watching, stop_watching, voice_now, on_delegation, instructions)
        # and looks once per placement, called by the second line, instead of watching.
        if not settings.moments_on:
            raise RuntimeError("the placement game needs MOMENTS=on: the Decisions line is what calls its judgement")
        brain = PlaceGame(session, build, model, settings.brain_effort, settings.brain_watch_side, lang,
                          settings.brain_timeout, record)
    else:
        brain = Brain(session, build, tap, model, settings.brain_effort, settings.brain_watch_side,
                      settings.brain_watch_every, lang, settings.brain_timeout, record, confirms_bricks=not settings.moments_on)
    # The second line (moments.py), or none: with MOMENTS=off the brain confirms the brick in the hand itself. In the
    # placement game it says nothing of the brick in the hand and only calls the judgement; in free play there is no
    # step's brick for it to read, so it does not run.
    moments = Moments(session, build, tap, brain, record, settings.moments_side, settings.moments_sure,
                      settings.moments_yes_at, settings.moments_not_at, settings.moments_hold_s, settings.moments_model,
                      settings.moments_detail, lines=not game) if settings.moments_on and game not in ("free", "report", "pick") else None
    if game == "place":
        brain.moments = moments
    if game in ("free", "report") and settings.moments_on:
        logger.info("%s: the second line does not run, there being no step's brick to read", game)
    persona = (place_persona(guide, lang) if game == "place" else free_persona(lang) if game == "free"
               else report_persona(lang, NEXT_SAID) if game == "report"
               else pick_persona(list(HUES), lang) if game == "pick"
               else voice_persona(guide, lang))
    record.text("brain.txt", brain.instructions)
    record.text("brain-tools.json", json.dumps(
        [{"name": n, "description": d, "input_schema": p} for n, d, p in TOOLS], indent=2))
    record.text("voice.txt", persona)

    # Two bills. The voice model is priced by the second and reports cumulative
    # session time about once a minute (usage:); the brain by the token, on its
    # brain: lines.
    @session.on("metrics_collected")
    def _log_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        if isinstance(m, RealtimeModelMetrics) and m.session_duration:
            logger.info("usage: voice +%.0fs", m.session_duration)

    @session.on("close")
    def _log_close(ev) -> None:
        brain.stop_watching()  # the call is over: no more looks at a camera that has stopped sending
        if moments:
            moments.stop()
        record.event("closed", reason=str(getattr(ev.reason, "value", ev.reason)), error=str(ev.error) if ev.error else None)
        # The call is over when the session is: end the job now, not when livekit-server closes the room, which is
        # 20 s after the glasses leave (departure_timeout), so the record closes and reaches the console at once.
        ctx.shutdown(reason=f"session closed: {getattr(ev.reason, 'value', ev.reason)}")

    async def _log_usage() -> None:
        brain.stop_watching()
        if moments:
            moments.stop()
        logger.info("usage: %s camera_frames=%d moments=%d", session.usage, tap.count, moments.count if moments else 0)
        record.event("end", voice_s=sum(getattr(u, "session_duration", 0) for u in session.usage.model_usage),
                     camera_frames=tap.count, moments=moments.count if moments else 0)
        record.close()
        if lab:
            path = write_report(lab, record.dir, record.wall_ms, round(time.time() * 1000),
                                {"steps": len(guide.steps), "done": build.step, "finished": build.finished})
            await asyncio.to_thread(deliver, path, 20)

    ctx.add_shutdown_callback(_log_usage)

    # Both sides as text, into the log and the record (the brain reads the same turns from the session's
    # history); a turn is closed when the audio goes quiet, so these lines trail the speech.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)
            if ev.item.role == "assistant":
                brain.voice_now = ""  # the turn is in the history now
            if ev.item.role in ("user", "assistant"):
                m = ev.item.metrics or {}
                record.event("said", who="wearer" if ev.item.role == "user" else "voice", text=ev.item.text_content,
                             interrupted=ev.item.interrupted,
                             started=record.t(m["started_speaking_at"]) if m.get("started_speaking_at") else None,
                             stopped=record.t(m["stopped_speaking_at"]) if m.get("stopped_speaking_at") else None)

    # The glasses' camera track: the full layer, and what decodes it into the record (camera.py).
    watch_camera(ctx.room, record, logger)

    await session.start(
        agent=Agent(instructions=persona),
        room=ctx.room,
        # GPT-Live's transcript already trails its audio; the framework's
        # pacing of text to playout only added to that on the glasses.
        room_options=room_io.RoomOptions(
            video_input=True, text_output=room_io.TextOutputOptions(sync_transcription=False)
        ),
    )
    duplex = session.current_agent.duplex_session
    duplex.on("delegation_created", brain.on_delegation)

    # The call's timeline in the log: who is speaking when, and what GPT-Live itself reports about handing over
    # (its raw events, so a delegation the plugin did not pass on would still show).
    @session.on("user_state_changed")
    def _log_wearer(ev) -> None:
        logger.info("live: wearer %s -> %s", ev.old_state, ev.new_state)
        record.event("state", who="wearer", old=ev.old_state, new=ev.new_state)

    @session.on("agent_state_changed")
    def _log_voice(ev) -> None:
        logger.info("live: voice %s -> %s", ev.old_state, ev.new_state)
        record.event("state", who="voice", old=ev.old_state, new=ev.new_state)

    def _log_live_event(event: dict) -> None:
        etype = event.get("type", "")
        # GPT-Live bills by the session second: from session.started to session.closed, whose usage is the total
        if etype == "session.started":
            sid = (event.get("session") or {}).get("id")
            logger.info("gpt-live: session started %s (billed from here)", sid or "")
            record.event("live", type="session.started", id=sid)
        elif etype == "session.closed":
            secs = (event.get("usage") or {}).get("seconds")
            logger.info("gpt-live: session closed (%s), %s s billed", event.get("reason"), secs)
            record.event("live", type="session.closed", reason=event.get("reason"), seconds=secs)
        elif etype == "session.delegation.created":
            d = event.get("delegation") or {}
            logger.info("live: event delegation.created id=%s target=%s offset_ms=%s", d.get("id"), d.get("target"),
                        event.get("offset_ms"))
            record.event("live", type="delegation.created", id=d.get("id"), target=d.get("target"),
                         offset_ms=event.get("offset_ms"))
        elif etype in ("session.commentary.appended", "session.thinking.appended", "session.instructions.appended"):
            # the receipt comes at the estimated end of injection, not when it is spoken
            logger.info("live: event %s for %s start_ms=%s end_ms=%s", etype.split(".", 1)[1],
                        event.get("client_event_id"), event.get("start_ms"), event.get("end_ms"))
            record.event("live", type=etype.split(".", 1)[1], for_id=event.get("client_event_id"),
                         start_ms=event.get("start_ms"), end_ms=event.get("end_ms"))
        elif etype == "error":
            logger.warning("live: event error %s", event.get("error"))
            record.event("live", type="error", error=event.get("error"))

    # Everything this process sends to GPT-Live, as it goes on the wire (the plugin's own events too, such as the
    # greeting's commentary from generate_reply); the mic audio is left out. session.start went before this hook.
    def _log_live_sent(event: dict) -> None:
        etype = event.get("type", "")
        if etype == "session.input_audio.append":
            return
        if etype in ("session.commentary.append", "session.thinking.append", "session.instructions.append"):
            logger.info("live: sent %s id=%s delegation=%s: %s", etype.split(".", 1)[1], event.get("event_id"),
                        event.get("delegation_id") or "none", event.get("content"))
            record.event("live_sent", type=etype.split(".", 1)[1], id=event.get("event_id"),
                         delegation=event.get("delegation_id"), content=event.get("content"))
        else:
            logger.info("live: sent %s %s", etype, json.dumps({k: v for k, v in event.items() if k != "type"}))
            record.event("live_sent", type=etype, event=event)

    # What the voice is saying right now, for the brain's looks (Brain.voice_now, brain.py _message), and every
    # transcript delta of either side into the record with its time: a `said` event comes only when a turn ends and
    # holds the whole turn, so a line the voice cut into a sentence (moments.py, brain.py CUT_IN) could not be timed
    # from the record before 2026-11-06; `start_ms` and `end_ms` are the delta's place on GPT-Live's session timeline.
    def _voice_words(event: dict) -> None:
        etype = event.get("type")
        if etype == "session.output_transcript.delta":
            brain.voice_now += event.get("delta") or ""
            record.event("voice_delta", text=event.get("delta"), start_ms=event.get("start_ms"), end_ms=event.get("end_ms"))
        elif etype == "session.input_transcript.delta":
            record.event("wearer_delta", text=event.get("delta"), start_ms=event.get("start_ms"), end_ms=event.get("end_ms"))

    duplex.on("openai_client_event_queued", _log_live_sent)
    duplex.on("openai_server_event_received", _log_live_event)
    duplex.on("openai_server_event_received", _voice_words)
    if getattr(duplex, "_session_id", None):  # started before the hook above was in place
        logger.info("gpt-live: session started %s (billed from here; before this line)", duplex._session_id)
        record.event("live", type="session.started", id=duplex._session_id, before_hook=True)

    async def _camera_watch() -> None:
        await asyncio.sleep(10)
        if tap.count == 0:
            logger.warning("camera: no frame 10 s into the call; the glasses are not sending video")
            record.event("camera", none_after_s=10)

    asyncio.create_task(_camera_watch(), name="camera_watch")

    wearer = await ctx.wait_for_participant()
    logger.info("session for user=%s room=%s", wearer.identity, ctx.room.name)
    record.event("wearer", joined=wearer.identity)

    # The glasses' link as the SFU sees it: who comes and goes (with the SFU's reason) and its coarse quality score.
    @ctx.room.on("participant_connected")
    def _log_join(p: rtc.RemoteParticipant) -> None:
        logger.info("link: %s joined", p.identity)
        record.event("wearer", joined=p.identity)

    @ctx.room.on("participant_disconnected")
    def _log_leave(p: rtc.RemoteParticipant) -> None:
        reason = rtc.DisconnectReason.Name(p.disconnect_reason) if p.disconnect_reason is not None else None
        logger.info("link: %s left (%s)", p.identity, reason or "no reason given")
        record.event("wearer", left=p.identity, reason=reason)

    @ctx.room.on("connection_quality_changed")
    def _log_quality(p: rtc.Participant, quality: rtc.ConnectionQuality) -> None:
        if isinstance(p, rtc.RemoteParticipant):
            name = quality.name.removeprefix("QUALITY_").lower()
            logger.info("link: %s quality %s", p.identity, name)
            record.event("quality", who=p.identity, quality=name)
    build.start()
    # The task's bounds in the record: `build` started here, finished when the last step is recorded as done.
    record.event("build", started=True, steps=len(guide.steps))
    record.event("step", done=None, now=1)
    await publish_build(build)
    brain.start_watching()
    if moments:
        moments.start()

    # The task ends by itself: once the brain has recorded the last step as done, the voice says so (the Progress
    # commentary), and when it has stopped speaking the glasses are told to hang up through Build.over in the published
    # attributes (BuildSteps.kt), so the wearer has nothing to remember to end a task (the pilot of 2026-11-03). The
    # brain may still move the progress back while the voice speaks; then the wait starts over. The silence is measured
    # here, at the agent's end of the audio; the glasses wait for a second of silence at their own decoder before they
    # hang up (VoiceAssistantScreen.kt), so the last words are heard whatever the network's delay. The session closes
    # as it does whenever the glasses leave.
    async def _end_when_finished() -> None:
        while True:
            while not build.finished:
                await asyncio.sleep(0.5)
            t_finished, spoke, quiet_since = time.monotonic(), False, None
            while build.finished:
                if session.agent_state == "speaking":
                    spoke, quiet_since = True, None
                elif spoke:
                    quiet_since = quiet_since or time.monotonic()
                    if time.monotonic() - quiet_since >= OVER_QUIET_S:
                        break
                if time.monotonic() - t_finished >= OVER_CAP_S:
                    break
                await asyncio.sleep(0.1)
            else:
                continue  # the progress moved back before the end: the build is on again
            build.over = True
            after = time.monotonic() - t_finished
            logger.info("build: over, the voice has %s; the glasses are told to hang up %.1f s after the last step",
                        "said so" if spoke else "said nothing", after)
            record.event("over", after_finish_s=round(after, 1), spoke=spoke)
            await publish_build(build)
            return

    asyncio.create_task(_end_when_finished(), name="end_when_finished")

    # generate_reply on GPT-Live is commentary: a request the model may decline.
    handle = session.generate_reply(
        instructions=place_start(guide) if game == "place" else FREE_START if game == "free"
        else REPORT_START if game == "report" else PICK_START if game == "pick" else (
            "Greet the user in one short sentence, say you can see their table, and ask whether to start, as you would "
            "across the table. Nothing else: no task name, no list of what they can do, no step yet; the first step "
            "comes when they say yes."
        )
    )
    await handle
    if handle.exception() is not None:
        logger.warning("the model declined to greet the wearer")


if __name__ == "__main__":
    agents.cli.run_app(server)
