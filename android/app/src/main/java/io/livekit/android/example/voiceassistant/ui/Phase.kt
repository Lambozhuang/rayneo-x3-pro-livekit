package io.livekit.android.example.voiceassistant.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.annotations.Beta
import io.livekit.android.compose.state.Agent
import io.livekit.android.compose.state.AgentState
import io.livekit.android.compose.state.Session
import io.livekit.android.room.ConnectionState
import io.livekit.android.room.participant.Participant
import io.livekit.android.util.flow

/**
 * Who has the floor. This is the one thing a wearer needs to know at a glance
 * mid-conversation, and the thing the starter's UI never said: its bar
 * visualizer only moved while the agent spoke, so "listening", "thinking" and
 * "the mic is dead" all looked identical.
 *
 * Derived from four sources. The agent publishes its own state (listening /
 * thinking / speaking) as a participant attribute, which the SDK exposes as
 * [Agent.agentState], merged with what the SDK knows about the agent's
 * arrival: no participant yet, one that has been and gone, none within the
 * timeout. On the GPT-Live path that state never says "thinking": the speech
 * model keeps listening while the hand-over to the vision model runs, so the
 * agent sets its own attribute, `rayneo.brain.looking`, for as long as a
 * look is in progress ([rememberBrainLooking]). Whether the *wearer* is speaking is not something the agent
 * reports; it comes from the SFU's active-speaker updates, which include the
 * local participant. And the room connection itself can be mid-reconnect,
 * which on a network-quality test bed is the most interesting state of all;
 * that one is read from the SDK's engine, because the public room state
 * sits on "connected" through a soft reconnect (see [rememberEngineState]).
 * The sources are merged with a fixed priority because several can be true
 * at once (the agent keeps "listening" while you talk).
 *
 * "Ready" means the mic is live and the agent is listening to it; the mic is
 * only switched on once the agent is there (see VoiceAssistantScreen), so
 * before "Ready" nothing is heard and the wearer should wait for it.
 */
enum class Phase(val label: String, val color: Color, val hint: String? = null) {
    CONNECTING("Connecting", Color(0xFF9E9E9E)),
    READY("Ready", Color(0xFF7ED9A0)),
    LISTENING("Listening", Color(0xFF1FF968)),
    THINKING("Thinking", Color(0xFFFFC107)),
    SPEAKING("Speaking", Color(0xFF66B1FF)),
    RECONNECTING("Reconnecting", Color(0xFFFFC107), "Connection lost, trying again"),
    LOST("Agent left", Color(0xFFFF5252), "Double tap to end the call"),
    NO_AGENT("No agent", Color(0xFFFF5252), "Double tap to end the call");

    companion object {
        /**
         * @param sawAgent whether an agent participant has ever been in this
         * room. The SDK's own "disconnected mid-session" only counts an agent
         * that reached "listening"; one that joined and died while starting up
         * (a bad model key, say) would otherwise read as "Connecting" for the
         * whole 20 s agent timeout.
         * @param engine the SDK engine's own connection state, see
         * [rememberEngineState]. [Session.isReconnecting] only covers a full
         * reconnect; the soft one a Wi-Fi drop triggers first is RESUMING here
         * and invisible there.
         */
        @OptIn(Beta::class)
        fun of(
            agent: Agent,
            wearerSpeaking: Boolean,
            session: Session,
            engine: ConnectionState,
            sawAgent: Boolean,
            micOn: Boolean,
            brainLooking: Boolean,
        ): Phase = when {
            session.isReconnecting || engine == ConnectionState.RESUMING || engine == ConnectionState.RECONNECTING -> RECONNECTING
            agent.agentState == AgentState.FAILED -> NO_AGENT
            session.isConnected && sawAgent && agent.agentParticipant == null -> LOST
            agent.agentState == AgentState.SPEAKING -> SPEAKING
            agent.agentState == AgentState.THINKING || brainLooking -> THINKING
            agent.isConnected && micOn && wearerSpeaking -> LISTENING
            agent.isConnected && micOn -> READY
            else -> CONNECTING
        }
    }
}

/**
 * The band along the bottom of the eye: a coloured dot and a word for who
 * has the floor, and after them what the model heard the wearer say
 * ([wearer]), or, when the phase has one, a line saying what to do about it
 * instead. Who has the floor and what the agent heard are read together,
 * so they share the line and the size; the word keeps a fixed width so the
 * wearer's words do not jump when it changes. Big enough to catch without
 * focusing on it: the panels are 640x480 at arm's length, so anything under
 * ~18 sp is a squint.
 */
@Composable
fun StatusBand(phase: Phase, modifier: Modifier = Modifier, wearer: @Composable (Modifier) -> Unit) {
    val color by animateColorAsState(phase.color, label = "phaseColor")
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        modifier = modifier
            .drawBehind { drawLine(Color(0xFF333333), Offset(0f, 0f), Offset(size.width, 0f), 1.dp.toPx()) }
            .padding(top = 8.dp),
    ) {
        Box(
            modifier = Modifier
                .size(16.dp)
                .background(color, CircleShape)
        )
        Text(
            text = phase.label,
            color = color,
            fontSize = 22.sp,
            lineHeight = 30.sp,
            fontWeight = FontWeight.Bold,
            maxLines = 1,
            modifier = Modifier.width(LABEL_WIDTH),
        )
        val rest = Modifier.weight(1f)
        phase.hint?.let {
            Text(
                text = it,
                color = Color(0xFFBDBDBD),
                fontSize = 22.sp,
                lineHeight = 30.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = rest,
            )
        } ?: wearer(rest)
    }
}

/** Width that holds the longest phase word, "Reconnecting", at 22 sp bold. */
private val LABEL_WIDTH = 150.dp

/** Whether the agent's brain is on a look right now: its `rayneo.brain.looking` attribute is "1" (brain.py). */
@Composable
fun rememberBrainLooking(agent: Participant?): State<Boolean> {
    if (agent == null) return remember { mutableStateOf(false) }
    val attributes by agent::attributes.flow.collectAsState()
    return remember(attributes) { mutableStateOf(attributes["rayneo.brain.looking"] == "1") }
}
