package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
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
            Text(stage.text, color = Color(0xFFEEEEEE), fontSize = 22.sp, lineHeight = 30.sp, textAlign = TextAlign.Center)
        }
    }
}
