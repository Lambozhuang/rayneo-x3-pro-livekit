package io.livekit.android.example.voiceassistant.screen

import android.app.Application
import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import io.livekit.android.example.voiceassistant.Exposure
import io.livekit.android.example.voiceassistant.requirePermissions
import io.livekit.android.example.voiceassistant.ui.Eyes
import kotlinx.coroutines.delay
import kotlinx.serialization.Serializable

@Serializable
object ExposureRoute

/**
 * Records the scene at each exposure compensation of [Exposure.SWEEP] and leaves. `glasses.ps1 -ExposureSweep`
 * opens the app on it; the wearer looks at the desk and keeps still until the screen says done, about 25 s. The
 * screen shows the step the sweep is at; the recording lands in the app's external files dir under `exposure/`.
 */
@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun ExposureScreen(onDone: () -> Unit) {
    val context = LocalContext.current
    val permissions = requirePermissions(microphone = false, camera = true)
    var status by remember { mutableStateOf("waiting for the camera permission") }
    if (permissions.allPermissionsGranted) {
        LaunchedEffect(Unit) {
            val result = runCatching { Exposure.sweep(context.applicationContext as Application) { status = it } }
            status = result.fold({ "done: ${Exposure.SWEEP.size} compensations recorded" }, { "failed: ${it.message}" })
            result.onFailure { Log.e("rayneo-camera", "sweep failed", it) }
            delay(3_000)
            onDone()
        }
    }
    Eyes {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.fillMaxSize().padding(24.dp),
        ) {
            Text("Exposure sweep", color = Color.White, fontSize = 28.sp)
            Text("Look at the desk and keep still.", color = Color.LightGray, fontSize = 20.sp, modifier = Modifier.padding(top = 12.dp))
            Text(status, color = Color.White, fontSize = 20.sp, modifier = Modifier.padding(top = 24.dp))
        }
    }
}
