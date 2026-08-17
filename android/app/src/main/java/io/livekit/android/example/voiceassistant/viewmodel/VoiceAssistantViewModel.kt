package io.livekit.android.example.voiceassistant.viewmodel

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.navigation.toRoute
import io.livekit.android.LiveKit
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantRoute
import io.livekit.android.token.TokenSource
import java.net.URI

/**
 * This ViewModel handles holding onto the Room object, so that it is
 * maintained across configuration changes, such as rotation.
 */
class VoiceAssistantViewModel(application: Application, savedStateHandle: SavedStateHandle) : AndroidViewModel(application) {

    val room = LiveKit.create(application)

    val tokenSource: TokenSource

    init {
        val route = savedStateHandle.toRoute<VoiceAssistantRoute>()

        // One token path on purpose. The upstream starter falls back to LiveKit's
        // public homepage agent when its Cloud config is missing, which would
        // quietly put the wearer in a room with someone else's agent instead of
        // failing. A connection error is far easier to diagnose on a headset.
        Log.i(TAG, "fetching token from ${route.tokenEndpoint}")
        tokenSource = TokenSource.fromEndpoint(URI(route.tokenEndpoint).toURL())
    }

    override fun onCleared() {
        super.onCleared()
        room.disconnect()
        room.release()
    }

    companion object {
        private const val TAG = "VoiceAssistantViewModel"
    }
}