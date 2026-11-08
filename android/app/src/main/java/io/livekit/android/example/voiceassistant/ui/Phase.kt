package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.annotations.Beta
import io.livekit.android.compose.state.Agent
import io.livekit.android.compose.state.AgentState
import io.livekit.android.compose.state.Session
import io.livekit.android.room.ConnectionState

/**
 * What the agent is doing this instant, as the dots show it (AgentDots). Who has the floor is the one thing a wearer
 * needs mid-conversation, and the starter's UI never said it: its bar visualizer only moved while the agent spoke, so
 * "listening", "thinking" and "the mic is dead" all looked identical.
 *
 * Derived from four sources, merged with a fixed priority because several can be true at once. The sound at the
 * glasses ([Voices]): the agent's voice out of the decoder, the wearer's voice at the microphone, and the wait between
 * the wearer finishing and the reply arriving; these are local and immediate. The agent's word on what it does
 * ([Act]): the brain judging a placement it was called to. The agent's own state attribute (listening / thinking /
 * speaking, [Agent.agentState]) merged with what the SDK knows about the agent's arrival: no participant yet, one that
 * has been and gone, none within the timeout; on the GPT-Live path that state never says "thinking" (the speech
 * model keeps listening while the brain looks), and "speaking" is not used, since the sound itself is here, so the
 * attribute's part is the agent's presence. And the room connection, which can be mid-reconnect, on a network-quality
 * test bed the most interesting state of all; that one is read from the SDK's engine, because the public room state
 * sits on "connected" through a soft reconnect (see [rememberEngineState]).
 *
 * "Ready" means the mic is live and the agent is listening to it; the mic is only switched on once the agent is
 * there (see VoiceAssistantScreen), so before "Ready" nothing is heard and the wearer should wait for it. Only the
 * phases with a [hint] put words on the screen; the others are told by the dots alone.
 */
enum class Phase(val label: String, val hint: String? = null) {
    CONNECTING("Connecting"),
    READY("Ready"),
    LISTENING("Listening"),
    THINKING("Thinking"),
    SPEAKING("Speaking"),
    LOOKING("Looking"),
    RECONNECTING("Reconnecting", "Connection lost, trying again"),
    LOST("Agent left", "The assistant has left, please wait"),
    NO_AGENT("No agent", "No assistant, please tell the experimenter");

    companion object {
        /**
         * @param voices who is sounding at the glasses, and whether a reply is awaited; see [rememberVoices].
         * @param looking the agent says it is judging a placement; see [rememberAct].
         * @param sawAgent whether an agent participant has ever been in this room. The SDK's own "disconnected
         * mid-session" only counts an agent that reached "listening"; one that joined and died while starting up
         * (a bad model key, say) would otherwise read as "Connecting" for the whole 20 s agent timeout.
         * @param engine the SDK engine's own connection state, see [rememberEngineState]. [Session.isReconnecting]
         * only covers a full reconnect; the soft one a Wi-Fi drop triggers first is RESUMING here and invisible there.
         */
        @OptIn(Beta::class)
        fun of(
            agent: Agent,
            voices: Voices,
            looking: Boolean,
            session: Session,
            engine: ConnectionState,
            sawAgent: Boolean,
            micOn: Boolean,
        ): Phase = when {
            session.isReconnecting || engine == ConnectionState.RESUMING || engine == ConnectionState.RECONNECTING -> RECONNECTING
            agent.agentState == AgentState.FAILED -> NO_AGENT
            session.isConnected && sawAgent && agent.agentParticipant == null -> LOST
            voices.agentSounding -> SPEAKING
            agent.isConnected && micOn && voices.wearerSounding -> LISTENING
            agent.isConnected && micOn && (voices.waiting || agent.agentState == AgentState.THINKING) -> THINKING
            agent.isConnected && micOn && looking -> LOOKING
            agent.isConnected && micOn -> READY
            else -> CONNECTING
        }
    }
}

/**
 * The line above the dots: the phase's words when it has any ("Connection lost, trying again"), else the agent's
 * [hint] for the wearer (`rayneo.hint`, BuildProgress) when there is one, else nothing. Big enough to catch without
 * focusing on it: the panels are 640x480 at arm's length, so anything under ~18 sp is a squint.
 */
@Composable
fun PhaseHint(phase: Phase, hint: String = "", modifier: Modifier = Modifier) {
    val text = phase.hint ?: hint.takeIf { it.isNotEmpty() } ?: return
    Text(
        text = text,
        color = Color(0xFFBDBDBD),
        fontSize = 20.sp,
        lineHeight = 26.sp,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        textAlign = TextAlign.Center,
        modifier = modifier.padding(bottom = 4.dp),
    )
}
