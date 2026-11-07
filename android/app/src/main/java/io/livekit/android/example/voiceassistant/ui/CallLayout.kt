package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
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
 * One eye of the call. A band along the top and the agent's dots along the bottom; the rest of the eye is the room.
 * The band: the build's title over a line, with the time left of the lab's limit at its right end during a lab run
 * ([remaining]); under it the step list, all steps in view on one line each, running from the left edge to the one
 * square at the right, which shows what the camera sees ([preview], CameraPreview) or, while the agent names one, the
 * agent's [picture] (Pictures.kt) in its place. Along the bottom edge, in the middle, the five dots that move with the
 * conversation (AgentDots), and above them a line saying what to do when the connection or the agent is lost
 * (PhaseHint), the one state that still gets words.
 *
 * The layout is the user's choice of 2026-11-06 among mock-ups drawn on a monitor. The two columns of the layout before
 * it, the build's at the left and the agent's at the right, had been drawn for the captions, which the screen has not
 * shown since 2026-11-05 (the transcripts came late and sometimes wrong, and the participant's task is the bricks, not the
 * screen), and without them the right column held a framed word and nothing else. Everything now sits in the upper
 * part of the eye, which lies over the far desk, and the lower middle, where the wearer sees the plate, holds only the
 * dots, which are small and are there so that a wearer looking at the bricks sees the agent react without looking up.
 * The camera and the picture share a square: while the picture is up, the wearer looks at the picture and has the
 * real table before them, and the voice says when the glasses show a picture and when the live view is back.
 *
 * The picture's square also says when a picture is on its way (the agent has named it, its bytes are not here yet) and
 * when one did not arrive, so the wearer can ask for it again. The agent sends a picture only when the wearer asked for
 * one, so the glasses show nothing the conversation did not bring up, and they know nothing of what the picture shows.
 *
 * While the call is being set up (Phase.CONNECTING: the room not yet joined, the agent not yet listening, the build not
 * yet published) the eye shows only a ring and the word, so the layout does not assemble itself piece by piece in front
 * of the wearer. VoiceAssistantScreen fills the layout from the room, MockScreen from a scripted scene, so the two look
 * the same; [seconds], [level] and [flash] are read while the dots are drawn, not when this is composed.
 */
@Composable
fun CallLayout(
    progress: BuildProgress,
    phase: Phase,
    picture: Picture,
    preview: @Composable (Modifier) -> Unit,
    seconds: () -> Float,
    level: () -> Float,
    flash: () -> Flash?,
    remaining: String? = null,
    modifier: Modifier = Modifier,
) {
    if (phase == Phase.CONNECTING) {
        Connecting(modifier)
        return
    }
    Box(modifier = modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxWidth()) {
            if (progress.title.isNotEmpty() || remaining != null) {
                // The build's title and, at the right end, the time left of the lab's limit (VoiceAssistantScreen).
                Row(modifier = Modifier.fillMaxWidth().padding(bottom = GAP), verticalAlignment = Alignment.CenterVertically) {
                    BuildTitle(progress = progress, modifier = Modifier.weight(1f))
                    if (remaining != null) {
                        Text(text = remaining, color = Color(0xFFBDBDBD), fontSize = 20.sp, lineHeight = 26.sp, maxLines = 1)
                    }
                }
                Hairline(Modifier.fillMaxWidth().height(1.dp))
            }
            Row(modifier = Modifier.fillMaxWidth().padding(top = GAP).height(SQUARE)) {
                Column(modifier = Modifier.weight(1f).fillMaxHeight()) {
                    StepsHeading(progress = progress)
                    BuildSteps(progress = progress, modifier = Modifier.padding(top = 4.dp))
                }
                Spacer(Modifier.width(GAP))
                Box(modifier = Modifier.size(SQUARE).border(1.dp, OUTLINE)) {
                    if (picture == Picture.None) {
                        preview(Modifier.fillMaxSize())
                    } else {
                        PictureArea(picture = picture, modifier = Modifier.fillMaxSize())
                    }
                }
            }
        }
        Column(modifier = Modifier.align(Alignment.BottomCenter), horizontalAlignment = Alignment.CenterHorizontally) {
            PhaseHint(phase = phase)
            AgentDots(phase = phase, seconds = seconds, level = level, flash = flash)
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

/** A one-pixel line in the grey of the outlines, under the title. */
@Composable
private fun Hairline(modifier: Modifier) {
    Box(modifier = modifier.background(OUTLINE))
}

/**
 * The agent's picture in the square: the picture itself; a small dim ring while the picture is on its way, which under
 * a slow network is how long it takes; or the words that it did not arrive. The ring and the words are dim: the
 * display is additive.
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

/** Side of the square at the right of the band, the camera's view or the picture, and so the band's height under the
 * title; the step list takes the width left of it, about 400 dp, where the longest step name takes under 200 dp. */
private val SQUARE = 200.dp

/** The space between the title's line and the band, and between the step list and the square. */
val GAP = 12.dp

/** The grey of every line and frame on the screen: the hairline and the square's frame. */
private val OUTLINE = Color(0xFF333333)
