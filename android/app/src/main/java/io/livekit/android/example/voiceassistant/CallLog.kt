package io.livekit.android.example.voiceassistant

import org.json.JSONArray
import org.json.JSONObject

/**
 * What the glasses measure during a call, kept for the report to the lab console (Lab.callEnded): the link as WebRTC
 * sees it here (LinkStatsLog), the agent's voice reaching the decoder (SpeechEdgeLog), the pictures' arrival
 * (Pictures.kt) and the call's own bounds (VoiceAssistantScreen). Each event is `{at, kind, ...fields}` with `at` the
 * glasses' wall clock in ms; Lab turns `at` into `t_ms` from the task's start when it composes the report, as the
 * contract advises. The same measurements go to logcat as before, where deploy/pull_run.py collects them for our own
 * reading; this is the copy that leaves the device.
 *
 * The call screen begins a call's list when it opens and takes it when it goes. Events come from the audio and stats
 * threads as well as the main thread, so the list is guarded.
 */
object CallLog {
    private val events = mutableListOf<JSONObject>()

    /** A new call: whatever a lingering sink of the last call added after its screen went is dropped. */
    @Synchronized
    fun begin() {
        events.clear()
    }

    /** One event at `at` (now unless the measurement itself carries its time); a null field is kept as JSON null. */
    @Synchronized
    fun add(kind: String, fields: Map<String, Any?>, at: Long = System.currentTimeMillis()) {
        val e = JSONObject().put("at", at).put("kind", kind)
        for ((k, v) in fields) e.put(k, v ?: JSONObject.NULL)
        events.add(e)
    }

    /** The call's events in order, and the list is empty again. */
    @Synchronized
    fun take(): JSONArray {
        val out = JSONArray(events)
        events.clear()
        return out
    }
}
