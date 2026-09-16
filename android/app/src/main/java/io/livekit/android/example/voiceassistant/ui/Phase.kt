package io.livekit.android.example.voiceassistant.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.annotations.Beta
import io.livekit.android.compose.state.Agent
import io.livekit.android.compose.state.AgentState
import io.livekit.android.compose.state.Session
import io.livekit.android.compose.ui.audio.VoiceAssistantBarVisualizer

/**
 * Who has the floor. This is the one thing a wearer needs to know at a glance
 * mid-conversation, and the thing the starter's UI never said: its bar
 * visualizer only moved while the agent spoke, so "listening", "thinking" and
 * "the mic is dead" all looked identical.
 *
 * Derived from three sources. The agent publishes its own state (listening /
 * thinking / speaking) as a participant attribute, which the SDK exposes as
 * [Agent.agentState], merged with what the SDK knows about the agent's
 * arrival: no participant yet, one that has been and gone, none within the
 * timeout. Whether the *wearer* is speaking is not something the agent
 * reports; it comes from the SFU's active-speaker updates, which include the
 * local participant. And the room connection itself can be mid-reconnect,
 * which on a network-quality test bed is the most interesting state of all.
 * The sources are merged with a fixed priority because several can be true
 * at once (the agent keeps "listening" while you talk).
 *
 * "Ready" starts before the agent has joined: the mic is recorded from the
 * moment the room is joined and the recording is handed to the agent when it
 * subscribes (see the ViewModel), so the wearer may speak as soon as they see
 * it and nothing is lost.
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
         */
        @OptIn(Beta::class)
        fun of(agent: Agent, wearerSpeaking: Boolean, session: Session, sawAgent: Boolean): Phase = when {
            session.isReconnecting -> RECONNECTING
            agent.agentState == AgentState.FAILED -> NO_AGENT
            session.isConnected && sawAgent && agent.agentParticipant == null -> LOST
            agent.agentState == AgentState.SPEAKING -> SPEAKING
            agent.agentState == AgentState.THINKING -> THINKING
            agent.canListen && wearerSpeaking -> LISTENING
            agent.canListen -> READY
            else -> CONNECTING
        }
    }
}

/**
 * A coloured dot, a word, and the agent's level meter; below them, when the
 * phase has one, a line saying what to do about it. Big enough to read without
 * focusing on it: the panels are 640x480 at arm's length, so anything under
 * ~18 sp is a squint.
 */
@OptIn(Beta::class)
@Composable
fun PhaseBanner(phase: Phase, agent: Agent, modifier: Modifier = Modifier) {
    val color by animateColorAsState(phase.color, label = "phaseColor")
    Column(modifier = modifier) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(14.dp)
                    .background(color, CircleShape)
            )
            Text(
                text = phase.label,
                color = color,
                fontSize = 22.sp,
                fontWeight = FontWeight.Medium,
            )
            Spacer(Modifier.width(4.dp))
            VoiceAssistantBarVisualizer(
                agentState = agent.agentState,
                audioTrackRef = agent.audioTrack,
                barCount = 5,
                minHeight = 0.2f,
                barWidth = 4.dp,
                brush = SolidColor(color),
                modifier = Modifier
                    .width(44.dp)
                    .height(22.dp)
            )
        }
        phase.hint?.let {
            Text(
                text = it,
                color = Color(0xFFBDBDBD),
                fontSize = 18.sp,
                modifier = Modifier.padding(top = 6.dp)
            )
        }
    }
}
