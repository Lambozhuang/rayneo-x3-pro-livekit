package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
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
 * Waiting for the lab console. The glasses are connected to it as the target device (Lab) and the console starts the
 * task: the call opens over this screen and comes back to it when the task ends. The screen shows what the connection
 * is doing and the last task; a double tap leaves lab mode and goes back to the menu (MainActivity).
 */
@Composable
fun LabScreen() {
    val console = Lab.console
    val status = Lab.status
    val run = Lab.run

    Eyes {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top,
            modifier = Modifier.fillMaxSize()
        ) {
            Text("Lab", color = MaterialTheme.colorScheme.onBackground, fontSize = 20.sp)
            Spacer(Modifier.size(6.dp))
            Text(console ?: "no console address", color = Color(0xFF9E9E9E), fontSize = 15.sp)
            Spacer(Modifier.size(20.dp))
            Text(status, color = Color(0xFFEEEEEE), fontSize = 18.sp, lineHeight = 24.sp, textAlign = TextAlign.Center)
            if (run != null) {
                Spacer(Modifier.size(12.dp))
                Text("${run.runType} task ${run.taskNumber}: ${run.label}", color = Color(0xFFBDBDBD), fontSize = 16.sp,
                     textAlign = TextAlign.Center)
            }
            Spacer(Modifier.weight(1f))
            Text("the console starts the task · double tap: back", color = Color(0xFF9E9E9E), fontSize = 14.sp)
        }
    }
}
