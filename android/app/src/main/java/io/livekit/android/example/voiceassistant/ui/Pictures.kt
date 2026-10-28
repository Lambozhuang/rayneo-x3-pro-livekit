package io.livekit.android.example.voiceassistant.ui

import android.graphics.BitmapFactory
import android.util.Log
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import io.livekit.android.room.Room
import io.livekit.android.room.participant.Participant
import io.livekit.android.util.flow
import kotlinx.coroutines.launch

/**
 * What the square beside the step list is to show of the agent's pictures, from the agent's point of view: nothing (the
 * camera), a picture announced and not yet here, a picture that failed to arrive, or a picture.
 */
sealed interface Picture {
    /** The agent names no picture: the square shows the camera. */
    data object None : Picture

    /** The agent has named [name] and its bytes have not all arrived; under a slow network this lasts. */
    data class Waiting(val name: String) : Picture

    /** The read of [name] failed (the stream was cut by a full reconnect, the agent left, the byte count was off); the
     * wearer can ask the agent to send it again. */
    data class Failed(val name: String) : Picture

    data class Shown(val name: String, val image: ImageBitmap) : Picture
}

/**
 * The pictures the agent sends for the square beside the step list, and which of them it wants shown.
 *
 * When the agent decides to show a picture (brain.py `_show`) it first names it in its participant attribute
 * `rayneo.picture`, which rides the signalling channel, and then sends it as a LiveKit byte stream on topic
 * `rayneo.picture`, a PNG of a few KB named like `step-4.png`, over the reliable data channel: under loss it arrives
 * late, not never. So the glasses know a picture is coming before its bytes arrive and show that it is on its way, and
 * show the picture once its bytes are here and its name is the one named. The attribute cleared means the camera again.
 * Nothing is kept: the glasses hold the one picture last received, a new one replaces it, and it is dropped when the
 * attribute clears, so every picture shown is one the agent sent for this occasion. The attribute is re-sent after a
 * reconnect; a stream cut by a full reconnect is not replayed, the read fails, and the square says the picture did not
 * arrive, so the wearer can ask for it again. The glasses know nothing of what a picture shows: the agent decides what
 * to send and when, which is what lets this screen serve a task other than the LEGO build.
 *
 * Four moments are logged under `rayneo-picture` with the wall clock, so a run's record can put them beside the agent's
 * time of sending (deploy/pull_run.py): announced (the attribute named it), opened (the stream's header arrived), shown
 * or failed, and cleared.
 *
 * Hoist the call above Eyes: it registers the stream handler once and holds the picture.
 */
@Composable
fun rememberPicture(room: Room, agent: Participant?): State<Picture> {
    var received by remember { mutableStateOf<Pair<String, ImageBitmap>?>(null) }  // the last picture, by name
    var failed by remember { mutableStateOf<String?>(null) }  // the name whose read last failed
    val scope = rememberCoroutineScope()
    DisposableEffect(room) {
        room.registerByteStreamHandler(PICTURE_TOPIC) { reader, _ ->
            scope.launch {
                val name = reader.info.name ?: ""  // the agent names every picture; a nameless one can never be picked
                Log.i(PICTURE_TAG, "opened name=$name size=${reader.info.totalSize} at=${System.currentTimeMillis()}")
                // A read fails when the agent leaves mid-stream or the room reconnects fully, since what was sent
                // during the outage is not replayed; the SDK throws.
                val chunks = try {
                    reader.readAll()
                } catch (e: Exception) {
                    failed = name
                    Log.w(PICTURE_TAG, "failed name=$name: ${e.message} at=${System.currentTimeMillis()}")
                    return@launch
                }
                val bytes = ByteArray(chunks.sumOf { it.size })
                var at = 0
                for (chunk in chunks) {
                    chunk.copyInto(bytes, at)
                    at += chunk.size
                }
                val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                if (bitmap == null) {
                    failed = name
                    Log.w(PICTURE_TAG, "failed name=$name: ${bytes.size} bytes are not an image at=${System.currentTimeMillis()}")
                } else {
                    received = name to bitmap.asImageBitmap()
                    failed = null
                    Log.i(PICTURE_TAG, "received name=$name bytes=${bytes.size} at=${System.currentTimeMillis()}")
                }
            }
        }
        onDispose { room.unregisterByteStreamHandler(PICTURE_TOPIC) }
    }
    val attributes: Map<String, String> = if (agent == null) emptyMap() else agent::attributes.flow.collectAsState().value
    val name = attributes[PICTURE_ATTRIBUTE]?.takeIf { it.isNotEmpty() }
    val held = received
    val picture: Picture = when {
        name == null -> Picture.None
        held != null && held.first == name -> Picture.Shown(name, held.second)
        failed == name -> Picture.Failed(name)
        else -> Picture.Waiting(name)
    }
    // One line per change of state; the first state, nothing named, is not a change.
    var logged by remember { mutableStateOf("") }
    val key = when (picture) {
        Picture.None -> "cleared"
        is Picture.Waiting -> "announced name=${picture.name}"
        is Picture.Failed -> "not shown name=${picture.name}"
        is Picture.Shown -> "shown name=${picture.name}"
    }
    LaunchedEffect(key) {
        if (key != logged) {
            if (logged.isNotEmpty() || picture != Picture.None) Log.i(PICTURE_TAG, "$key at=${System.currentTimeMillis()}")
            logged = key
        }
        if (picture == Picture.None) {
            received = null  // the agent sends the next picture anew
            failed = null
        }
    }
    return rememberUpdatedState(picture)
}

/** Topic of the byte streams that carry pictures and name of the attribute that names the one to show, as guide.py has them. */
private const val PICTURE_TOPIC = "rayneo.picture"
private const val PICTURE_ATTRIBUTE = "rayneo.picture"

/** Log tag of the picture lines; deploy/pull_run.py collects it into glasses.log. */
private const val PICTURE_TAG = "rayneo-picture"
