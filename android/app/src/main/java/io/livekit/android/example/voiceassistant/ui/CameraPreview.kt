package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import io.livekit.android.compose.ui.RendererType
import io.livekit.android.compose.ui.ScaleType
import io.livekit.android.compose.ui.VideoTrackView
import io.livekit.android.room.track.LocalVideoTrack

/**
 * What the camera sees, cut as the brain sees it: the bottom square of the portrait frame, the table in front of the
 * wearer (frames.py `bottom_square`). The whole frame is drawn at the square's width, 16:9 tall, aligned to the
 * square's bottom edge and clipped to it, so the wall and the far desk in the upper part fall outside. The renderer
 * is a TextureView: Compose cannot clip a SurfaceView. Eyes composes this twice, so two renderers draw the same
 * track; each binds to it on its own. Until the camera track exists the square keeps its outline.
 *
 * The display is additive, so the camera image is a patch of light in the eye beside the real scene; whether it
 * needs dimming is judged on the glasses, not here.
 */
@Composable
fun CameraPreview(track: LocalVideoTrack?, modifier: Modifier = Modifier) {
    if (track == null) {
        Box(modifier = modifier.border(1.dp, Color(0xFF333333)))
        return
    }
    BoxWithConstraints(modifier = modifier.clipToBounds(), contentAlignment = Alignment.BottomCenter) {
        VideoTrackView(
            videoTrack = track,
            scaleType = ScaleType.FitInside,
            rendererType = RendererType.Texture,
            modifier = Modifier.requiredSize(maxWidth, maxWidth * 16 / 9),
        )
    }
}
