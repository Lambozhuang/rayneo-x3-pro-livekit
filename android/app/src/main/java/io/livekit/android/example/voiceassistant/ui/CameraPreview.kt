package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.layout.layout
import androidx.compose.ui.unit.Constraints
import io.livekit.android.compose.ui.RendererType
import io.livekit.android.compose.ui.ScaleType
import io.livekit.android.compose.ui.VideoTrackView
import io.livekit.android.room.track.LocalVideoTrack

/**
 * What the camera sees, cut as the brain sees it: the bottom square of the portrait frame, the table in front of the
 * wearer (frames.py `bottom_square`). The whole frame is drawn at the square's width, 16:9 tall, with its bottom edge
 * on the square's bottom edge and the rest clipped, so the wall and the far desk in the upper part fall outside. The
 * renderer is a TextureView: Compose cannot clip a SurfaceView. Eyes composes this twice, so two renderers draw the
 * same track; each binds to it on its own. Until the camera track exists the square stays empty inside the frame
 * CallLayout draws around it.
 *
 * The placing is done in a layout modifier, not with `requiredSize` and an alignment: a child that reports a size
 * larger than its constraints is coerced to them and centred by Compose whatever alignment it was given, which
 * showed the middle square of the frame on the glasses on 2026-10-28. Here the node reports the square's size and
 * places the taller renderer inside it itself.
 *
 * The display is additive, so the camera image is a patch of light in the eye beside the real scene; whether it
 * needs dimming is judged on the glasses, not here.
 */
@Composable
fun CameraPreview(track: LocalVideoTrack?, modifier: Modifier = Modifier) {
    if (track == null) {
        Box(modifier = modifier)
        return
    }
    Box(modifier = modifier.clipToBounds()) {
        VideoTrackView(
            videoTrack = track,
            scaleType = ScaleType.FitInside,
            rendererType = RendererType.Texture,
            modifier = Modifier.layout { measurable, constraints ->
                val side = constraints.maxWidth
                val tall = side * FRAME_HEIGHT / FRAME_WIDTH
                val frame = measurable.measure(Constraints.fixed(side, tall))
                layout(side, constraints.maxHeight) { frame.place(0, constraints.maxHeight - tall) }
            },
        )
    }
}

/** The camera frame's shape as the glasses send it, 1080x1920 portrait (README, the camera paragraph). */
private const val FRAME_WIDTH = 9
private const val FRAME_HEIGHT = 16
