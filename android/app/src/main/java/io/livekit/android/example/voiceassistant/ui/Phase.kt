package io.livekit.android.example.voiceassistant.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
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
import io.livekit.android.compose.ui.audio.VoiceAssistantBarVisualizer

/**
 * Who has the floor. This is the one thing a wearer needs to know at a glance
 * mid-conversation, and the thing the starter's UI never said: its bar
 * visualizer only moved while the agent spoke, so "listening", "thinking" and
 * "the mic is dead" all looked identical.
 *
 * Derived from two sources. The agent publishes its own state (listening /
 * thinking / speaking) as a participant attribute, which the SDK exposes as
 * [Agent.agentState]. Whether the *wearer* is speaking is not something the
 * agent reports; it comes from the SFU's active-speaker updates, which include
 * the local participant. The two are merged with a fixed priority because both
 * can be true at once (the agent keeps "listening" while you talk).
 */
enum class Phase(val label: String, val color: Color) {
    CONNECTING("Connecting", Color(0xFF9E9E9E)),
    WAITING("Waiting", Color(0xFF9E9E9E)),
    LISTENING("Listening", Color(0xFF1FF968)),
    THINKING("Thinking", Color(0xFFFFC107)),
    SPEAKING("Speaking", Color(0xFF66B1FF)),
    FAILED("Agent failed", Color(0xFFFF5252));

    companion object {
        @OptIn(Beta::class)
        fun of(agent: Agent, wearerSpeaking: Boolean): Phase = when {
            agent.agentState == AgentState.FAILED -> FAILED
            !agent.isConnected -> CONNECTING
            agent.agentState == AgentState.SPEAKING -> SPEAKING
            agent.agentState == AgentState.THINKING -> THINKING
            wearerSpeaking -> LISTENING
            agent.agentState == AgentState.LISTENING || agent.agentState == AgentState.IDLE -> WAITING
            else -> CONNECTING
        }
    }
}

/**
 * A coloured dot, a word, and the agent's level meter. Big enough to read
 * without focusing on it: the panels are 640x480 at arm's length, so anything
 * under ~18 sp is a squint.
 */
@OptIn(Beta::class)
@Composable
fun PhaseBanner(phase: Phase, agent: Agent, modifier: Modifier = Modifier) {
    val color by animateColorAsState(phase.color, label = "phaseColor")
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        modifier = modifier
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
}
