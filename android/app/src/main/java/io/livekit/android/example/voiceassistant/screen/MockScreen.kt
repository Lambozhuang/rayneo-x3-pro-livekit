package io.livekit.android.example.voiceassistant.screen

import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.res.imageResource
import io.livekit.android.example.voiceassistant.R
import io.livekit.android.example.voiceassistant.ui.BuildProgress
import io.livekit.android.example.voiceassistant.ui.CallLayout
import io.livekit.android.example.voiceassistant.ui.CameraPreview
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.Flash
import io.livekit.android.example.voiceassistant.ui.Phase
import io.livekit.android.example.voiceassistant.ui.Picture
import io.livekit.android.example.voiceassistant.ui.rememberSeconds
import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.sin

@Serializable
object MockRoute

/**
 * The call screen with nothing behind it, for looking at the layout and the dots on the glasses without a server. It
 * plays one scene of a build on a loop, SCENE_S seconds long: the gate (backend/agent/guides/gate/task.toml) at step 2,
 * the wearer asks and the agent answers, a wrong brick is picked up and flashed red, the right one green, the brick
 * goes down and the brain looks, the step moves to 3 and the picture of step 3 (the gate's step-3.png, copied into the
 * app's resources for this screen only) comes and goes, then the connection drops and comes back. The voices are a
 * made-up loudness curve. The camera's square stays empty, there being no camera. `glasses.ps1 -Mock` opens the app on
 * it; a double tap leaves.
 */
@Composable
fun MockScreen() {
    // Hoisted above Eyes, which composes the layout twice: both eyes read the same state.
    val stepPicture = ImageBitmap.imageResource(R.drawable.mock_step_3)
    val seconds = rememberSeconds()
    val scene = remember { Scene() }

    // The scene's time is read while the dots are drawn, through the lambdas below; the phase, step and picture are
    // derived from it here, so the layout recomposes only when one of them changes.
    val phase by remember { derivedStateOf { scene.phase(seconds.value % SCENE_S) } }
    val current by remember { derivedStateOf { if (seconds.value % SCENE_S >= STEP_AT) 2 else 1 } }
    val pictureUp by remember { derivedStateOf { (seconds.value % SCENE_S).let { it >= PICTURE_FROM && it < PICTURE_TO } } }
    val picture = if (pictureUp) Picture.Shown("step-3.png", stepPicture) else Picture.None

    Eyes {
        CallLayout(
            progress = BuildProgress(
                title = "LEGO gate on a baseplate",
                steps = listOf(
                    "Blue 2x6, left post",
                    "Dark grey 2x6, right post",
                    "Dark red 2x6, top",
                    "White 1x6, ground left",
                    "Tan 1x6, ground right",
                ),
                current = current,
            ),
            phase = phase,
            picture = picture,
            preview = { m -> CameraPreview(track = null, modifier = m) },
            seconds = { seconds.value },
            level = { scene.level(seconds.value % SCENE_S) },
            flash = { scene.flash(seconds.value % SCENE_S) },
            remaining = "2:31",
        )
    }
}

/** The scene: what the agent is doing at each second, and when the two verdicts flash. */
private class Scene {
    private val segments = listOf(
        0f to Phase.READY,        // step 2 is on, nothing is happening
        2f to Phase.LISTENING,    // "where does the grey one go?"
        4.5f to Phase.THINKING,   // the reply is on its way
        6.3f to Phase.SPEAKING,   // "the dark grey two by six, right of the blue one, ..."
        10f to Phase.READY,       // a brick is picked up; at 11.5 the agent says it is not the step's
        12.2f to Phase.SPEAKING,  // "that's not the right brick; ..."
        14f to Phase.READY,       // another brick; at 15.5 the agent says it is the step's
        16.2f to Phase.SPEAKING,  // "that's the right brick; it goes ..."
        18.5f to Phase.READY,     // it goes on the plate
        20f to Phase.LOOKING,     // the brain judges the plate
        23f to Phase.SPEAKING,    // the step moves to 3: "step 2 is done; ..."
        26f to Phase.READY,
        27.5f to Phase.LISTENING, // "show me the picture"
        29f to Phase.THINKING,
        30.5f to Phase.SPEAKING,  // the picture arrives at 30.8
        33f to Phase.READY,       // the picture stays
        36f to Phase.READY,       // the picture is gone
        38f to Phase.RECONNECTING,
        41f to Phase.READY,
    )
    private val flashes = listOf(11.5f to false, 15.5f to true)

    fun phase(t: Float): Phase = segments.last { it.first <= t }.second

    /** A made-up loudness curve for the stretches with a voice, from the stretch's start. */
    fun level(t: Float): Float {
        val start = segments.last { it.first <= t }
        if (start.second != Phase.LISTENING && start.second != Phase.SPEAKING) return 0f
        val tIn = t - start.first
        val attack = (tIn / 0.15f).coerceAtMost(1f)
        return attack * (0.3f + 0.7f * abs(sin(tIn * 9.3f) * sin(tIn * 2.1f + 0.4f)) * (0.65f + 0.35f * sin(tIn * 0.7f))).coerceAtMost(1f)
    }

    fun flash(t: Float): Flash? {
        val f = flashes.firstOrNull { t - it.first in 0f..1.2f } ?: return null
        return Flash(yes = f.second, at = SystemClock.uptimeMillis() - ((t - f.first) * 1000).toLong())
    }
}

private const val SCENE_S = 43f
private const val STEP_AT = 23f
private const val PICTURE_FROM = 30.8f
private const val PICTURE_TO = 36f
