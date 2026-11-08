package io.livekit.android.example.voiceassistant.ui

import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import io.livekit.android.example.voiceassistant.SpeechEdgeLog

/**
 * Who is sounding at the glasses this instant, read from the audio itself: the microphone's track for the wearer and
 * the agent's decoded track for the agent, through the two [SpeechEdgeLog] sinks the call screen already attaches for
 * its timing log. Nothing here waits for the network: the wearer's bars move with the voice at the mic, and the
 * agent's with the sound as it comes out of the decoder, which is when the wearer hears it.
 *
 * [waiting] is the stretch the words came from nowhere: the wearer's voice has stopped, and no sound has come from the
 * agent since. It ends when the agent's voice arrives, when the wearer speaks again, or after [WAIT_MAX_MS] with
 * nothing, which is longer than any reply measured so far, so that under a slow network the dots do not give up
 * before the reply comes. A burst at the microphone that begins while the agent's voice is in the room, or within
 * [ECHO_MS] after it, is taken as that voice coming back through the open-ear speakers, not the wearer's, and
 * neither counts as the wearer sounding nor starts a wait.
 */
data class Voices(val wearerSounding: Boolean, val agentSounding: Boolean, val waiting: Boolean) {
    companion object {
        val NONE = Voices(wearerSounding = false, agentSounding = false, waiting = false)
    }
}

/** The two sinks sampled once a frame; the state changes only when one of the three answers does. */
@Composable
fun rememberVoices(wearer: SpeechEdgeLog?, agent: SpeechEdgeLog?): State<Voices> {
    val state = remember { mutableStateOf(Voices.NONE) }
    LaunchedEffect(wearer, agent) {
        var wasSounding = false
        var echo = false  // the burst under way began while the agent's voice was in the room
        var waitingSince = 0L  // uptime when the wearer's last burst of their own ended, 0 while not waiting
        while (true) {
            withFrameNanos { }
            val now = SystemClock.uptimeMillis()
            val w = wearer?.sounding == true
            val a = agent?.sounding == true
            // lastLoud is a wall clock time (SpeechEdgeLog stamps its log lines for the record), so it is compared on
            // that clock: against the uptime clock the difference was always negative, every burst at the microphone
            // read as the agent's echo once the agent had sounded, and the wearer's bars never showed (2026-11-08).
            val agentJustSpoke = agent != null && (a || System.currentTimeMillis() - agent.lastLoud < ECHO_MS)
            if (w && !wasSounding) {
                echo = agentJustSpoke
                if (!echo) waitingSince = 0L
            }
            if (!w && wasSounding && !echo) waitingSince = now
            wasSounding = w
            if (a || (waitingSince != 0L && now - waitingSince >= WAIT_MAX_MS)) waitingSince = 0L
            val next = Voices(wearerSounding = w && !echo, agentSounding = a, waiting = waitingSince != 0L)
            if (next != state.value) state.value = next
        }
    }
    return state
}

private const val WAIT_MAX_MS = 8000L
private const val ECHO_MS = 300L
