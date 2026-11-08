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
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hasRoute
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import io.livekit.android.LiveKit
import io.livekit.android.example.voiceassistant.screen.ConnectRoute
import io.livekit.android.example.voiceassistant.screen.ConnectScreen
import io.livekit.android.example.voiceassistant.screen.ExposureRoute
import io.livekit.android.example.voiceassistant.screen.ExposureScreen
import io.livekit.android.example.voiceassistant.screen.LabRoute
import io.livekit.android.example.voiceassistant.screen.LabScreen
import io.livekit.android.example.voiceassistant.screen.Menu
import io.livekit.android.example.voiceassistant.screen.MenuRoute
import io.livekit.android.example.voiceassistant.screen.MenuScreen
import io.livekit.android.example.voiceassistant.screen.MockRoute
import io.livekit.android.example.voiceassistant.screen.MockScreen
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantRoute
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantScreen
import io.livekit.android.example.voiceassistant.ui.theme.LiveKitVoiceAssistantExampleTheme
import io.livekit.android.example.voiceassistant.viewmodel.VoiceAssistantViewModel
import io.livekit.android.util.LoggingLevel
import kotlin.math.abs
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private var navController: NavHostController? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Raise this to VERBOSE to see each ICE candidate the client gathers --
        // the SDK logs them through `LKLog.v`, and they are the only client-side
        // view of what it actually produced.
        LiveKit.loggingLevel = LoggingLevel.DEBUG

        // Lets `adb shell am start ... -e token_endpoint <url>` retarget the app
        // without a rebuild (TokenEndpoint), `-e lab_console <url>` name the lab console (Lab), `-e task <name>`
        // preselect a build (Tasks), `--ez record true` record the calls (Recording; off on any launch without it),
        // `--ei exposure <n>` set the camera's exposure compensation (Exposure; the camera's own 0 without it),
        // `-e game A|B` make the launch's calls trials of that game of the user study (Lab), and `--ei max_kbps <n>` cap
        // the camera track's bitrate (Uplink; 4000 without it).
        TokenEndpoint.applyIntent(this, intent)
        Lab.applyIntent(this, intent)
        Tasks.applyIntent(this, intent)
        Recording.applyIntent(intent)
        Exposure.applyIntent(intent)
        Uplink.applyIntent(intent)
        // The camera opens through CameraX from here on, so the compensation can be set on it; before any track.
        Exposure.install(this)

        // The glasses' screen-off timeout is 30 s and cannot be raised by an
        // app. When it fires, SystemUI puts a clock overlay over everything,
        // the activity leaves the foreground, and the system silences the
        // microphone of a backgrounded app ("App op 27 missing, silencing
        // record"). A call that dies after half a minute of not touching
        // anything is not a call, so hold the screen for as long as this
        // activity is showing. It costs display power only while in the app.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // The app opens on the menu: `Lab` hands the glasses to the lab console, which starts and ends the tasks
        // (LabScreen, Lab); `Debug` is the build picker, swipe to choose, tap to start (ConnectScreen). The call
        // returns to whichever it came from when it ends.
        // `--ez mock true` opens it on the mock call screen instead (MockScreen), to look at the layout without a server;
        // `--ez exposure_sweep true` on the exposure sweep (ExposureScreen), which photographs the desk and leaves.
        val mock = intent.getBooleanExtra("mock", false)
        val sweep = intent.getBooleanExtra(Exposure.EXTRA_SWEEP, false)
        // A launch that names the console (`-e lab_console`, glasses.ps1 -Lab) opens on the lab screen in lab mode: the
        // participant never sees the menu. `--es lab_mock waiting|after|problem` opens the lab screen in that stage with
        // no console (Lab.mock).
        val labLaunch = intent.getStringExtra("lab_console") != null
        val labMock = intent.getStringExtra("lab_mock")
        if (labMock != null) Lab.mock(labMock) else if (labLaunch) Lab.start(this)
        // The lab console's start_task opens the call over the lab screen, its end_task leaves it; the call screen
        // itself tells Lab when it is gone (VoiceAssistantScreen), which is when the run is reported.
        Lab.screens = object : Lab.Screens {
            override fun startCall(run: Lab.Run): Boolean {
                val nav = navController ?: return false
                // A task on screen that the console has reset: its screen goes first, and reports nothing (Lab.callEnded).
                if (nav.currentDestination?.hasRoute(VoiceAssistantRoute::class) == true) nav.navigateUp()
                if (nav.currentDestination?.hasRoute(LabRoute::class) != true) {
                    Log.w(TAG, "start_task while not on the lab screen")
                    return false
                }
                nav.navigate(route(run))
                return true
            }

            override fun endCall() {
                val nav = navController ?: return
                if (nav.currentDestination?.hasRoute(VoiceAssistantRoute::class) == true) nav.navigateUp()
            }
        }
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
                val start: Any = if (sweep) ExposureRoute else if (mock) MockRoute else if (labMock != null || labLaunch) LabRoute else MenuRoute
                NavHost(navController, startDestination = start) {
                    composable<MenuRoute> { MenuScreen() }
                    composable<LabRoute> { LabScreen() }
                    composable<ConnectRoute> { ConnectScreen() }
                    composable<MockRoute> { MockScreen() }
                    composable<ExposureRoute> { ExposureScreen(onDone = { finish() }) }

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

    /**
     * `adb shell am start` (or the launcher icon) on an already running
     * instance lands here instead of onCreate -- but only because the manifest
     * says singleTop. With the default launch mode Android just brings the
     * task forward and drops the intent, even for the task's root activity.
     * Launching again means the same as launching fresh: take any new endpoint
     * and build pick, recording on or off, and (on the connect screen) fetch the list again.
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        val onConnect = navController?.currentDestination?.hasRoute(ConnectRoute::class) == true
        Log.i(TAG, "new intent, on connect screen=$onConnect")
        TokenEndpoint.applyIntent(this, intent)
        Lab.applyIntent(this, intent)
        Tasks.applyIntent(this, intent)
        Recording.applyIntent(intent)
        Exposure.applyIntent(intent)
        if (onConnect) lifecycleScope.launch { Tasks.load(this@MainActivity, TokenEndpoint.get(this@MainActivity)) }
    }

    /** The call with the build the console named (`run`), or with the one picked on the connect screen. */
    private fun route(run: Lab.Run?) = VoiceAssistantRoute(
        tokenEndpoint = TokenEndpoint.get(this).trim(),
        credential = TokenEndpoint.getCredential(this).trim(),
        task = run?.task?.name ?: Tasks.pick?.name ?: "",
        game = Lab.game?.uppercase() ?: "",
        sid = run?.sid ?: "",
        runId = run?.runId ?: 0,
        console = if (run != null) Lab.console ?: "" else "",
    )

    /**
     * The temple touchpad is, to Android, a touchscreen. RayNeo's docs
     * (Touch Events & Event Response) say so: both temples emit TP
     * `MotionEvent`s, one-dimensional, "X changing, Y fixed", and never a
     * `KeyEvent` (on our pair Y does change: touches end anywhere from y=51 to
     * y=348, so a swipe across the temple is told apart too). Their SDK feeds the raw events to a `TouchDispatcher` that
     * turns them into Click / DoubleClick / LongClick / SlideForward /
     * SlideBackward; that SDK is an AAR built on ViewBinding and
     * `BaseMirrorActivity`, which a Compose app cannot sit on, so the same
     * reduction is done here in a few lines. The glasses' convention, also
     * from the docs: single tap confirms, double tap goes back / exits.
     *
     *   tap           menu: enter the pick. Connect screen: start the call with the picked build. Elsewhere: nothing.
     *   double tap    in the call: end it, except in a lab run, which the console or the finished build ends. Lab
     *                 screen: nothing. Connect screen: back to the menu. Menu and mock screen: leave the app.
     *   triple tap    the experimenter's way back in lab mode, said nowhere on screen: in a lab call, end it; on the
     *                 lab screen, leave lab mode for the menu. Elsewhere: nothing.
     *   swipe         menu and connect screen: move the pick (+x or down: next, -x or up: previous). Elsewhere: logged only
     *
     * A swipe is a travel of more than [SWIPE_PX] along X, or [SWIPE_PX_Y] along Y, between down and up,
     * along whichever axis it travelled further;
     * anything shorter that lifts within [TAP_MS] is a tap; taps that follow each other inside [DOUBLE_MS] count
     * together, and [DOUBLE_MS] after the last one the count is one gesture: a tap, a double tap or a triple tap, so a
     * double tap is known a third of a second after it, when no third tap came. The wearer cannot
     * see their finger, so *where* a touch lands is meaningless; nothing on the
     * screens is clickable and no touch is ever passed to the Compose tree.
     */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = ev.x; downY = ev.y; downTime = ev.eventTime
            }
            MotionEvent.ACTION_UP -> {
                val dx = ev.x - downX
                val dy = ev.y - downY
                val dt = ev.eventTime - downTime
                val gesture = when {
                    abs(dx) > SWIPE_PX && abs(dx) >= abs(dy) -> if (dx > 0) "swipe +x" else "swipe -x"
                    abs(dy) > SWIPE_PX_Y -> if (dy > 0) "swipe +y" else "swipe -y"
                    dt < TAP_MS -> "tap"
                    else -> "hold"
                }
                Log.i(TAG, "gesture: $gesture dx=${dx.toInt()} dy=${dy.toInt()} dt=${dt}ms at x=${ev.x.toInt()} y=${ev.y.toInt()}")
                if (gesture == "tap") onTap(ev.eventTime)
                if (gesture.startsWith("swipe")) {
                    val delta = if (gesture.endsWith("+x") || gesture.endsWith("+y")) 1 else -1
                    val here = navController?.currentDestination
                    if (here?.hasRoute(ConnectRoute::class) == true) Tasks.move(this, delta)
                    if (here?.hasRoute(MenuRoute::class) == true) Menu.move(delta)
                }
            }
        }
        return true
    }

    private var downX = 0f
    private var downY = 0f
    private var downTime = 0L
    private var lastTapTime = 0L
    private var taps = 0  // taps in the run so far
    private val handler = Handler(Looper.getMainLooper())
    private val pendingTaps = Runnable {
        val n = taps
        taps = 0
        onGesture(if (n >= 3) Gesture.TRIPLE_CLICK else if (n == 2) Gesture.DOUBLE_CLICK else Gesture.CLICK)
    }

    private fun onTap(time: Long) {
        taps = if (time - lastTapTime < DOUBLE_MS) taps + 1 else 1
        lastTapTime = time
        handler.removeCallbacks(pendingTaps)
        handler.postDelayed(pendingTaps, DOUBLE_MS)
    }

    private enum class Gesture { CLICK, DOUBLE_CLICK, TRIPLE_CLICK }

    private fun onGesture(g: Gesture) {
        Log.i(TAG, "action: $g")
        val nav = navController ?: return
        val here = nav.currentDestination
        val onMenu = here?.hasRoute(MenuRoute::class) == true
        val onLab = here?.hasRoute(LabRoute::class) == true
        val onCall = here?.hasRoute(VoiceAssistantRoute::class) == true
        val onConnect = here?.hasRoute(ConnectRoute::class) == true
        val onMock = here?.hasRoute(MockRoute::class) == true
        when (g) {
            Gesture.CLICK -> when {
                onMenu && Menu.pick == Menu.Entry.LAB -> { Lab.start(this); nav.navigate(LabRoute) }
                onMenu -> nav.navigate(ConnectRoute)
                onConnect && Tasks.pick != null -> nav.navigate(route(null))
            }
            Gesture.DOUBLE_CLICK -> when {
                onMenu || onMock -> finish()
                onLab -> Log.i(TAG, "double tap on the lab screen: nothing")
                onCall && Lab.run != null -> Log.i(TAG, "double tap in a lab run: nothing; the console or the finished build ends it")
                else -> nav.navigateUp()
            }
            Gesture.TRIPLE_CLICK -> when {  // the experimenter's, said nowhere on screen
                onCall && Lab.run != null -> { Log.i(TAG, "triple tap: the experimenter ends the lab call"); nav.navigateUp() }
                onLab -> { Log.i(TAG, "triple tap: the experimenter leaves lab mode"); Lab.stop(); if (!nav.navigateUp()) nav.navigate(MenuRoute) }
                else -> Log.i(TAG, "triple tap: nothing here")
            }
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
        private const val SWIPE_PX_Y = 80f  // the strip is narrow across; taps drift ~50 px in y
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
