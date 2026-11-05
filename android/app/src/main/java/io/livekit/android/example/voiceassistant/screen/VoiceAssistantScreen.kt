package io.livekit.android.example.voiceassistant.screen

import android.util.Log
import android.widget.Toast
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import io.livekit.android.annotations.Beta
import io.livekit.android.compose.local.SessionScope
import io.livekit.android.compose.local.requireRoom
import io.livekit.android.compose.state.SessionConnectOptions
import io.livekit.android.compose.state.SessionConnectTrackOptions
import io.livekit.android.compose.state.SessionOptions
import io.livekit.android.compose.state.rememberAgent
import io.livekit.android.compose.state.rememberLocalMedia
import io.livekit.android.compose.state.rememberSession
import io.livekit.android.compose.state.rememberSpeakingParticipants
import io.livekit.android.example.voiceassistant.CallLog
import io.livekit.android.example.voiceassistant.Exposure
import io.livekit.android.example.voiceassistant.FrameDump
import io.livekit.android.example.voiceassistant.Lab
import io.livekit.android.example.voiceassistant.LinkStatsLog
import io.livekit.android.example.voiceassistant.Recording
import io.livekit.android.example.voiceassistant.SpeechEdgeLog
import io.livekit.android.room.track.LocalAudioTrack
import io.livekit.android.room.track.LocalVideoTrack
import io.livekit.android.room.track.RemoteAudioTrack
import io.livekit.android.example.voiceassistant.rememberCanEnableCamera
import io.livekit.android.example.voiceassistant.rememberCanEnableMic
import io.livekit.android.example.voiceassistant.requirePermissions
import io.livekit.android.example.voiceassistant.ui.BuildProgress
import io.livekit.android.example.voiceassistant.ui.CallLayout
import io.livekit.android.example.voiceassistant.ui.CameraPreview
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.rememberBuildProgress
import io.livekit.android.example.voiceassistant.ui.rememberPicture
import io.livekit.android.example.voiceassistant.ui.rememberEngineState
import io.livekit.android.example.voiceassistant.viewmodel.VoiceAssistantViewModel
import kotlinx.coroutines.delay
import kotlinx.serialization.Serializable

/** Tag of the two lines that bound a call in the glasses' log; deploy/pull_run.py reads them with the link and speech lines. */
private const val CALL_TAG = "rayneo-call"

@Serializable
data class VoiceAssistantRoute(
    val tokenEndpoint: String,
    /** Bearer credential for the token endpoint; empty sends no header. */
    val credential: String = "",
    /** The build picked on the connect screen (Tasks), or the one the lab console named (Lab). */
    val task: String = "",
    /** The lab console's run this call is, and the console's address, for the agent to report the call to (Lab);
     *  all empty for a call the glasses started themselves. */
    val sid: String = "",
    val runId: Int = 0,
    val console: String = "",
)

@Composable
fun VoiceAssistantScreen(
    viewModel: VoiceAssistantViewModel,
    onEndCall: () -> Unit,
) {
    VoiceAssistant(
        viewModel = viewModel,
        modifier = Modifier.fillMaxSize(),
        onEndCall = onEndCall
    )
}

/**
 * The call, laid out for glasses. Nothing on this screen is tappable: there is
 * no pointer, no keyboard, and the only control the wearer has is the temple
 * strip, which MainActivity turns into "end the call" outside lab mode; in lab mode the console and the finished
 * build end the call (Lab, the agent's `rayneo.call.over`). So the phone starter's
 * chat box, control bar, screenshare and camera-flip are gone, and what is
 * left is what a wearer actually needs while talking:
 *
 *   top           the build's title
 *   left column   the steps, all five in view, the current one highlighted; what the camera sees at the bottom
 *   right column  who has the floor (you / listening / thinking / speaking) in a framed head, the agent's
 *                 lines, newest at the bottom and shown whole or not at all, the agent's picture when the
 *                 wearer asked for one, and what the model heard the wearer say along the bottom
 * Nothing scrolls: the glasses have no pointer, so what does not fit is left out, never half shown.
 *
 * Mic and camera are always on. Toggling them was the starter's idea of a
 * feature; here it is a way to silently break the assistant. The camera's view
 * is shown so that the wearer knows what the assistant can see and can bring
 * a brick into it; it is the same square the brain gets (CameraPreview).
 */
@OptIn(Beta::class, ExperimentalPermissionsApi::class)
@Composable
fun VoiceAssistant(
    viewModel: VoiceAssistantViewModel,
    modifier: Modifier = Modifier,
    onEndCall: () -> Unit
) {
    requirePermissions(microphone = true, camera = true)

    val canEnableMic by rememberCanEnableMic()
    val canEnableVideo by rememberCanEnableCamera()

    val session = rememberSession(
        tokenSource = viewModel.tokenSource,
        options = SessionOptions(
            room = viewModel.room
        )
    )

    val context = LocalContext.current

    SessionScope(session = session) { session ->

        val room = requireRoom()
        // What the glasses measure during this call, for the report to the lab console; see CallLog.
        remember { CallLog.begin() }

        // The camera first, the room second. The camera is opened here, before anything connects, so that its
        // exposure has settled and this launch's compensation is on it (Exposure.apply) by the time the agent sees
        // a frame; the track is published once the room is connected, below. A compensation set while the
        // camera comes up is taken against its dark start (Exposure).
        var cameraTrack by remember { mutableStateOf<LocalVideoTrack?>(null) }

        // Start the session when we have the permissions.
        // Permission removals kill the app, so this is a one-way transition.
        LaunchedEffect(canEnableMic, canEnableVideo) {
            if (!canEnableMic || !canEnableVideo) {
                return@LaunchedEffect
            }

            val track = room.localParticipant.createVideoTrack(options = room.localParticipant.videoTrackCaptureDefaults)
            track.startCapture()
            cameraTrack = track
            Exposure.apply(track)
            val cameraAt = System.currentTimeMillis()
            Log.i(CALL_TAG, "camera ready at=$cameraAt")
            CallLog.add("call", mapOf("what" to "camera ready"), cameraAt)

            // No ICE overrides here on purpose. `adb reverse` cannot carry WebRTC
            // media at all, and ICE-TCP does not rescue it — see the README section
            // on the USB tunnel. Standard WebRTC over the LAN is the only media path.
            // Join without a microphone; it is switched on below, once the
            // agent is there to hear it. The alternative, LiveKit's pre-connect
            // buffer (record from join, hand the recording over when the agent
            // subscribes), keeps every word but delivers the first ones in a
            // burst one or two seconds late. This is a network-quality test
            // bed: connection setup is not what is measured, and a first reply
            // that is slow for an unrelated reason would be one more variable.
            val result = session.start(
                SessionConnectOptions(
                    tracks = SessionConnectTrackOptions(microphoneEnabled = false, usePreconnectBuffer = false)
                )
            )

            if (result.isFailure) {
                Toast.makeText(context, "Error connecting to the session.", Toast.LENGTH_SHORT).show()
                onEndCall()
                return@LaunchedEffect
            }
            room.localParticipant.publishVideoTrack(track)
        }

        // End the session when leaving the screen, whichever side ended it: a double tap leaves the screen, and a
        // server-side end leaves it through onEndCall below. The call's end in the glasses' log is written with the
        // lab report, further down.
        DisposableEffect(Unit) {
            onDispose {
                room.name?.let { Recording.end(it) }
                cameraTrack?.let { runCatching { it.stopCapture() } }  // opened before the room, so closed by hand too
                session.end()
            }
        }

        // And leave the screen when the session ends: the room was closed on
        // the server, or the connection was lost and the SDK gave up
        // reconnecting. A brief loss is RECONNECTING, not DISCONNECTED,
        // so this does not fire for a network blip; the banner shows that.
        // The room name on the start line is the one in the server's record
        // (backend/runs/<UTC start>-<room>/), so the two logs pair up by it.
        LaunchedEffect(Unit) {
            session.waitUntilConnected()
            val startsAt = System.currentTimeMillis()
            val codec = room.videoTrackPublishDefaults.videoCodec  // what the camera track is published as
            Log.i(CALL_TAG, "call starts room=${room.name} codec=$codec at=$startsAt")
            CallLog.add("call", mapOf("what" to "starts", "room" to room.name, "codec" to codec), startsAt)
            session.waitUntilDisconnected()
            onEndCall()
        }
        val localMedia = rememberLocalMedia()

        // The mic does not start until the session is fully connected:
        // `waitUntilConnected()` does not return while the peer connections are
        // still negotiating, so with an unreachable SFU it parks here forever
        // and the mic is never opened. See the README section on capture on the glasses.
        //
        // The mic additionally waits for the agent to report "listening", so
        // that nothing said reaches a room nobody is subscribed to. Until then
        // the banner says "Connecting"; "Ready" means the mic is live and the
        // agent hears it. Audio pushed to the model before its own WebSocket
        // is open is queued by the plugin, not dropped, so "listening" is early
        // enough.
        val agent = rememberAgent()
        LaunchedEffect(canEnableMic) {
            session.waitUntilConnected()
            agent.waitUntilAvailable()
            localMedia.setMicrophoneEnabled(canEnableMic)
        }

        val micTrack = localMedia.microphoneTrack?.publication?.track as? LocalAudioTrack
        val agentAudio = agent.audioTrack?.publication?.track as? RemoteAudioTrack

        // The link as WebRTC measures it here, one line per stream every few seconds. See LinkStatsLog.
        LaunchedEffect(cameraTrack) {
            cameraTrack?.let { LinkStatsLog.upVideo(it) }
        }
        LaunchedEffect(micTrack) {
            if (micTrack != null) LinkStatsLog.upAudio(micTrack)
        }
        LaunchedEffect(agentAudio) {
            if (agentAudio != null) LinkStatsLog.downAudio(agentAudio)
        }

        // When the wearer's voice stops at the microphone and when the agent's voice arrives, as wall clock
        // times. See SpeechEdgeLog; the mic's threshold is higher because the room is in it. The agent's edges go
        // into the lab report; the wearer's stay in logcat.
        DisposableEffect(micTrack) {
            val edges = if (micTrack != null) SpeechEdgeLog("wearer", threshold = 1000) else null
            if (edges != null) micTrack!!.addSink(edges)
            onDispose { if (edges != null) micTrack!!.removeSink(edges) }
        }
        // The agent's edges are kept in state: the hang-up on `over` below waits for the agent's voice to fall silent here.
        val agentEdges = remember(agentAudio) { if (agentAudio != null) SpeechEdgeLog("agent", threshold = 500, report = true) else null }
        DisposableEffect(agentEdges) {
            if (agentEdges != null) agentAudio!!.addSink(agentEdges)
            onDispose { if (agentEdges != null) agentAudio!!.removeSink(agentEdges) }
        }

        // The call to disk when the app was launched with --ez record true: the camera, the mic and the
        // agent's voice, each from its track as it is attached. See Recording. The camera track exists before
        // the room is connected and has a name, so its effect also waits for the connection.
        val connected = session.isConnected
        DisposableEffect(cameraTrack, connected) {
            val rec = if (connected) cameraTrack?.let { room.name?.let { r -> Recording.forCall(context, r, viewModel.eglContext) } } else null
            if (rec != null) cameraTrack!!.addRenderer(rec.video)
            onDispose { if (rec != null) cameraTrack!!.removeRenderer(rec.video) }
        }
        DisposableEffect(micTrack) {
            val rec = micTrack?.let { room.name?.let { r -> Recording.forCall(context, r, viewModel.eglContext) } }
            if (rec != null) micTrack!!.addSink(rec.mic)
            onDispose { if (rec != null) micTrack!!.removeSink(rec.mic) }
        }
        DisposableEffect(agentAudio) {
            val rec = agentAudio?.let { room.name?.let { r -> Recording.forCall(context, r, viewModel.eglContext) } }
            if (rec != null) agentAudio!!.addSink(rec.agent)
            onDispose { if (rec != null) agentAudio!!.removeSink(rec.agent) }
        }

        // Debug only: raw frames to disk when the marker file exists. See FrameDump.
        DisposableEffect(cameraTrack) {
            val dump = if (cameraTrack != null) FrameDump.ifArmed(context) else null
            if (dump != null) cameraTrack!!.addRenderer(dump)
            onDispose { if (dump != null) cameraTrack!!.removeRenderer(dump) }
        }

        val speakers by rememberSpeakingParticipants(room)
        val wearerSpeaking = speakers.any { it.identity == room.localParticipant.identity }
        // Has an agent ever been here? Lets "it left" read differently from
        // "it has not arrived yet"; see Phase.of.
        var sawAgent by remember { mutableStateOf(false) }
        LaunchedEffect(agent.agentParticipant) {
            if (agent.agentParticipant != null) sawAgent = true
        }
        val engineState by rememberEngineState(room)
        val buildProgress by rememberBuildProgress(agent.agentParticipant)
        val picture by rememberPicture(room, agent.agentParticipant)
        val phase = Phase.of(agent, wearerSpeaking, session, engineState, sawAgent, localMedia.isMicrophoneEnabled)
        val remaining by rememberRemaining(viewModel.route.sid, viewModel.route.runId)

        // Every call ends in the glasses' log here, whoever ended it: the console's end_task, the wearer's double tap or
        // the room closing. A lab run is then reported to the console with how far the build got, as last published
        // (when the agent left first its attributes are gone, and that must not read as no progress), and with what
        // the glasses measured during the call (CallLog). A call the glasses started by themselves has no run and
        // nothing more happens.
        var lastBuild by remember { mutableStateOf(BuildProgress.NONE) }
        LaunchedEffect(buildProgress) { if (buildProgress.steps.isNotEmpty()) lastBuild = buildProgress }
        // The agent ended the task: the build is finished and the voice has said so (gpt/agent.py). The agent judged
        // the silence at its own end; here the last words may still be on their way, so the call ends once the agent's
        // voice has been silent at this decoder for OVER_SILENCE_MS, or after OVER_WAIT_MS at most, as a double tap
        // would end it, and the run is reported as ended by the finished build.
        LaunchedEffect(buildProgress.over) {
            if (buildProgress.over) {
                Log.i(CALL_TAG, "call over: the agent says the build is finished, room=${room.name}")
                CallLog.add("call", mapOf("what" to "over", "room" to room.name))
                val t0 = System.currentTimeMillis()
                while (System.currentTimeMillis() - t0 < OVER_WAIT_MS) {
                    val e = agentEdges
                    if (e == null || (!e.sounding && System.currentTimeMillis() - e.lastLoud >= OVER_SILENCE_MS)) break
                    delay(100)
                }
                Log.i(CALL_TAG, "call over: the agent's voice has been silent here; hanging up ${System.currentTimeMillis() - t0} ms after over")
                Lab.finished(viewModel.route.sid, viewModel.route.runId)
                onEndCall()
            }
        }
        DisposableEffect(Unit) {
            onDispose {
                val endsAt = System.currentTimeMillis()
                Log.i(CALL_TAG, "call ends room=${room.name} at=$endsAt")
                CallLog.add("call", mapOf("what" to "ends", "room" to room.name), endsAt)
                Lab.callEnded(viewModel.route.sid, viewModel.route.runId, room.name, lastBuild.current, lastBuild.steps.size, CallLog.take())
            }
        }

        // Everything above the Eyes call is hoisted on purpose: that layout is
        // composed once per eye, so a `remember` inside it would exist twice
        // and the two copies could disagree. See Eyes.
        Eyes {
            CallLayout(
                progress = buildProgress,
                phase = phase,
                picture = picture,
                preview = { m -> CameraPreview(track = cameraTrack, modifier = m) },
                remaining = remaining,
                modifier = modifier,
            )
        }
    }
}

/** How long the agent's voice must have been silent at the glasses' decoder before an `over` hangs up, and the longest the hang-up waits. */
private const val OVER_SILENCE_MS = 1000L
private const val OVER_WAIT_MS = 5000L

/**
 * The time left of a lab run's limit, "m:ss", counted down each second from the console's `max_duration_s` and the
 * task's start (Lab.Run); null for a call without a run or a limit. The participant sees it on the title line, so the
 * end the console brings does not come as a surprise (the pilot of 2026-11-03).
 */
@Composable
private fun rememberRemaining(sid: String, runId: Int): State<String?> {
    val state = remember { mutableStateOf<String?>(null) }
    LaunchedEffect(sid, runId) {
        while (true) {
            val r = Lab.run?.takeIf { it.sid == sid && it.runId == runId && it.maxDurationS > 0 }
            state.value = r?.let {
                val left = (it.maxDurationS - (System.currentTimeMillis() - it.startedAt) / 1000).coerceAtLeast(0)
                "%d:%02d".format(left / 60, left % 60)
            }
            delay(1000)
        }
    }
    return state
}
