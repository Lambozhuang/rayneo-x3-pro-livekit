package io.livekit.android.example.voiceassistant

import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
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

    private var navController: NavHostController? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Raise this to VERBOSE to see each ICE candidate the client gathers --
        // the SDK logs them through `LKLog.v`, and they are the only client-side
        // view of what it actually produced.
        LiveKit.loggingLevel = LoggingLevel.DEBUG

        // Lets `adb shell am start ... -e token_endpoint <url>` retarget the app
        // without a rebuild. See TokenEndpoint.
        TokenEndpoint.applyIntent(this, intent)

        // The glasses' screen-off timeout is 30 s and cannot be raised by an
        // app. When it fires, SystemUI puts a clock overlay over everything,
        // the activity leaves the foreground, and the system silences the
        // microphone of a backgrounded app ("App op 27 missing, silencing
        // record"). A call that dies after half a minute of not touching
        // anything is not a call, so hold the screen for as long as this
        // activity is showing. It costs display power only while in the app.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Glasses have no pointer. Once the backend address is known, the only
        // thing a wearer can want from launching this app is to be in the call,
        // so go straight there; the connect screen is for the first run, and
        // for where the call returns to when it ends. `-e autostart false`
        // keeps the connect screen for debugging it.
        val autoStart = savedInstanceState == null &&
            TokenEndpoint.get(this) != TokenEndpoint.DEFAULT &&
            intent?.getStringExtra("autostart") != "false"

        setContent {
            val navController = rememberNavController().also { this.navController = it }
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
                if (autoStart) {
                    LaunchedEffect(Unit) { navController.navigate(savedRoute()) }
                }
            }
        }
    }

    private fun savedRoute() = VoiceAssistantRoute(
        tokenEndpoint = TokenEndpoint.get(this).trim(),
        credential = TokenEndpoint.getCredential(this).trim(),
    )

    /**
     * The temple touchpads reach apps as key events, not touches: the panels
     * are one-dimensional strips (`cyttsp5_mt` / `cyttsp6_mt`, X only) whose
     * firmware also declares F1..F8, and RayNeo's own launcher selects by
     * focus rather than by pointing. Which gesture becomes which keycode is
     * not documented anywhere we can reach, so every key is logged and any of
     * the plausible "select" keys acts as the one control this app has: start
     * the call from the connect screen, end it from the call.
     */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        Log.i(TAG, "key down: ${KeyEvent.keyCodeToString(keyCode)} device=${event.deviceId} source=0x${event.source.toString(16)}")
        if (event.repeatCount > 0) return super.onKeyDown(keyCode, event)
        if (keyCode !in SELECT_KEYS) return super.onKeyDown(keyCode, event)

        val nav = navController ?: return super.onKeyDown(keyCode, event)
        if (nav.currentDestination?.hasRoute(ConnectRoute::class) == true) {
            nav.navigate(savedRoute())
        } else {
            nav.navigateUp()
        }
        return true
    }

    companion object {
        private const val TAG = "rayneo-input"
        private val SELECT_KEYS = setOf(
            KeyEvent.KEYCODE_ENTER,
            KeyEvent.KEYCODE_NUMPAD_ENTER,
            KeyEvent.KEYCODE_DPAD_CENTER,
            KeyEvent.KEYCODE_BUTTON_A,
            KeyEvent.KEYCODE_F1, KeyEvent.KEYCODE_F2, KeyEvent.KEYCODE_F3, KeyEvent.KEYCODE_F4,
            KeyEvent.KEYCODE_F5, KeyEvent.KEYCODE_F6, KeyEvent.KEYCODE_F7, KeyEvent.KEYCODE_F8,
        )
    }
}
