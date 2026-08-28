package io.livekit.android.example.voiceassistant

import android.content.Context
import android.content.Intent

/**
 * Where the glasses fetch their join token: `agent/src/token_server.py`.
 *
 * The host's address changes with the network, so this is stored at runtime
 * instead of compiled in. It has to be an address the glasses can reach over IP:
 * `adb reverse` will forward the token and signaling ports over the cable, but
 * media never negotiates, because the client gathers no loopback ICE candidate
 * to pair with the server's. See the README section on USB.
 *
 * Set it without rebuilding:
 *
 * ```
 * adb shell am start -n com.rayneo.x3pro.assistant/io.livekit.android.example.voiceassistant.MainActivity \
 *   -e token_endpoint http://10.0.0.5:3000/getToken
 * ```
 *
 * or edit the field on the connect screen when there's no cable. Either way it
 * persists across restarts, and whichever happened last wins.
 *
 * Cleartext `http://` and `ws://` only work because `app/src/debug` permits
 * cleartext traffic; a release build would refuse both.
 */
object TokenEndpoint {

    /**
     * A placeholder, not a working default: it only resolves if the ports are
     * forwarded over USB, which is enough to connect but not to hear anything.
     * Override it on every real run.
     */
    const val DEFAULT = "http://127.0.0.1:3000/getToken"

    private const val PREFS = "rayneo"
    private const val KEY = "token_endpoint"

    fun get(context: Context): String = prefs(context).getString(KEY, DEFAULT) ?: DEFAULT

    fun set(context: Context, value: String) {
        prefs(context).edit().putString(KEY, value.trim()).apply()
    }

    /** Picks up `-e token_endpoint <url>` from an adb-launched intent. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }?.let { set(context, it) }
    }

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
