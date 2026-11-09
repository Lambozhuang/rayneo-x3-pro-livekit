package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
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
 * The line above the dots when the phase has one, saying what to do ("Connection lost, trying again"); nothing
 * otherwise. Big enough to catch without focusing on it: the panels are 640x480 at arm's length, so anything under
 * ~18 sp is a squint.
 */
@Composable
fun PhaseHint(phase: Phase, modifier: Modifier = Modifier) {
    val hint = phase.hint ?: return
    Text(
        text = hint,
        color = Color(0xFFBDBDBD),
        fontSize = 20.sp,
        lineHeight = 26.sp,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        textAlign = TextAlign.Center,
        modifier = modifier.padding(bottom = 4.dp),
    )
}

/**
 * The agent's line for the wearer, what to do now (`rayneo.hint`, BuildProgress.hint; the games of the user study use
 * it, gpt/place.py), across the eye right under the band: 22 sp, up to three lines, since the longest hint of game B
 * runs to 107 characters and one line at this size holds about 50. The wearer has just looked at the picture in the
 * band's square, so the line sits where their eyes go next. It was above the dots at 20 sp in grey until 2026-11-08,
 * when the first home run of game B showed it was missed there. Nothing when the agent has published no hint, and
 * nothing while the phase has words of its own (CallLayout), since those sit just below and matter more.
 */
@Composable
fun AgentHint(text: String, modifier: Modifier = Modifier) {
    if (text.isEmpty()) return
    Text(
        text = text,
        color = HINT_GREEN,
        fontSize = 22.sp,
        lineHeight = 28.sp,
        fontWeight = FontWeight.Medium,
        maxLines = 3,
        overflow = TextOverflow.Ellipsis,
        textAlign = TextAlign.Center,
        modifier = modifier.border(2.dp, HINT_GREEN, RoundedCornerShape(8.dp)).padding(horizontal = 14.dp, vertical = 6.dp),
    )
}

/** The hint's green, text and frame: a different green from the dots' "yes" flash, so the two do not read as one. */
private val HINT_GREEN = Color(0xFF66E07A)
