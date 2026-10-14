package io.livekit.android.example.voiceassistant

import android.util.Log
import livekit.org.webrtc.AudioTrackSink
import java.nio.ByteBuffer
import java.nio.ByteOrder

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
 *   adb logcat -v time -s rayneo-speech
 */
class SpeechEdgeLog(private val who: String, private val threshold: Int, private val hangover: Long = 400) : AudioTrackSink {
    private var loudUntil = 0L  // wall clock when the current burst counts as over, 0 while silent
    private var lastLoud = 0L
    private var peak = 0

    override fun onData(data: ByteBuffer, bitsPerSample: Int, sampleRate: Int, channels: Int, frames: Int, timestamp: Long) {
        if (bitsPerSample != 16) return
        val rms = rms16(data)
        val now = System.currentTimeMillis()
        if (rms >= threshold) {
            if (loudUntil == 0L) Log.i(TAG, "$who sound starts at=$now")
            loudUntil = now + hangover
            lastLoud = now
            if (rms > peak) peak = rms
        } else if (loudUntil != 0L && now > loudUntil) {
            Log.i(TAG, "$who sound stops at=$lastLoud peak=$peak")
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
