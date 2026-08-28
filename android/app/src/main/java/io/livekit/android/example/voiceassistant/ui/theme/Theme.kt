package io.livekit.android.example.voiceassistant.ui.theme

import android.app.Activity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

/**
 * One scheme, always dark, background pure black.
 *
 * The X3 Pro's display is additive — it only ever adds light to what the wearer
 * is already looking at, and cannot subtract any. A black pixel emits nothing
 * and so reads as completely transparent, which is why the background here is
 * `Color.Black` and not the starter's near-black `0xFF070707`: that value would
 * render as a dimly glowing grey rectangle hanging in the room.
 *
 * The same reasoning removes the light scheme and dynamic colour that the
 * starter carried. There is no such thing as a light background on these
 * glasses, only a lamp aimed at the wearer's eyes. `surface` stays a very dark
 * grey rather than black, deliberately, so that panels like the control bar
 * still read as panels.
 */
private val GlassesColorScheme = darkColorScheme(
    primary = Blue500,
    secondary = PurpleGrey80,
    tertiary = Pink80,
    background = Color.Black,
    onBackground = Color(0xFFEEEEEE),
    surface = Color(0xFF131313),
    onSurface = Color(0xFFEEEEEE),
    outline = Color(0xFF202020),
)

@Composable
fun LiveKitVoiceAssistantExampleTheme(
    content: @Composable () -> Unit
) {
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = Color.Black.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }

    MaterialTheme(
        colorScheme = GlassesColorScheme,
        typography = Typography,
        content = content
    )
}
