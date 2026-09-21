package io.livekit.android.example.voiceassistant.screen

import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
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
import io.livekit.android.compose.state.rememberSessionMessages
import io.livekit.android.compose.state.rememberSpeakingParticipants
import io.livekit.android.compose.ui.VideoTrackView
import io.livekit.android.example.voiceassistant.FrameDump
import io.livekit.android.example.voiceassistant.VideoStatsLog
import io.livekit.android.room.track.LocalVideoTrack
import io.livekit.android.example.voiceassistant.rememberCanEnableCamera
import io.livekit.android.example.voiceassistant.rememberCanEnableMic
import io.livekit.android.example.voiceassistant.requirePermissions
import io.livekit.android.example.voiceassistant.ui.BuildSteps
import io.livekit.android.example.voiceassistant.ui.Captions
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.ModelView
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.PhaseBanner
import io.livekit.android.example.voiceassistant.ui.ReplyLatencyProbe
import io.livekit.android.example.voiceassistant.ui.rememberBuildProgress
import io.livekit.android.example.voiceassistant.ui.rememberEngineState
import io.livekit.android.example.voiceassistant.viewmodel.VoiceAssistantViewModel
import kotlinx.serialization.Serializable

@Serializable
data class VoiceAssistantRoute(
    val tokenEndpoint: String,
    /** Bearer credential for the token endpoint; empty sends no header. */
    val credential: String = "",
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
 * strip, which MainActivity turns into "end the call". So the phone starter's
 * chat box, control bar, screenshare and camera-flip are gone, and what is
 * left is what a wearer actually needs while talking:
 *
 *   top-left      who has the floor (you / listening / thinking / speaking),
 *                 then the build's steps with the current one highlighted
 *   top-right     the reference model the agent streams (see ModelView), and
 *                 under it a small camera self-preview, the only proof that
 *                 capture is running
 *   bottom        the last three turns, what the model heard in green
 *
 * Mic and camera are always on. Toggling them was the starter's idea of a
 * feature; here it is a way to silently break the assistant.
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

        // Start the session when we have at least microphone permissions.
        // Permission removals kill the app, so this is a one-way transition.
        LaunchedEffect(canEnableMic) {
            if (!canEnableMic) {
                return@LaunchedEffect
            }

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
            }
        }

        // End the session when leaving the screen.
        DisposableEffect(Unit) {
            onDispose {
                session.end()
            }
        }

        // And leave the screen when the session ends: the agent hung up
        // (end_call deletes the room), or the connection was lost and the SDK
        // gave up reconnecting. A brief loss is RECONNECTING, not DISCONNECTED,
        // so this does not fire for a network blip; the banner shows that.
        LaunchedEffect(Unit) {
            session.waitUntilConnected()
            session.waitUntilDisconnected()
            onEndCall()
        }

        val room = requireRoom()
        val localMedia = rememberLocalMedia()
        val isCameraEnabled by localMedia::isCameraEnabled

        // Neither of these starts capture until the session is fully connected:
        // `waitUntilConnected()` does not return while the peer connections are
        // still negotiating, so with an unreachable SFU both effects park here
        // forever and the mic and camera are never opened. See the README
        // section on capture on the glasses.
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

        LaunchedEffect(canEnableVideo) {
            session.waitUntilConnected()
            localMedia.setCameraEnabled(canEnableVideo)
        }

        val cameraTrack = localMedia.cameraTrack?.publication?.track as? LocalVideoTrack

        // What the encoder is doing, every few seconds. See VideoStatsLog.
        LaunchedEffect(cameraTrack) {
            if (cameraTrack != null) VideoStatsLog.run(cameraTrack)
        }

        // Debug only: raw frames to disk when the marker file exists. See FrameDump.
        DisposableEffect(cameraTrack) {
            val dump = if (cameraTrack != null) FrameDump.ifArmed(context) else null
            if (dump != null) cameraTrack!!.addRenderer(dump)
            onDispose { if (dump != null) cameraTrack!!.removeRenderer(dump) }
        }

        val sessionMessages = rememberSessionMessages()
        val speakers by rememberSpeakingParticipants(room)
        val wearerSpeaking = speakers.any { it.identity == room.localParticipant.identity }
        val agentSpeaking = speakers.any { it.identity == agent.agentParticipant?.identity }
        // Wearer stops talking -> agent audio arrives, timed here and sent to
        // the agent's log. See ReplyLatencyProbe.
        ReplyLatencyProbe(room, wearerSpeaking, agentSpeaking)
        // Has an agent ever been here? Lets "it left" read differently from
        // "it has not arrived yet"; see Phase.of.
        var sawAgent by remember { mutableStateOf(false) }
        LaunchedEffect(agent.agentParticipant) {
            if (agent.agentParticipant != null) sawAgent = true
        }
        val engineState by rememberEngineState(room)
        val buildProgress by rememberBuildProgress(agent.agentParticipant)
        val phase = Phase.of(agent, wearerSpeaking, session, engineState, sawAgent, localMedia.isMicrophoneEnabled)

        // Both sides. The agent's lines are its own transcript; the wearer's
        // are what the model heard, published back by the agent under the
        // wearer's identity. See Captions.
        val wearerIdentity = room.localParticipant.identity

        // Everything above the Eyes call is hoisted on purpose: that layout is
        // composed once per eye, so a `remember` inside it would exist twice
        // and the two copies could disagree. See Eyes.
        val cameraAlpha by animateFloatAsState(targetValue = if (isCameraEnabled) 1f else 0f, label = "cameraAlpha")

        Eyes {
            Box(modifier = modifier) {
                // Top to bottom: who has the floor, where the build stands,
                // and whatever is left is caption space, which the newest
                // turn fills from the bottom up (see Captions). The step list
                // keeps to the left two thirds so it clears the preview.
                Column(modifier = Modifier.fillMaxSize()) {
                    PhaseBanner(
                        phase = phase,
                        agent = agent,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                    BuildSteps(
                        progress = buildProgress,
                        modifier = Modifier
                            .fillMaxWidth(0.56f)
                            .padding(top = 12.dp)
                    )
                    Captions(
                        messages = sessionMessages.messages,
                        wearerIdentity = wearerIdentity,
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .padding(top = 12.dp, bottom = 4.dp)
                    )
                }

                // Right column: the reference model, then the self-preview.
                Column(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .fillMaxWidth(0.42f)
                ) {
                    // The finished build, rendered and streamed by the agent
                    // with the current step's brick highlighted; black, so
                    // transparent here, where there is no model.
                    ModelView(
                        agent = agent.agentParticipant,
                        modifier = Modifier
                            .fillMaxWidth()
                            .aspectRatio(4f / 3f)
                    )
                    // Self-preview. Redundant on glasses — the wearer is looking at
                    // the scene directly — but it is the only on-device confirmation
                    // that capture is actually running.
                    Box(
                        modifier = Modifier
                            .align(Alignment.End)
                            .fillMaxWidth(0.45f)
                            .aspectRatio(4f / 3f)
                            .padding(top = 6.dp)
                            .clip(RoundedCornerShape(6.dp))
                            .alpha(cameraAlpha)
                    ) {
                        VideoTrackView(
                            trackReference = localMedia.cameraTrack,
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                }
            }
        }
    }
}
