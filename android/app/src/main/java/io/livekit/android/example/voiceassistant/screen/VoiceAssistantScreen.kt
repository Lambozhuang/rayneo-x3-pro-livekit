package io.livekit.android.example.voiceassistant.screen

import android.widget.Toast
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
import io.livekit.android.compose.state.SessionOptions
import io.livekit.android.compose.state.rememberAgent
import io.livekit.android.compose.state.rememberLocalMedia
import io.livekit.android.compose.state.rememberSession
import io.livekit.android.compose.state.rememberSessionMessages
import io.livekit.android.compose.state.rememberSpeakingParticipants
import io.livekit.android.compose.ui.VideoTrackView
import io.livekit.android.example.voiceassistant.FrameDump
import io.livekit.android.room.track.LocalVideoTrack
import io.livekit.android.example.voiceassistant.rememberCanEnableCamera
import io.livekit.android.example.voiceassistant.rememberCanEnableMic
import io.livekit.android.example.voiceassistant.requirePermissions
import io.livekit.android.example.voiceassistant.ui.Captions
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.PhaseBanner
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
 *   top-left      who has the floor (you / listening / thinking / speaking)
 *   top-right     camera self-preview, the only proof capture is running
 *   bottom        the agent's last two sentences
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
            val result = session.start()

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

        val room = requireRoom()
        val localMedia = rememberLocalMedia()
        val isCameraEnabled by localMedia::isCameraEnabled

        // Neither of these starts capture until the session is fully connected:
        // `waitUntilConnected()` does not return while the peer connections are
        // still negotiating, so with an unreachable SFU both effects park here
        // forever and the mic and camera are never opened. See the README
        // section on capture on the glasses.
        LaunchedEffect(canEnableMic) {
            session.waitUntilConnected()
            localMedia.setMicrophoneEnabled(canEnableMic)
        }

        LaunchedEffect(canEnableVideo) {
            session.waitUntilConnected()
            localMedia.setCameraEnabled(canEnableVideo)
        }

        // Debug only: raw frames to disk when the marker file exists. See FrameDump.
        val cameraTrack = localMedia.cameraTrack?.publication?.track as? LocalVideoTrack
        DisposableEffect(cameraTrack) {
            val dump = if (cameraTrack != null) FrameDump.ifArmed(context) else null
            if (dump != null) cameraTrack!!.addRenderer(dump)
            onDispose { if (dump != null) cameraTrack!!.removeRenderer(dump) }
        }

        val sessionMessages = rememberSessionMessages()
        val agent = rememberAgent()
        val speakers by rememberSpeakingParticipants(room)
        val wearerSpeaking = speakers.any { it.identity == room.localParticipant.identity }
        val phase = Phase.of(agent, wearerSpeaking)

        // Only the agent's lines. Its participant is stable for the session,
        // so comparing identities is enough; chat messages from ourselves do
        // not exist any more, but transcripts of the wearer still arrive here.
        val agentIdentity = agent.agentParticipant?.identity
        val agentMessages = sessionMessages.messages.filter { it.fromParticipant?.identity == agentIdentity }

        // Everything above the Eyes call is hoisted on purpose: that layout is
        // composed once per eye, so a `remember` inside it would exist twice
        // and the two copies could disagree. See Eyes.
        val cameraAlpha by animateFloatAsState(targetValue = if (isCameraEnabled) 1f else 0f, label = "cameraAlpha")

        Eyes {
            Box(modifier = modifier) {
                PhaseBanner(
                    phase = phase,
                    agent = agent,
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(top = 4.dp)
                )

                // Self-preview. Redundant on glasses — the wearer is looking at
                // the scene directly — but it is the only on-device confirmation
                // that capture is actually running.
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .fillMaxWidth(0.3f)
                        .aspectRatio(4f / 3f)
                        .clip(RoundedCornerShape(6.dp))
                        .alpha(cameraAlpha)
                ) {
                    VideoTrackView(
                        trackReference = localMedia.cameraTrack,
                        modifier = Modifier.fillMaxSize()
                    )
                }

                Captions(
                    messages = agentMessages,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .fillMaxWidth()
                        .padding(bottom = 4.dp)
                )
            }
        }
    }
}
