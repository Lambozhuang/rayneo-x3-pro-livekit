package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.room.participant.Participant
import io.livekit.android.util.flow

/**
 * Where the build stands: every step by name, the current one bright.
 *
 * The agent process owns the position (guide.py) and publishes it as its own
 * participant attributes, `rayneo.build.steps` (names, one per line) and
 * `rayneo.build.step` (index of the current step; equal to the count once the
 * build is done). Attributes travel on the signalling channel and are re-sent
 * after a reconnect, so this list is right again as soon as the connection is.
 *
 * @param current index of the step being built, or null when nothing has
 * been published yet; `steps.size` once finished.
 */
data class BuildProgress(val steps: List<String>, val current: Int?) {
    companion object {
        val NONE = BuildProgress(emptyList(), null)

        fun of(attributes: Map<String, String>): BuildProgress {
            val steps = attributes[KEY_STEPS]?.split('\n')?.filter { it.isNotBlank() } ?: return NONE
            return BuildProgress(steps, attributes[KEY_STEP]?.toIntOrNull())
        }

        private const val KEY_STEPS = "rayneo.build.steps"
        private const val KEY_STEP = "rayneo.build.step"
    }
}

@Composable
fun rememberBuildProgress(agent: Participant?): State<BuildProgress> {
    if (agent == null) return remember { mutableStateOf(BuildProgress.NONE) }
    val attributes by agent::attributes.flow.collectAsState()
    return remember(attributes) { mutableStateOf(BuildProgress.of(attributes)) }
}

/**
 * A numbered list. Done steps dim, the current one white and bold, the rest
 * grey; one line each, the name is written to fit. Nothing when the agent has
 * not published a build, so a session without a guide looks as before.
 */
@Composable
fun BuildSteps(progress: BuildProgress, modifier: Modifier = Modifier) {
    if (progress.steps.isEmpty()) return
    val current = progress.current ?: -1
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        progress.steps.forEachIndexed { i, name ->
            val color = when {
                i < current -> Color(0xFF5E5E5E)
                i == current -> Color(0xFFEEEEEE)
                else -> Color(0xFF9E9E9E)
            }
            val weight = if (i == current) FontWeight.Bold else FontWeight.Normal
            Row {
                Text(
                    text = if (i < current) "✓" else "${i + 1}.",
                    color = color,
                    fontSize = 18.sp,
                    lineHeight = 24.sp,
                    fontWeight = weight,
                    modifier = Modifier.width(26.dp),
                )
                Text(
                    text = name,
                    color = color,
                    fontSize = 18.sp,
                    lineHeight = 24.sp,
                    fontWeight = weight,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}
