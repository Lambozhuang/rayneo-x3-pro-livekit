package io.livekit.android.example.voiceassistant

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
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
import kotlin.math.abs

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

    /**
     * `adb shell am start` (or the launcher icon) on an already running
     * instance lands here instead of onCreate -- but only because the manifest
     * says singleTop. With the default launch mode Android just brings the
     * task forward and drops the intent, even for the task's root activity.
     * The wearer launching again means the same thing as launching fresh: be
     * in the call. Take any new endpoint, then start from the connect screen.
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.i(TAG, "new intent, on connect screen=${navController?.currentDestination?.hasRoute(ConnectRoute::class)}")
        TokenEndpoint.applyIntent(this, intent)
        if (intent.getStringExtra("autostart") == "false") return
        val nav = navController ?: return
        if (nav.currentDestination?.hasRoute(ConnectRoute::class) == true) nav.navigate(savedRoute())
    }

    private fun savedRoute() = VoiceAssistantRoute(
        tokenEndpoint = TokenEndpoint.get(this).trim(),
        credential = TokenEndpoint.getCredential(this).trim(),
    )

    /**
     * The temple touchpad is, to Android, a touchscreen. RayNeo's docs
     * (Touch Events & Event Response) say so: both temples emit TP
     * `MotionEvent`s, one-dimensional, "X changing, Y fixed", and never a
     * `KeyEvent`. Their SDK feeds the raw events to a `TouchDispatcher` that
     * turns them into Click / DoubleClick / LongClick / SlideForward /
     * SlideBackward; that SDK is an AAR built on ViewBinding and
     * `BaseMirrorActivity`, which a Compose app cannot sit on, so the same
     * reduction is done here in a few lines. The glasses' convention, also
     * from the docs: single tap confirms, double tap goes back / exits.
     *
     *   tap           connect screen: start the call. In the call: nothing (yet).
     *   double tap    in the call: end it. Connect screen: leave the app.
     *   swipe         logged only, for now
     *
     * A swipe is a travel of more than [SWIPE_PX] along X between down and up;
     * anything shorter that lifts within [TAP_MS] is a tap, and a second tap
     * inside [DOUBLE_MS] upgrades the pair to a double tap. The wearer cannot
     * see their finger, so *where* a touch lands is meaningless; nothing on the
     * screens is clickable and no touch is ever passed to the Compose tree.
     */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = ev.x; downTime = ev.eventTime
            }
            MotionEvent.ACTION_UP -> {
                val dx = ev.x - downX
                val dt = ev.eventTime - downTime
                val gesture = when {
                    abs(dx) > SWIPE_PX -> if (dx > 0) "swipe +x" else "swipe -x"
                    dt < TAP_MS -> "tap"
                    else -> "hold"
                }
                Log.i(TAG, "gesture: $gesture dx=${dx.toInt()} dt=${dt}ms at x=${ev.x.toInt()} y=${ev.y.toInt()}")
                if (gesture == "tap") onTap(ev.eventTime)
            }
        }
        return true
    }

    private var downX = 0f
    private var downTime = 0L
    private var lastTapTime = 0L
    private val handler = Handler(Looper.getMainLooper())
    private val pendingSingleTap = Runnable { onGesture(Gesture.CLICK) }

    private fun onTap(time: Long) {
        if (time - lastTapTime < DOUBLE_MS) {
            handler.removeCallbacks(pendingSingleTap)
            lastTapTime = 0L
            onGesture(Gesture.DOUBLE_CLICK)
        } else {
            lastTapTime = time
            handler.postDelayed(pendingSingleTap, DOUBLE_MS)
        }
    }

    private enum class Gesture { CLICK, DOUBLE_CLICK }

    private fun onGesture(g: Gesture) {
        Log.i(TAG, "action: $g")
        val nav = navController ?: return
        val onConnect = nav.currentDestination?.hasRoute(ConnectRoute::class) == true
        when (g) {
            Gesture.CLICK -> if (onConnect) nav.navigate(savedRoute())
            Gesture.DOUBLE_CLICK -> if (onConnect) finish() else nav.navigateUp()
        }
    }

    /**
     * The gpio buttons (volume, camera, ...) do arrive as keys; they are logged
     * so we learn what the wearer has, and any plausible "select" key acts like
     * a single tap.
     */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        Log.i(TAG, "key down: ${KeyEvent.keyCodeToString(keyCode)} device=${event.deviceId} source=0x${event.source.toString(16)}")
        if (event.repeatCount > 0) return super.onKeyDown(keyCode, event)
        if (keyCode !in SELECT_KEYS) return super.onKeyDown(keyCode, event)
        onGesture(Gesture.CLICK)
        return true
    }

    companion object {
        private const val TAG = "rayneo-input"
        private const val SWIPE_PX = 150f
        private const val TAP_MS = 400L
        private const val DOUBLE_MS = 350L
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
