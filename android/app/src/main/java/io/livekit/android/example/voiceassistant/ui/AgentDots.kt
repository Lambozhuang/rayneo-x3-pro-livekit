package io.livekit.android.example.voiceassistant.ui

import android.os.SystemClock
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.unit.dp
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

/**
 * The agent as five dots along the bottom of the eye, the one thing on the screen that moves with the conversation.
 * The words "Listening" and "Speaking" in a frame, which the screen showed until 2026-11-06, had to be read, and read
 * late: the wearer's eyes are on the bricks, and the words came from the SFU's speaker detection and the agent's own
 * state attribute, both of which reach the glasses well after the sound does. The dots are read in the corner of the
 * eye, and what drives them is the sound itself at the glasses, or the agent's word the instant it acts:
 *
 *   READY         five dim grey dots, breathing slowly: the mic is open, nothing is happening
 *   LISTENING     white bars rising and falling with the wearer's voice at the microphone here, with no network in between
 *   THINKING      a white light running along the dots: the wearer has finished and the reply has not yet arrived
 *   SPEAKING      blue bars moving with the agent's voice as it comes out of the decoder here
 *   LOOKING       a blue light running along the dots: a brick is down and the brain is judging the plate
 *   RECONNECTING  amber dots blinking, with the hint above them; LOST and NO_AGENT red, likewise
 *   a Flash       all five dots large and green or red, fading over FLASH_MS: the agent has just judged the brick in
 *                 the hand, which it tells the glasses the instant it tells the voice, 0.7 s before the voice says it
 *
 * The time, the level and the flash come as lambdas and are read while drawing, so a frame redraws the canvas and
 * recomposes nothing. Eyes composes this twice; the time is [rememberSeconds] hoisted above it, so both eyes draw the
 * same instant. The display is additive: black is the room, and a colour at low alpha is a faint light.
 */
@Composable
fun AgentDots(
    phase: Phase,
    seconds: () -> Float,
    level: () -> Float,
    flash: () -> Flash?,
    modifier: Modifier = Modifier,
) {
    Canvas(modifier = modifier.size(DOTS_WIDTH, DOTS_HEIGHT)) {
        val t = seconds()
        val cy = size.height / 2
        val r = DOT.toPx()
        val gap = DOT_GAP.toPx()
        val xs = FloatArray(COUNT) { i -> size.width / 2 + (i - (COUNT - 1) / 2f) * gap }
        when (phase) {
            Phase.READY, Phase.CONNECTING -> xs.forEachIndexed { i, x ->
                dot(x, cy, r * 0.8f, GREY.copy(alpha = 0.5f + 0.2f * sin(t * 2 + i)))
            }
            Phase.LISTENING -> bars(xs, cy, r, t, level(), WHITE)
            Phase.SPEAKING -> bars(xs, cy, r, t, level(), BLUE)
            Phase.THINKING -> chase(xs, cy, r, t, WHITE)
            Phase.LOOKING -> chase(xs, cy, r, t, BLUE)
            Phase.RECONNECTING -> xs.forEach { x -> dot(x, cy, r * 0.8f, AMBER.copy(alpha = 0.55f + 0.35f * sin(t * 6))) }
            Phase.LOST, Phase.NO_AGENT -> xs.forEach { x -> dot(x, cy, r * 0.8f, RED.copy(alpha = 0.55f + 0.35f * sin(t * 6))) }
        }
        val f = flash()
        if (f != null) {
            val age = (SystemClock.uptimeMillis() - f.at) / 1000f
            if (age in 0f..FLASH_S) {
                val a = 1 - age / FLASH_S
                val colour = if (f.yes) GREEN else RED
                xs.forEach { x -> dot(x, cy, r * (1.7f - 0.5f * (1 - a)), colour.copy(alpha = a)) }
            }
        }
    }
}

/** A verdict on the brick in the hand, flashed over the dots: green when [yes], red when not, from [at] (uptime millis). */
data class Flash(val yes: Boolean, val at: Long)

/** Seconds since the first frame after this was composed, advanced every frame; the time base of the dots' motion. */
@Composable
fun rememberSeconds(): State<Float> {
    val seconds = remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        val t0 = withFrameNanos { it }
        while (true) {
            withFrameNanos { now -> seconds.floatValue = (now - t0) / 1e9f }
        }
    }
    return seconds
}

/** A dot of radius [r], or a bar of height [h] with round ends when that is taller than the dot. */
private fun DrawScope.dot(x: Float, cy: Float, r: Float, colour: Color, h: Float = 0f) {
    if (h <= 2 * r) {
        drawCircle(colour, r, Offset(x, cy))
    } else {
        drawRoundRect(colour, Offset(x - r, cy - h / 2), Size(2 * r, h), CornerRadius(r, r))
    }
}

/** Bars rising with the voice: the level sets how tall, a wave along the row keeps them from rising as one. */
private fun DrawScope.bars(xs: FloatArray, cy: Float, r: Float, t: Float, level: Float, colour: Color) {
    val reach = BAR_MAX.toPx() - 2 * r
    xs.forEachIndexed { i, x ->
        val h = 2 * r + reach * level * (0.35f + 0.65f * abs(sin(t * 9 + i * 1.7f)))
        dot(x, cy, r, colour, h)
    }
}

/** A light running along the row, left to right, once every 0.8 s: the agent is at work and nothing has come yet. */
private fun DrawScope.chase(xs: FloatArray, cy: Float, r: Float, t: Float, colour: Color) {
    xs.forEachIndexed { i, x ->
        val v = 0.5f * (1 + cos(2 * Math.PI.toFloat() * t * 1.2f - i * 0.9f))
        dot(x, cy, r * (0.8f + 0.3f * v), colour.copy(alpha = 0.25f + 0.75f * v * v * v))
    }
}

private const val COUNT = 5
private const val FLASH_S = 1.2f
private val DOT = 6.dp
private val DOT_GAP = 26.dp
private val BAR_MAX = 56.dp
val DOTS_WIDTH = 220.dp
val DOTS_HEIGHT = 70.dp

private val GREY = Color(0xFF9E9E9E)
private val WHITE = Color(0xFFEEEEEE)
private val BLUE = Color(0xFF66B1FF)
private val GREEN = Color(0xFF1FF968)
private val RED = Color(0xFFFF5252)
private val AMBER = Color(0xFFFFC107)
