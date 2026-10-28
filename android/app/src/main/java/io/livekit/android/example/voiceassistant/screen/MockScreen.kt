package io.livekit.android.example.voiceassistant.screen

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import io.livekit.android.example.voiceassistant.ui.AgentLinesView
import io.livekit.android.example.voiceassistant.ui.Brick
import io.livekit.android.example.voiceassistant.ui.BuildProgress
import io.livekit.android.example.voiceassistant.ui.CallLayout
import io.livekit.android.example.voiceassistant.ui.CameraPreview
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.WearerLineView
import kotlinx.serialization.Serializable

@Serializable
object MockRoute

/**
 * The call screen with nothing behind it, for looking at the layout on the glasses without a server: the ladder
 * (backend/agent/guides/ladder/task.toml) at its third step, the yellow top rung, with a conversation about it as
 * GPT-Live would have transcribed it, the agent speaking, and the picture of the step on the glasses as if the wearer
 * had asked for it (there is no camera to preview here). `glasses.ps1 -Mock` opens the app on it; a double tap leaves.
 */
@Composable
fun MockScreen() {
    val progress = BuildProgress(
        title = "LEGO ladder on a baseplate",
        steps = listOf(
            "Tan 1x6, left side",
            "White 1x6, right side",
            "Yellow 1x4, top rung",
            "Blue 1x4, middle rung",
            "Aqua 1x4, bottom rung",
        ),
        current = 2,
        picture = 3,
        plate = 16,
        bricks = listOf(
            Brick(Color(0xFFD9C89B), 5, 5, 5, 10),
            Brick(Color(0xFFF2F2F2), 10, 5, 10, 10),
            Brick(Color(0xFFF2C20A), 6, 5, 9, 5),
            Brick(Color(0xFF1E5BC6), 6, 7, 9, 7),
            Brick(Color(0xFFA8E0DC), 6, 9, 9, 9),
        ),
    )
    val agentLines = listOf(
        "Both rails are in place. Next, find the yellow 1x4 brick.",
        "Lay it flat between the tan and the white brick, in their top row, so it touches both.",
        "The top row, yes, level with the top ends of the two rails. Press it down until it clicks on both.",
    )
    val wearerLine = "Does it go in the top row or the second row?"

    Eyes {
        CallLayout(
            progress = progress,
            phase = Phase.SPEAKING,
            preview = { m -> CameraPreview(track = null, modifier = m) },
            agentLines = { m -> AgentLinesView(agentLines, m) },
            wearerLine = { m -> WearerLineView(wearerLine, m) },
        )
    }
}
