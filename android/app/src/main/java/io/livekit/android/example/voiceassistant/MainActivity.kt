package io.livekit.android.example.voiceassistant

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import io.livekit.android.LiveKit
import io.livekit.android.example.voiceassistant.screen.ConnectRoute
import io.livekit.android.example.voiceassistant.screen.ConnectScreen
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantRoute
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantScreen
import io.livekit.android.example.voiceassistant.ui.theme.LiveKitVoiceAssistantExampleTheme
import io.livekit.android.example.voiceassistant.viewmodel.VoiceAssistantViewModel
import io.livekit.android.util.LoggingLevel

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Raise this to VERBOSE to see each ICE candidate the client gathers --
        // the SDK logs them through `LKLog.v`, and they are the only client-side
        // view of what it actually produced.
        LiveKit.loggingLevel = LoggingLevel.DEBUG

        // Lets `adb shell am start ... -e token_endpoint <url>` retarget the app
        // without a rebuild. See TokenEndpoint.
        TokenEndpoint.applyIntent(this, intent)

        setContent {
            val navController = rememberNavController()
            LiveKitVoiceAssistantExampleTheme {
                // No Scaffold, and no window-inset padding. The starter used both
                // to keep clear of a phone's status and navigation bars. Those
                // windows do exist here but are zero-sized, so the padding was
                // measurably nothing — and taking insets at the root of a stereo
                // surface is a trap worth closing anyway: a horizontal inset
                // spans the whole 1280 px, so it comes off the *outer* edge of
                // each eye and none of the inner one. The pair would stop being
                // mirror-symmetric. Per-eye margins belong to Eyes, which
                // applies them to each panel evenly.
                NavHost(navController, startDestination = ConnectRoute) {
                    composable<ConnectRoute> {
                        ConnectScreen(navigateToVoiceAssistant = { voiceAssistantRoute ->
                            runOnUiThread {
                                navController.navigate(voiceAssistantRoute)
                            }
                        })
                    }

                    composable<VoiceAssistantRoute> {
                        val viewModel = viewModel<VoiceAssistantViewModel>()
                        VoiceAssistantScreen(
                            viewModel = viewModel,
                            onEndCall = {
                                runOnUiThread { navController.navigateUp() }
                            }
                        )
                    }
                }
            }
        }
    }
}
