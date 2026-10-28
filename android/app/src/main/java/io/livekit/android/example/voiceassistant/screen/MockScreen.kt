package io.livekit.android.example.voiceassistant.screen

import androidx.compose.runtime.Composable
import io.livekit.android.example.voiceassistant.ui.AgentLinesView
import io.livekit.android.example.voiceassistant.ui.BuildProgress
import io.livekit.android.example.voiceassistant.ui.CallLayout
import io.livekit.android.example.voiceassistant.ui.CameraPreview
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.Picture
import io.livekit.android.example.voiceassistant.ui.WearerLineView
import kotlinx.serialization.Serializable

@Serializable
object MockRoute

/**
 * The call screen with nothing behind it, for looking at the layout on the glasses without a server: the ladder
 * (backend/agent/guides/ladder/task.toml) at its third step, the yellow top rung, with a conversation about it as
 * GPT-Live would have transcribed it, the agent speaking. The square keeps its outline: there is no camera to preview
 * and no agent to send a picture. `glasses.ps1 -Mock` opens the app on it; a double tap leaves.
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
            "Lime 1x4, bottom rung",
        ),
        current = 2,
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
            picture = Picture.None,
            preview = { m -> CameraPreview(track = null, modifier = m) },
            agentLines = { m -> AgentLinesView(agentLines, m) },
            wearerLine = { m -> WearerLineView(wearerLine, m) },
        )
    }
}
