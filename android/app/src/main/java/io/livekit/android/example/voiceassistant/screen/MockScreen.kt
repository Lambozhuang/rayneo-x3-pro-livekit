package io.livekit.android.example.voiceassistant.screen

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.res.imageResource
import io.livekit.android.example.voiceassistant.R
import io.livekit.android.example.voiceassistant.ui.BuildProgress
import io.livekit.android.example.voiceassistant.ui.CallLayout
import io.livekit.android.example.voiceassistant.ui.CameraPreview
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.Picture
import kotlinx.coroutines.delay
import kotlinx.serialization.Serializable

@Serializable
object MockRoute

/**
 * The call screen with nothing behind it, for looking at the layout on the glasses without a server: the gate
 * (backend/agent/guides/gate/task.toml), the task with the longest step names, at its third step, the dark red top, the
 * agent speaking. The camera's square stays empty, there being no camera. The picture of step 3 as the agent would have sent it (the gate's step-3.png, copied into the
 * app's resources for this screen only) comes and goes every few seconds, so both states can be looked at.
 * `glasses.ps1 -Mock` opens the app on it; a double tap leaves.
 */
@Composable
fun MockScreen() {
    val progress = BuildProgress(
        title = "LEGO gate on a baseplate",
        steps = listOf(
            "Blue 2x6, left post",
            "Dark grey 2x6, right post",
            "Dark red 2x6, top",
            "White 1x6, ground left",
            "Tan 1x6, ground right",
        ),
        current = 2,
    )
    // Hoisted above Eyes, which composes the layout twice: both eyes read the same state.
    val stepPicture = ImageBitmap.imageResource(R.drawable.mock_step_3)
    var showPicture by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(6_000)
            showPicture = !showPicture
        }
    }

    Eyes {
        CallLayout(
            progress = progress,
            phase = Phase.SPEAKING,
            picture = if (showPicture) Picture.Shown("step-3.png", stepPicture) else Picture.None,
            preview = { m -> CameraPreview(track = null, modifier = m) },
            remaining = "2:31",
        )
    }
}
