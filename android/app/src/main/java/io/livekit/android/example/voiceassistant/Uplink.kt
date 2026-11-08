package io.livekit.android.example.voiceassistant

import android.content.Intent
import android.util.Log

/**
 * The camera track's bitrate cap for this launch's calls, in kbit/s: [DEFAULT_KBPS] unless the launch said otherwise
 * (`--ei max_kbps <n>`, `glasses.ps1 -MaxKbps n`); a launch without it is back at the default, like Recording.
 *
 * The cap is the encoder's target, what the glasses send when the network lets them. At home there is no netem box, so
 * it stands in for a link cap when the frames the agent judges at 250, 150 or 100 kbit/s are to be looked at (the
 * study's bandwidth floor). Under a real link cap WebRTC's bandwidth estimate sets the bitrate below the cap, with
 * queueing and loss on top, so a floor found this way is a little optimistic. The value is logged with the call's
 * start and goes into the lab report with it (VoiceAssistantScreen).
 */
object Uplink {
    const val DEFAULT_KBPS = 4000
    const val EXTRA = "max_kbps"

    var maxKbps = DEFAULT_KBPS
        private set

    fun applyIntent(intent: Intent?) {
        maxKbps = if (intent?.hasExtra(EXTRA) == true) intent.getIntExtra(EXTRA, DEFAULT_KBPS).coerceIn(50, 20_000) else DEFAULT_KBPS
        if (maxKbps != DEFAULT_KBPS) Log.i(TAG, "camera track capped at $maxKbps kbit/s for this launch")
    }

    private const val TAG = "rayneo-call"
}
