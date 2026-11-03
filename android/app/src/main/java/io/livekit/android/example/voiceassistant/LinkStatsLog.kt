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
 * record on the server after the two clocks' offset is known. The same numbers
 * go to CallLog as one `link` event per line, with the stream and the fields
 * named, for the report to the lab console.
 *
 *   adb logcat -v time -s rayneo-link
 */
object LinkStatsLog {
    private const val TAG = "rayneo-link"
    private const val PERIOD_MS = 5_000L

    suspend fun upVideo(track: LocalVideoTrack) = every(track, "up_video") {
        val out = first("outbound-rtp", "video") ?: return@every null
        val back = first("remote-inbound-rtp", "video")
        val m = out.members
        val rtt = ms(back?.members?.get("roundTripTime"))
        val lost = pct(back?.members?.get("fractionLost"))
        val f = linkedMapOf<String, Any?>(
            "width" to m["frameWidth"], "height" to m["frameHeight"], "fps" to m["framesPerSecond"],
            "sent_kbps" to kbps(out, "bytesSent"), "target_kbps" to (m["targetBitrate"] as? Number)?.toInt()?.div(1000),
            "limited" to m["qualityLimitationReason"], "qp" to (m["qpSum"] != null),
            "nack" to delta(out, "nackCount").toInt(), "pli" to delta(out, "pliCount").toInt(),
            "rtt_ms" to rtt, "lost_pct" to lost, "codec" to codec(out), "encoder" to m["encoderImplementation"])
        f to "${f["width"]}x${f["height"]} @${f["fps"]}fps sent=${f["sent_kbps"]}kbps target=${f["target_kbps"]}kbps " +
            "limited=${f["limited"]} qp=${if (f["qp"] == true) "reported" else "none"} nack=${f["nack"]} pli=${f["pli"]} " +
            "rtt=${rtt ?: -1}ms lost=${lostText(lost)} codec=${f["codec"]} encoder=${f["encoder"]}"
    }

    suspend fun upAudio(track: LocalAudioTrack) = every(track, "up_audio") {
        val out = first("outbound-rtp", "audio") ?: return@every null
        val back = first("remote-inbound-rtp", "audio")
        val rtt = ms(back?.members?.get("roundTripTime"))
        val lost = pct(back?.members?.get("fractionLost"))
        val f = linkedMapOf<String, Any?>("sent_kbps" to kbps(out, "bytesSent"), "rtt_ms" to rtt, "lost_pct" to lost, "codec" to codec(out))
        f to "sent=${f["sent_kbps"]}kbps rtt=${rtt ?: -1}ms lost=${lostText(lost)} codec=${f["codec"]}"
    }

    suspend fun downAudio(track: RemoteAudioTrack) = every(track, "down_audio") {
        val inb = first("inbound-rtp", "audio") ?: return@every null
        val m = inb.members
        val held = delta(inb, "jitterBufferDelay")  // seconds, summed over the samples emitted in the period
        val emitted = delta(inb, "jitterBufferEmittedCount")
        val f = linkedMapOf<String, Any?>(
            "received" to delta(inb, "packetsReceived").toInt(), "lost" to delta(inb, "packetsLost").toInt(),
            "jitter_ms" to ms(m["jitter"]), "buffer_ms" to if (emitted > 0) (held * 1000 / emitted).toInt() else null,
            "concealed" to delta(inb, "concealedSamples").toInt(), "samples" to delta(inb, "totalSamplesReceived").toInt(),
            "codec" to codec(inb))
        f to "received=${f["received"]} lost=${f["lost"]} jitter=${f["jitter_ms"] ?: -1}ms buffer=${f["buffer_ms"] ?: -1}ms " +
            "concealed=${f["concealed"]}/${f["samples"]} codec=${f["codec"]}"
    }

    /**
     * Polls the track's stats every PERIOD_MS until the coroutine is cancelled; `line` turns a report into the named
     * fields and their text, which go to CallLog and logcat with the same time.
     */
    private suspend fun every(track: Track, stream: String, line: Report.() -> Pair<Map<String, Any?>, String>?) {
        val report = Report()
        while (coroutineContext.isActive) {
            delay(PERIOD_MS)
            report.stats = track.getRTCStats()?.statsMap?.values ?: continue
            val (fields, text) = report.line() ?: continue
            val at = System.currentTimeMillis()
            Log.i(TAG, "${stream.replace('_', ' ')} $text at=$at")
            CallLog.add("link", mapOf("stream" to stream) + fields, at)
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

    /** Seconds as whole ms; null when the stats have no such number yet. */
    private fun ms(seconds: Any?): Int? = (seconds as? Number)?.toDouble()?.times(1000)?.toInt()

    /** A fraction as a percentage to a tenth; null when the SFU has not reported one. */
    private fun pct(fraction: Any?): Double? = (fraction as? Number)?.toDouble()?.let { Math.round(it * 1000) / 10.0 }

    private fun lostText(pct: Double?): String = pct?.let { "%.1f%%".format(it) } ?: "-"
}
