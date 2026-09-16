package io.livekit.android.example.voiceassistant.ui

import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import io.livekit.android.room.ConnectionState
import io.livekit.android.room.RTCEngine
import io.livekit.android.room.Room
import io.livekit.android.util.flow

/**
 * The connection state the SDK actually acts on, not the one it shows.
 *
 * When the signal WebSocket drops, livekit-android (2.28) first tries a
 * "soft" reconnect: reopen the socket and keep the peer connections. That is
 * the path behind `Reconnecting to signal, attempt n` in the log, and it is
 * what a Wi-Fi outage looks like from the app. During it the engine's own
 * state is [ConnectionState.RESUMING], but `Room` only forwards the *full*
 * reconnect to its public [Room.state]: `onEngineResuming` is a no-op, so
 * [Room.state] stays CONNECTED, and with it the components' `Session.isConnected`.
 * A banner driven by those alone says "Ready" while nothing is getting through.
 *
 * The engine is `internal` to the SDK, so it is reached by reflection on the
 * accessor's mangled name. If a future SDK renames it the app falls back to
 * "no extra information" (this returns CONNECTED forever) rather than crash,
 * and the banner is back to the SDK's own picture.
 */
@Composable
fun rememberEngineState(room: Room): State<ConnectionState> {
    val engine = remember(room) { room.engineOrNull() }
    return if (engine == null) {
        remember { mutableStateOf(ConnectionState.CONNECTED) }
    } else {
        engine::connectionState.flow.collectAsState()
    }
}

private fun Room.engineOrNull(): RTCEngine? = try {
    Room::class.java.methods
        .first { it.name.startsWith("getEngine") && it.parameterCount == 0 }
        .invoke(this) as? RTCEngine
} catch (e: Exception) {
    Log.w("rayneo-phase", "no engine accessor on Room; soft reconnects will not show", e)
    null
}
