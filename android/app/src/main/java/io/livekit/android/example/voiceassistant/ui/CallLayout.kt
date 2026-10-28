package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.Image
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
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * One eye of the call: above the band, the build on the left (a square, the build's title, the steps) and the agent's
 * lines on the right; the band along the bottom says who has the floor and what the model heard the wearer say.
 * VoiceAssistantScreen fills it from the room, MockScreen from fixed data, so the two look the same.
 *
 * The square shows what the camera sees ([preview], CameraPreview), so the wearer knows what the assistant can see,
 * until the agent names a [picture] (Pictures.kt): then the square says one is on its way, shows it when its bytes have
 * arrived, or says it did not arrive so the wearer can ask again, and goes back to the camera when the agent clears the
 * name. The agent sends a picture only when the wearer asked for one, so the glasses show nothing the conversation did
 * not bring up, and they know nothing of what the picture shows.
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
    Column(modifier = modifier.fillMaxSize()) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            modifier = Modifier.fillMaxWidth().weight(1f)
        ) {
            Column(modifier = Modifier.width(LEFT_WIDTH).fillMaxHeight()) {
                val square = Modifier.size(DIAGRAM_SIDE)
                when (picture) {
                    Picture.None -> preview(square)
                    is Picture.Shown -> Image(bitmap = picture.image, contentDescription = null, modifier = square)
                    is Picture.Waiting -> Box(modifier = square.border(1.dp, OUTLINE), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = OUTLINE, strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
                    }
                    is Picture.Failed -> Box(modifier = square.border(1.dp, OUTLINE), contentAlignment = Alignment.Center) {
                        Text(
                            text = "The picture did not arrive.\nAsk for it again.",
                            color = Color(0xFF9E9E9E),
                            fontSize = 14.sp,
                            lineHeight = 18.sp,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(12.dp),
                        )
                    }
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

/** Side of the square for the camera's view or the agent's picture, out of the 592 px an eye has after its margins. */
private val DIAGRAM_SIDE = 216.dp

/** The square's outline while it waits for a picture or reports one missing, the grey CameraPreview uses too. */
private val OUTLINE = Color(0xFF333333)
