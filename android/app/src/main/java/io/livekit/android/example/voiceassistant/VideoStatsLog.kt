package io.livekit.android.example.voiceassistant

import android.util.Log
import io.livekit.android.room.track.LocalVideoTrack
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlin.coroutines.coroutineContext

/**
 * One log line every few seconds with what the encoder is actually doing:
 * the size it is encoding at, the bitrate it is achieving, and what WebRTC
 * says is holding it back. This is the only way to tell "the network would not
 * take more" from "the encoder could not make more" from "the camera gave it
 * mush"; the picture at the far end looks the same in all three cases.
 *
 *   adb logcat -s rayneo-video
 */
object VideoStatsLog {
    private const val TAG = "rayneo-video"
    private const val PERIOD_MS = 5_000L

    suspend fun run(track: LocalVideoTrack) {
        var lastBytes = 0L
        var lastTs = 0.0
        while (coroutineContext.isActive) {
            delay(PERIOD_MS)
            val report = track.getRTCStats() ?: continue
            val out = report.statsMap.values.firstOrNull { it.type == "outbound-rtp" && it.members["kind"] == "video" }
                ?: continue
            val m = out.members
            val bytes = (m["bytesSent"] as? Number)?.toLong() ?: 0L
            val ts = out.timestampUs / 1_000_000.0
            val kbps = if (lastTs > 0 && ts > lastTs) ((bytes - lastBytes) * 8 / (ts - lastTs) / 1000).toInt() else -1
            lastBytes = bytes
            lastTs = ts
            Log.i(
                TAG,
                "encoding ${m["frameWidth"]}x${m["frameHeight"]} @${m["framesPerSecond"]}fps " +
                    "sent=${kbps}kbps target=${(m["targetBitrate"] as? Number)?.toInt()?.div(1000)}kbps " +
                    "limited=${m["qualityLimitationReason"]} encoder=${m["encoderImplementation"]} " +
                    "codec=${report.statsMap[m["codecId"]]?.members?.get("mimeType")}",
            )
        }
    }
}
