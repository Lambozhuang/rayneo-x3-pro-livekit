package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.example.voiceassistant.Lab
import io.livekit.android.example.voiceassistant.ui.Eyes
import kotlinx.serialization.Serializable

@Serializable
object LabRoute

/**
 * The participant's screen between tasks. The glasses are connected to the lab console as the target device (Lab) and
 * the console starts the task: the call opens over this screen and comes back to it when the task ends. The screen
 * shows one sentence for the stage the participant is in (Lab.stage) and nothing else: the connection's state is for
 * the log, and no gesture does anything here (MainActivity), so the participant cannot leave lab mode by mistake.
 */
@Composable
fun LabScreen() {
    val stage = Lab.stage

    Eyes {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxSize()
        ) {
            // One Text per sentence: a sentence that wraps keeps its lines close, and a gap separates it from the next.
            stage.text.lines().forEachIndexed { i, sentence ->
                if (i > 0) Spacer(Modifier.height(SENTENCE_GAP))
                Text(sentence, color = Color(0xFFEEEEEE), fontSize = 28.sp, lineHeight = 32.sp, textAlign = TextAlign.Center)
            }
        }
    }
}

/** The space between two sentences of the stage's text, wider than the lines inside one so the sentences read apart. */
private val SENTENCE_GAP = 14.dp
