package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
 * Where the build stands: every step by name, the current one bright, and the bricks to draw its picture from.
 *
 * The agent process owns the position (guide.py) and publishes it as its own
 * participant attributes, `rayneo.build.title` (the build's name),
 * `rayneo.build.steps` (step names, one per line), `rayneo.build.bricks` (one line per step,
 * `#rrggbb col0 row0 col1 row1`, with `round` appended for a round plate), `rayneo.build.plate`
 * (the plate's side in studs), `rayneo.build.step`
 * (index of the current step; equal to the count once the build is done) and `rayneo.build.picture` (the number of the
 * step whose picture the glasses show, as the wearer counts them; 0 for none). Attributes travel on the signalling
 * channel and are re-sent after a reconnect, so this list is right again as soon as the connection is.
 *
 * @param current index of the step being built, or null when nothing has
 * been published yet; `steps.size` once finished.
 * @param bricks one per step, in step order; empty when the agent published none, and then there is no picture.
 * @param picture the step whose picture is shown, 1 to `steps.size`, or null when the square shows the camera; the
 * agent sets it when the wearer asked for a picture (brain.py `show`) and clears it when the progress moves.
 */
data class BuildProgress(
    val title: String,
    val steps: List<String>,
    val current: Int?,
    val plate: Int = 16,
    val bricks: List<Brick> = emptyList(),
    val picture: Int? = null,
) {
    companion object {
        val NONE = BuildProgress("", emptyList(), null)

        fun of(attributes: Map<String, String>): BuildProgress {
            val steps = attributes[KEY_STEPS]?.split('\n')?.filter { it.isNotBlank() } ?: return NONE
            val bricks = attributes[KEY_BRICKS]?.split('\n')?.filter { it.isNotBlank() }?.map { brick(it) } ?: emptyList()
            return BuildProgress(
                title = attributes[KEY_TITLE] ?: "",
                steps = steps,
                current = attributes[KEY_STEP]?.toIntOrNull(),
                plate = attributes[KEY_PLATE]?.toIntOrNull() ?: 16,
                bricks = bricks,
                picture = attributes[KEY_PICTURE]?.toIntOrNull()?.takeIf { it in 1..bricks.size },
            )
        }

        /** One line of `rayneo.build.bricks`, as guide.py writes it. */
        private fun brick(line: String): Brick {
            val f = line.trim().split(' ')
            return Brick(
                color = Color(0xFF000000L or f[0].removePrefix("#").toLong(16)),
                col0 = f[1].toInt(), row0 = f[2].toInt(), col1 = f[3].toInt(), row1 = f[4].toInt(),
                round = f.getOrNull(5) == "round",
            )
        }

        private const val KEY_TITLE = "rayneo.build.title"
        private const val KEY_STEPS = "rayneo.build.steps"
        private const val KEY_BRICKS = "rayneo.build.bricks"
        private const val KEY_PLATE = "rayneo.build.plate"
        private const val KEY_STEP = "rayneo.build.step"
        private const val KEY_PICTURE = "rayneo.build.picture"
    }
}

@Composable
fun rememberBuildProgress(agent: Participant?): State<BuildProgress> {
    if (agent == null) return remember { mutableStateOf(BuildProgress.NONE) }
    val attributes by agent::attributes.flow.collectAsState()
    return remember(attributes) { mutableStateOf(BuildProgress.of(attributes)) }
}

/** The build's title on one line, white; nothing when no build has been published. */
@Composable
fun BuildTitle(progress: BuildProgress, modifier: Modifier = Modifier) {
    if (progress.title.isEmpty()) return
    Text(
        text = progress.title,
        color = Color(0xFFEEEEEE),
        fontSize = 20.sp,
        lineHeight = 26.sp,
        fontWeight = FontWeight.Medium,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = modifier,
    )
}

/**
 * A numbered list. Done steps dim, the current one white and bold, the rest
 * grey; a name takes one line and is cut short if it does not fit. Nothing
 * when the agent has not published a build, so a session without a guide
 * looks as before.
 *
 * Longer than the space, the list scrolls by itself so that the current step
 * is the second line, one done step above it for context. The scroll position
 * is per eye (Eyes composes this twice), which is fine: it follows `current`
 * only, so both copies land in the same place. No user scrolling: no pointer.
 */
@Composable
fun BuildSteps(progress: BuildProgress, modifier: Modifier = Modifier) {
    if (progress.steps.isEmpty()) return
    val current = progress.current ?: -1
    val list = rememberLazyListState()
    LaunchedEffect(current) {
        if (current >= 0) list.animateScrollToItem((current - 1).coerceIn(0, progress.steps.lastIndex))
    }
    LazyColumn(
        state = list,
        userScrollEnabled = false,
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        itemsIndexed(progress.steps) { i, name ->
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
