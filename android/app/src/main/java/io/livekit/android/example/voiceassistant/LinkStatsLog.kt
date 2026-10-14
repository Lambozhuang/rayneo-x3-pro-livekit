package io.livekit.android.example.voiceassistant

import android.util.Log
import io.livekit.android.room.track.LocalAudioTrack
import io.livekit.android.room.track.LocalVideoTrack
import io.livekit.android.room.track.RemoteAudioTrack
import io.livekit.android.room.track.Track
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import livekit.org.webrtc.RTCStats
import kotlin.coroutines.coroutineContext

/**
 * One log line every five seconds per media stream with what WebRTC measured on
 * the glasses' own link to the SFU, which is the only place that link can be
 * measured: the agent sits on the same machine as the SFU. Nothing is sent for
 * this; the numbers come from the RTCP reports and ICE checks WebRTC exchanges
 * anyway.
 *
 *   up video    what the encoder is doing (size, fps, bitrate, what holds it back) and
 *               what the SFU reports back about it (round trip, loss, repair requests)
 *   up audio    the same for the microphone, with the codec, so the log shows whether
 *               the audio carries redundancy (audio/red) or plain Opus
 *   down audio  the agent's voice as received: loss, jitter, how long the jitter buffer
 *               held each sample, how many samples were made up to cover gaps
 *
 * Every line carries at=<wall clock ms> so it can be put next to the call's
 * record on the server after the two clocks' offset is known.
 *
 *   adb logcat -v time -s rayneo-link
 */
object LinkStatsLog {
    private const val TAG = "rayneo-link"
    private const val PERIOD_MS = 5_000L

    suspend fun upVideo(track: LocalVideoTrack) = every(track) {
        val out = first("outbound-rtp", "video") ?: return@every null
        val back = first("remote-inbound-rtp", "video")
        val m = out.members
        "up video ${m["frameWidth"]}x${m["frameHeight"]} @${m["framesPerSecond"]}fps " +
            "sent=${kbps(out, "bytesSent")}kbps target=${(m["targetBitrate"] as? Number)?.toInt()?.div(1000)}kbps " +
            "limited=${m["qualityLimitationReason"]} qp=${if (m["qpSum"] != null) "reported" else "none"} " +
            "nack=${delta(out, "nackCount").toInt()} pli=${delta(out, "pliCount").toInt()} " +
            "rtt=${ms(back?.members?.get("roundTripTime"))}ms lost=${pct(back?.members?.get("fractionLost"))} " +
            "codec=${codec(out)} encoder=${m["encoderImplementation"]}"
    }

    suspend fun upAudio(track: LocalAudioTrack) = every(track) {
        val out = first("outbound-rtp", "audio") ?: return@every null
        val back = first("remote-inbound-rtp", "audio")
        "up audio sent=${kbps(out, "bytesSent")}kbps rtt=${ms(back?.members?.get("roundTripTime"))}ms " +
            "lost=${pct(back?.members?.get("fractionLost"))} codec=${codec(out)}"
    }

    suspend fun downAudio(track: RemoteAudioTrack) = every(track) {
        val inb = first("inbound-rtp", "audio") ?: return@every null
        val m = inb.members
        val held = delta(inb, "jitterBufferDelay")  // seconds, summed over the samples emitted in the period
        val emitted = delta(inb, "jitterBufferEmittedCount")
        val buffer = if (emitted > 0) (held * 1000 / emitted).toInt() else -1
        "down audio received=${delta(inb, "packetsReceived").toInt()} lost=${delta(inb, "packetsLost").toInt()} " +
            "jitter=${ms(m["jitter"])}ms buffer=${buffer}ms " +
            "concealed=${delta(inb, "concealedSamples").toInt()}/${delta(inb, "totalSamplesReceived").toInt()} " +
            "codec=${codec(inb)}"
    }

    /** Polls the track's stats every PERIOD_MS until the coroutine is cancelled; `line` turns a report into text. */
    private suspend fun every(track: Track, line: Report.() -> String?) {
        val report = Report()
        while (coroutineContext.isActive) {
            delay(PERIOD_MS)
            report.stats = track.getRTCStats()?.statsMap?.values ?: continue
            val text = report.line() ?: continue
            Log.i(TAG, "$text at=${System.currentTimeMillis()}")
            report.remember()
        }
    }

    /** One stats report with the previous one's counters kept, so a line can give the change over the period. */
    private class Report {
        var stats: Collection<RTCStats> = emptyList()
        private var previous = mutableMapOf<String, Double>()
        private val seen = mutableMapOf<String, Double>()

        fun first(type: String, kind: String): RTCStats? = stats.firstOrNull { it.type == type && it.members["kind"] == kind }

        fun codec(s: RTCStats): Any? = stats.firstOrNull { it.id == s.members["codecId"] }?.members?.get("mimeType")

        /** The counter's change since the last line; the first line gives the whole count so far. */
        fun delta(s: RTCStats, member: String): Double {
            val now = (s.members[member] as? Number)?.toDouble() ?: return 0.0
            val key = s.id + "/" + member
            seen[key] = now
            return now - (previous[key] ?: 0.0)
        }

        /** The stream's bit rate over the period, from the change in a byte counter. */
        fun kbps(s: RTCStats, member: String): Int = (delta(s, member) * 8 / (PERIOD_MS / 1000) / 1000).toInt()

        fun remember() {
            previous = seen.toMutableMap()
            seen.clear()
        }
    }

    private fun ms(seconds: Any?): Int = ((seconds as? Number)?.toDouble()?.times(1000))?.toInt() ?: -1

    private fun pct(fraction: Any?): String = (fraction as? Number)?.toDouble()?.let { "%.1f%%".format(it * 100) } ?: "-"
}
