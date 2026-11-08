package io.livekit.android.example.voiceassistant.viewmodel

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.navigation.toRoute
import io.livekit.android.LiveKit
import io.livekit.android.LiveKitOverrides
import io.livekit.android.example.voiceassistant.Recording
import io.livekit.android.example.voiceassistant.Uplink
import io.livekit.android.example.voiceassistant.screen.VoiceAssistantRoute
import io.livekit.android.room.participant.VideoTrackPublishDefaults
import io.livekit.android.room.track.LocalVideoTrackOptions
import io.livekit.android.room.track.VideoCaptureParameter
import io.livekit.android.room.track.VideoCodec
import io.livekit.android.room.track.VideoEncoding
import io.livekit.android.token.TokenSource
import java.net.URI
import java.net.URLEncoder
import livekit.org.webrtc.HardwareVideoEncoderFactory
import livekit.org.webrtc.EglBase
import livekit.org.webrtc.RtpParameters

/**
 * This ViewModel handles holding onto the Room object, so that it is
 * maintained across configuration changes, such as rotation.
 */
class VoiceAssistantViewModel(application: Application, savedStateHandle: SavedStateHandle) : AndroidViewModel(application) {

    // Our own EGL context and libwebrtc's own encoder factory, instead of the
    // SDK's SimulcastVideoEncoderFactoryWrapper. That wrapper compares the
    // *unrotated* frame width with the *rotated* encoder width, so on this
    // sideways-mounted sensor every 1920x1080 frame failed the check and was
    // crop-and-scaled to 1080x1920 before encoding: a non-uniform resample
    // that threw away half the vertical detail. The plain hardware factory
    // encodes the buffer as captured and lets the rotation ride as metadata.
    private val eglBase: EglBase = EglBase.create()

    /** The context the camera's textures live in, for drawing them into a second encoder (Recording). */
    val eglContext: EglBase.Context get() = eglBase.eglBaseContext

    val room = LiveKit.create(
        application,
        overrides = LiveKitOverrides(
            eglBase = eglBase,
            // Hardware only: DefaultVideoEncoderFactory also builds the software
            // factory, whose constructor needs libwebrtc's native library, and
            // that is not loaded until LiveKit.create runs. We publish H265 on
            // the Qualcomm encoder anyway.
            videoEncoderFactory = HardwareVideoEncoderFactory(
                eglBase.eglBaseContext,
                /* enableIntelVp8Encoder = */ true,
                /* enableH264HighProfile = */ false,
            ),
        ),
    ).apply {
        // The camera has exactly one consumer, the agent, and it samples one
        // frame a second to show a vision model. The SDK's defaults are tuned
        // for a video call: 30 fps, three simulcast layers, and "keep the
        // frame rate, drop the resolution" when the encoder or the uplink is
        // short. On the glasses that produced 360x640 frames at the agent,
        // too soft to count the studs on a brick, and 720p was still too soft
        // for a human. So: one layer, 1080p, resolution held, frame rate cut
        // to what the encoder can sustain at full size. The sensor is mounted
        // sideways, so these arrive at the agent as 1080x1920 portrait. A
        // recorded call (Recording) takes the same frames and keeps this rate.
        videoTrackCaptureDefaults = LocalVideoTrackOptions(
            captureParams = VideoCaptureParameter(1920, 1080, Recording.FPS),
        )
        videoTrackPublishDefaults = VideoTrackPublishDefaults(
            // 4 Mbps unless the launch capped it (Uplink), which stands in for a link cap at home.
            videoEncoding = VideoEncoding(maxBitrate = Uplink.maxKbps * 1000, maxFps = 15),
            // VP8 is libvpx in software on this SoC, and 1080p at 15 fps was
            // still mush: it hit the encoder's limit, not the network's. H265
            // goes through the Qualcomm hardware encoder, as H264 did until
            // 2026-11-03, and reads the same to the vision model at half the
            // bitrate (eval/brain-frame-codec). The agent's libwebrtc decodes
            // it on the server's NVIDIA GPU only (backend/docker-compose.yml);
            // livekit-server relays any codec both ends agree on.
            videoCodec = VideoCodec.H265.codecName,
            simulcast = false,
            degradationPreference = RtpParameters.DegradationPreference.MAINTAIN_RESOLUTION,
        )
    }

    val tokenSource: TokenSource
    /** What this call was opened with; the lab run in it is what the screen reports as ended (Lab). */
    val route: VoiceAssistantRoute = savedStateHandle.toRoute<VoiceAssistantRoute>()

    init {

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
        // The build rides as ?task=, which the api puts into the agent's dispatch metadata; in a lab run the console's
        // run and address ride with it, for the agent to report the call to the console (backend/agent/src/qoe.py).
        var endpoint = route.tokenEndpoint + "?task=" + URLEncoder.encode(route.task, "UTF-8")
        if (route.sid.isNotBlank()) {
            endpoint += "&sid=" + URLEncoder.encode(route.sid, "UTF-8") + "&run_id=" + route.runId +
                "&console=" + URLEncoder.encode(route.console, "UTF-8")
        }
        tokenSource = TokenSource.fromEndpoint(url = URI(endpoint).toURL(), headers = headers)
    }

    override fun onCleared() {
        super.onCleared()
        room.disconnect()
        room.release()
        eglBase.release()
    }

    companion object {
        private const val TAG = "VoiceAssistantViewModel"
    }
}