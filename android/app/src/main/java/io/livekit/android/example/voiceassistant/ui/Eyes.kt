package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Draws [content] once for each eye.
 *
 * The X3 Pro has two 640x480 panels but Android sees a single logical display,
 * 1280x480 at density 160 — so 1 dp is 1 px, and the left half of the surface
 * goes to the left eye while the right half goes to the right. An ordinary
 * phone layout therefore does not appear twice; it gets *cut in half*, and
 * anything centred horizontally lands on the seam between the two eyes.
 *
 * The fix is to draw everything twice, which is what RayNeo's own SDK does
 * through `BaseMirrorActivity`, `MirrorContainerView` and `BindingPair`. Those
 * mirror View trees, and a Compose hierarchy is a single `AndroidComposeView`,
 * so they have nothing to work with here. Composing the same function twice
 * gets the same result in a few lines and keeps us off RayNeo's private Maven.
 * https://rayneo-en.gitbook.io/rayneo-devdoc/x-series/android-sdk
 *
 * **Hoist state above this call.** [content] is composed twice, so a `remember`
 * inside it exists twice and the two copies drift apart — type into a mirrored
 * text field and only the eye you touched updates. State that both eyes must
 * agree on belongs to the caller. (`BindingPair.updateView` exists for exactly
 * this reason in the View world; hoisting is the Compose answer to it.)
 *
 * The inset is RayNeo's: they ask for a black margin of at least 16-30 px
 * around the edges, because the outer edges of each panel distort and the
 * parallax there is uncomfortable to fuse. Black is not a cosmetic choice
 * either — see the theme.
 *
 * One thing to know when checking work with `adb shell screencap`: the capture
 * is not the surface we laid out. Measured on device, each half comes back
 * scaled to about 0.95 and nudged toward the seam, so a 592 px-wide button
 * lands as 562 px sitting ~31 px further in than the layout put it. It happens
 * to both eyes equally, so it is the compositor's own per-eye correction rather
 * than anything to fix here — but it does mean the usable area is a little
 * smaller than the numbers above, and that `uiautomator dump` (which reports
 * pre-composition bounds) is the honest way to verify a layout.
 */
@Composable
fun Eyes(content: @Composable () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // weight rather than a hardcoded 640.dp, so this still splits evenly if
        // a future device reports a different width.
        repeat(2) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .padding(EYE_MARGIN)
            ) {
                content()
            }
        }
    }
}

/** Middle of RayNeo's recommended 16-30 px safe-area margin. */
private val EYE_MARGIN = 24.dp
