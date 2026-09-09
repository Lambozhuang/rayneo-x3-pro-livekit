package io.livekit.android.example.voiceassistant.viewmodel

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.navigation.toRoute
import io.livekit.android.LiveKit
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantRoute
import io.livekit.android.room.participant.VideoTrackPublishDefaults
import io.livekit.android.room.track.LocalVideoTrackOptions
import io.livekit.android.room.track.VideoCaptureParameter
import io.livekit.android.room.track.VideoEncoding
import io.livekit.android.token.TokenSource
import java.net.URI
import livekit.org.webrtc.RtpParameters

/**
 * This ViewModel handles holding onto the Room object, so that it is
 * maintained across configuration changes, such as rotation.
 */
class VoiceAssistantViewModel(application: Application, savedStateHandle: SavedStateHandle) : AndroidViewModel(application) {

    val room = LiveKit.create(application).apply {
        // The camera has exactly one consumer, the agent, and it samples one
        // frame a second to show a vision model. The SDK's defaults are tuned
        // for a video call: 30 fps, three simulcast layers, and "keep the
        // frame rate, drop the resolution" when the encoder or the uplink is
        // short. On the glasses that produced 360x640 frames at the agent,
        // too soft to count the studs on a brick. So: one layer, resolution
        // held, frame rate cut to what the encoder can sustain at full size.
        videoTrackCaptureDefaults = LocalVideoTrackOptions(
            captureParams = VideoCaptureParameter(1280, 720, 15),
        )
        videoTrackPublishDefaults = VideoTrackPublishDefaults(
            videoEncoding = VideoEncoding(maxBitrate = 2_500_000, maxFps = 15),
            simulcast = false,
            degradationPreference = RtpParameters.DegradationPreference.MAINTAIN_RESOLUTION,
        )
    }

    val tokenSource: TokenSource

    init {
        val route = savedStateHandle.toRoute<VoiceAssistantRoute>()

        // One token path on purpose. The upstream starter falls back to LiveKit's
        // public homepage agent when its Cloud config is missing, which would
        // quietly put the wearer in a room with someone else's agent instead of
        // failing. A connection error is far easier to diagnose on a headset.
        Log.i(TAG, "fetching token from ${route.tokenEndpoint}")
        // The credential rides in the Authorization header, which is where the
        // standard endpoint spec puts it and what backend/api reads. Never in
        // the URL: query strings end up in access logs.
        val headers = if (route.credential.isBlank()) emptyMap()
        else mapOf("Authorization" to "Bearer ${route.credential}")
        tokenSource = TokenSource.fromEndpoint(url = URI(route.tokenEndpoint).toURL(), headers = headers)
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