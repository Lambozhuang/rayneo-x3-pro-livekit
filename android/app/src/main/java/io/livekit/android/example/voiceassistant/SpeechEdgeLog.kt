package io.livekit.android.example.voiceassistant

import android.util.Log
import livekit.org.webrtc.AudioTrackSink
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/**
 * Logs the moment an audio track goes from silence to sound and back, with the
 * wall clock, so the glasses' side of a turn can be timed: when the wearer
 * stopped talking into the microphone, and when the agent's voice arrived in
 * the decoder here, the last point before the loudspeaker. The server's record
 * has the same two edges as GPT-Live saw them and as the agent emitted them;
 * the difference between the two logs is the network's share of the wait.
 *
 * The track hands over decoded PCM in 10 ms frames; a frame is sound when its
 * RMS is above `threshold` (full scale is 32767), and silence returns after
 * `hangover` ms without a loud frame. The start edge is the first loud frame,
 * so it is accurate to one frame; the stop edge is logged when the hangover
 * runs out but carries the time of the last loud frame. The peak RMS of the
 * burst is logged with the stop so the threshold can be judged afterwards.
 *
 * With `report` the edges also go to CallLog as `sound` events, for the report to
 * the lab console. The agent's are reported: they are when its voice reached the
 * ear. The wearer's are not: a threshold on the room's microphone is a poor word
 * boundary, and the server's record has the model's own turn detection.
 *
 * `level` is how loud the track is right now, 0 to 1, for the dots on the screen
 * (AgentDots): the frame's RMS against `full`, its square root taken so quiet
 * speech still shows, rising at once and falling over about 150 ms so the bars do
 * not flicker; `sounding` and `lastLoud` drive who has the floor (Voices).
 *
 *   adb logcat -v time -s rayneo-speech
 */
class SpeechEdgeLog(private val who: String, private val threshold: Int, private val hangover: Long = 400,
                    private val report: Boolean = false, private val full: Int = 4000) : AudioTrackSink {
    @Volatile private var loudUntil = 0L  // wall clock when the current burst counts as over, 0 while silent
    /** How loud the track is right now, 0 to 1; read from the main thread while the dots are drawn. */
    @Volatile var level = 0f
        private set
    /** Wall clock of the last loud frame, 0 before the first; read from the main thread to time the hang-up. */
    @Volatile var lastLoud = 0L
        private set
    private var peak = 0

    /** Whether a burst of sound is on right now, hangover included. */
    val sounding: Boolean get() = loudUntil != 0L

    override fun onData(data: ByteBuffer, bitsPerSample: Int, sampleRate: Int, channels: Int, frames: Int, timestamp: Long) {
        if (bitsPerSample != 16) return
        val rms = rms16(data)
        val target = sqrt((rms.toFloat() / full).coerceIn(0f, 1f))
        level = if (target > level) target else level * 0.86f
        val now = System.currentTimeMillis()
        if (rms >= threshold) {
            if (loudUntil == 0L) {
                Log.i(TAG, "$who sound starts at=$now")
                if (report) CallLog.add("sound", mapOf("who" to who, "edge" to "starts"), now)
            }
            loudUntil = now + hangover
            lastLoud = now
            if (rms > peak) peak = rms
        } else if (loudUntil != 0L && now > loudUntil) {
            Log.i(TAG, "$who sound stops at=$lastLoud peak=$peak")
            if (report) CallLog.add("sound", mapOf("who" to who, "edge" to "stops", "peak" to peak), lastLoud)
            loudUntil = 0L
            peak = 0
        }
    }

    private fun rms16(data: ByteBuffer): Int {
        val b = data.duplicate().order(ByteOrder.LITTLE_ENDIAN)
        val n = b.remaining() / 2
        if (n == 0) return 0
        var sum = 0.0
        for (i in 0 until n) {
            val s = b.getShort(i * 2).toDouble()
            sum += s * s
        }
        return Math.sqrt(sum / n).toInt()
    }

    companion object {
        private const val TAG = "rayneo-speech"
    }
}
