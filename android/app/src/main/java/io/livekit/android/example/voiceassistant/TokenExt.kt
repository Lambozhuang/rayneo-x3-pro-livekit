package io.livekit.android.example.voiceassistant

import android.content.Context
import android.content.Intent

/**
 * How the glasses reach the backend: where to fetch a join token, and what
 * credential to present. Both live in SharedPreferences, set at runtime
 * instead of compiled in, because the host's address changes with the network
 * and the credential is per deployment.
 *
 * The endpoint is `backend/api` (`POST /getToken`). It has to be an address
 * the glasses can reach over IP: `adb reverse` will forward the token and
 * signaling ports over the cable, but media never negotiates, because the
 * client gathers no loopback ICE candidate to pair with the server's. See the
 * README section on USB.
 *
 * The credential goes out as `Authorization: Bearer <credential>`. What it
 * has to be depends on the backend's AUTH_MODE: nothing for `dev`, the shared
 * string for `static`, a user JWT from an account system for `jwt`.
 *
 * Set both without rebuilding:
 *
 * ```
 * adb shell am start -n com.rayneo.x3pro.assistant/io.livekit.android.example.voiceassistant.MainActivity \
 *   -e token_endpoint http://10.0.0.5:3000/getToken -e credential shared-secret
 * ```
 *
 * or edit the fields on the connect screen when there's no cable. Either way
 * they persist across restarts, and whichever happened last wins.
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
    private const val KEY_CREDENTIAL = "credential"

    fun get(context: Context): String = prefs(context).getString(KEY, DEFAULT) ?: DEFAULT

    fun set(context: Context, value: String) {
        prefs(context).edit().putString(KEY, value.trim()).apply()
    }

    /** Empty means "send no Authorization header", which is what AUTH_MODE=dev wants. */
    fun getCredential(context: Context): String = prefs(context).getString(KEY_CREDENTIAL, "") ?: ""

    fun setCredential(context: Context, value: String) {
        prefs(context).edit().putString(KEY_CREDENTIAL, value.trim()).apply()
    }

    /** Picks up `-e token_endpoint <url>` and `-e credential <string>` from an adb-launched intent. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }?.let { set(context, it) }
        intent?.getStringExtra(KEY_CREDENTIAL)?.let { setCredential(context, it) }
    }

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
