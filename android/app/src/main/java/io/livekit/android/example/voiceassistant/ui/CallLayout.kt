package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * One eye of the call. The build's title runs along the top over a line. Below it two columns divided by a line. The
 * left one is the build's: the step list under its heading, all steps in view, and at the bottom what the camera sees
 * ([preview], CameraPreview). The right one is the agent's: a framed head saying "Assistant" and who has the floor
 * (PhaseHeader), the agent's lines, newest at the bottom, under them the agent's [picture] while it names one
 * (Pictures.kt), as the newest thing the agent gave, and along the bottom, under a line, what the model heard the wearer
 * say (WearerOrHint). VoiceAssistantScreen fills it from the room, MockScreen from fixed data, so the two look the same.
 *
 * The picture's square also says when a picture is on its way (the agent has named it, its bytes are not here yet) and
 * when one did not arrive, so the wearer can ask for it again. The agent sends a picture only when the wearer asked for
 * one, so the glasses show nothing the conversation did not bring up, and they know nothing of what the picture shows.
 *
 * While the call is being set up (Phase.CONNECTING: the room not yet joined, the agent not yet listening, the build not
 * yet published) the eye shows only a ring and the word, so the layout does not assemble itself piece by piece in front
 * of the wearer; the camera's square keeps its place at the bottom of its column even before the steps have come.
 */
@Composable
fun CallLayout(
    progress: BuildProgress,
    phase: Phase,
    picture: Picture,
    preview: @Composable (Modifier) -> Unit,
    agentLines: @Composable (Modifier) -> Unit,
    wearerLine: @Composable (Modifier) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (phase == Phase.CONNECTING) {
        Connecting(modifier)
        return
    }
    Column(modifier = modifier.fillMaxSize()) {
        if (progress.title.isNotEmpty()) {
            BuildTitle(progress = progress, modifier = Modifier.padding(bottom = GAP))
            Hairline(Modifier.fillMaxWidth().height(1.dp))
        }
        Row(modifier = Modifier.fillMaxWidth().weight(1f).padding(top = GAP)) {
            Column(modifier = Modifier.width(PREVIEW_SIDE).fillMaxHeight()) {
                Column(modifier = Modifier.weight(1f)) {  // the list's room, kept even while there are no steps yet
                    StepsHeading(progress = progress)
                    BuildSteps(progress = progress, modifier = Modifier.padding(top = 4.dp))
                }
                preview(Modifier.size(PREVIEW_SIDE).border(1.dp, OUTLINE))
            }
            Hairline(Modifier.padding(horizontal = GAP).fillMaxHeight().width(1.dp))
            Column(modifier = Modifier.weight(1f).fillMaxHeight()) {
                PhaseHeader(phase = phase, modifier = Modifier.fillMaxWidth())
                agentLines(Modifier.weight(1f).fillMaxWidth().padding(top = GAP))
                if (picture != Picture.None) {
                    PictureArea(picture = picture, modifier = Modifier.padding(top = 8.dp).size(PICTURE_SIDE).border(1.dp, OUTLINE))
                }
                Hairline(Modifier.padding(top = GAP).fillMaxWidth().height(1.dp))
                WearerOrHint(phase = phase, modifier = Modifier.fillMaxWidth().padding(top = GAP), wearer = wearerLine)
            }
        }
    }
}

/** The whole eye while the call is being set up: a dim ring and the phase's word, nothing else. */
@Composable
private fun Connecting(modifier: Modifier) {
    Column(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator(color = OUTLINE, strokeWidth = 2.dp, modifier = Modifier.size(32.dp))
        Text(
            text = Phase.CONNECTING.label,
            color = Color(0xFF9E9E9E),
            fontSize = 20.sp,
            lineHeight = 26.sp,
            modifier = Modifier.padding(top = 16.dp),
        )
    }
}

/** A one-pixel line in the grey of the outlines; three of them divide the screen. */
@Composable
private fun Hairline(modifier: Modifier) {
    Box(modifier = modifier.background(OUTLINE))
}

/**
 * The agent's picture, a square under the agent's lines, framed like the camera's: the picture itself; a small dim ring
 * while the picture is on its way, which under a slow network is how long it takes; or the words that it did not arrive.
 * The ring and the words are dim: the display is additive.
 */
@Composable
private fun PictureArea(picture: Picture, modifier: Modifier = Modifier) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        when (picture) {
            is Picture.Shown -> Image(
                bitmap = picture.image,
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
            is Picture.Waiting -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = OUTLINE, strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
            }
            is Picture.Failed -> Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    text = "The picture did not arrive.\nAsk for it again.",
                    color = Color(0xFF9E9E9E),
                    fontSize = 16.sp,
                    lineHeight = 20.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(12.dp),
                )
            }
            Picture.None -> Unit
        }
    }
}

/** Side of the camera's square at the bottom of the build's column, and so the column's width; the step list, five
 * lines at 16 sp, takes the room above it, and the agent's column takes the rest of the eye's width. */
private val PREVIEW_SIDE = 200.dp

/** Side of the agent's picture under the agent's lines, which keep the space above it. */
private val PICTURE_SIDE = 192.dp

/** The space between every hairline and the content on either side of it. */
val GAP = 12.dp

/** The grey of every line and frame on the screen: the hairlines, the two squares' frames, the header's frame. */
private val OUTLINE = Color(0xFF333333)
