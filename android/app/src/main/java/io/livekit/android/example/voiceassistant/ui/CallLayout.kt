package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * One eye of the call: above the band, the build on the left (the current step's picture, the build's title, the
 * steps) and the agent's lines on the right; the band along the bottom says who has the floor and what the model heard
 * the wearer say. VoiceAssistantScreen fills it from the room, MockScreen from fixed data, so the two look the same.
 * The picture is drawn from the bricks the agent published (BuildProgress); until it has published any, or on a path
 * without a build, the square keeps its outline.
 */
@Composable
fun CallLayout(
    progress: BuildProgress,
    phase: Phase,
    agentLines: @Composable (Modifier) -> Unit,
    wearerLine: @Composable (Modifier) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxSize()) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.fillMaxWidth().weight(1f)
        ) {
            Column(modifier = Modifier.width(LEFT_WIDTH).fillMaxHeight()) {
                val square = Modifier.size(DIAGRAM_SIDE)
                val current = progress.current
                if (progress.bricks.isNotEmpty() && current != null) {
                    StepPicture(plate = progress.plate, bricks = progress.bricks, current = current, modifier = square)
                } else {
                    Box(modifier = square.border(1.dp, Color(0xFF333333)))
                }
                BuildTitle(
                    progress = progress,
                    modifier = Modifier.padding(top = 6.dp)
                )
                BuildSteps(
                    progress = progress,
                    modifier = Modifier.weight(1f).padding(top = 10.dp)
                )
            }
            agentLines(Modifier.weight(1f).fillMaxHeight())
        }
        StatusBand(
            phase = phase,
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            wearer = wearerLine,
        )
    }
}

/** Width of the build's column, which holds the longest step name, "Dark grey 2x6, right post", on one line at 18 sp. */
private val LEFT_WIDTH = 272.dp

/** Side of the square kept for the step's picture, out of the 592 px an eye has after its margins. */
private val DIAGRAM_SIDE = 216.dp
