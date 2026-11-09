package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.border
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
 * shows the sentences for the stage the participant is in (Lab.stage) and nothing else: the connection's state is for
 * the log, and no gesture does anything here (MainActivity), so the participant cannot leave lab mode by mistake. In a
 * block of the user study's games (Lab.game) the sentences are the games' and sit in the green frame the hint line of a
 * trial uses (AgentHint), so the screen between trials reads as the same voice as the one within them; a session of
 * builds keeps its plain white sentences.
 */
@Composable
fun LabScreen() {
    val stage = Lab.stage
    val game = Lab.game

    Eyes {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxSize()
        ) {
            val sentences = stage.wording(game).lines()
            if (game != null) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = Modifier.border(2.dp, FRAME_GREEN, RoundedCornerShape(8.dp)).padding(horizontal = 18.dp, vertical = 10.dp),
                ) {
                    sentences.forEachIndexed { i, sentence ->
                        if (i > 0) Spacer(Modifier.height(SENTENCE_GAP))
                        Text(sentence, color = FRAME_GREEN, fontSize = 26.sp, lineHeight = 32.sp, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center)
                    }
                }
            } else {
                // One Text per sentence: a sentence that wraps keeps its lines close, and a gap separates it from the next.
                sentences.forEachIndexed { i, sentence ->
                    if (i > 0) Spacer(Modifier.height(SENTENCE_GAP))
                    Text(sentence, color = Color(0xFFEEEEEE), fontSize = 28.sp, lineHeight = 32.sp, textAlign = TextAlign.Center)
                }
            }
        }
    }
}

/** The green of the games' sentences and frame, the hint line's (Phase.kt AgentHint). */
private val FRAME_GREEN = Color(0xFF66E07A)

/** The space between two sentences of the stage's text, wider than the lines inside one so the sentences read apart. */
private val SENTENCE_GAP = 14.dp
