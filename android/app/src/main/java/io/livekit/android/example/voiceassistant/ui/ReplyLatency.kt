package io.livekit.android.example.voiceassistant.ui

import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import io.livekit.android.room.Room
import io.livekit.android.room.track.DataPublishReliability

/**
 * How long the wearer waits for an answer, measured where it is felt.
 *
 * The agent cannot measure this: with Gemini's own turn detection the server
 * never learns when the wearer stopped talking, so the SDK's `e2e_latency` is
 * empty or invented. Here both edges come from the SFU's active-speaker
 * updates, which the glasses receive for themselves and for the agent: the
 * wearer's last speech ends, and some time later the agent's audio arrives.
 * That gap is the number a network-quality experiment is about, and it
 * includes everything (Gemini's end-of-turn wait, the model, both hops).
 * Active-speaker updates are coarse, a few hundred milliseconds, so read the
 * trend, not the third decimal.
 *
 * Each measurement goes to logcat under `rayneo-latency` and to the agent as
 * a data packet on [TOPIC], so it shows up in the server log next to the
 * model's own timings (agent.py logs it as `latency:`).
 */
@Composable
fun ReplyLatencyProbe(room: Room, wearerSpeaking: Boolean, agentSpeaking: Boolean) {
    val state = remember(room) { ProbeState() }

    LaunchedEffect(wearerSpeaking) {
        if (wearerSpeaking) {
            state.wearerStoppedAt = null
            state.wearerSpoke = true
        } else if (state.wearerSpoke) {
            state.wearerStoppedAt = SystemClock.elapsedRealtime()
        }
    }

    LaunchedEffect(agentSpeaking) {
        if (!agentSpeaking) return@LaunchedEffect
        val stoppedAt = state.wearerStoppedAt ?: return@LaunchedEffect
        state.wearerStoppedAt = null
        val gapMs = SystemClock.elapsedRealtime() - stoppedAt
        Log.i(TAG, "reply after ${gapMs} ms")
        val payload = """{"reply_ms":$gapMs}"""
        room.localParticipant.publishData(
            payload.toByteArray(),
            DataPublishReliability.RELIABLE,
            TOPIC,
        ).onFailure { Log.w(TAG, "could not send latency to the agent", it) }
    }
}

private class ProbeState {
    var wearerSpoke = false
    var wearerStoppedAt: Long? = null
}

private const val TAG = "rayneo-latency"
private const val TOPIC = "rayneo.latency"
