package io.livekit.android.example.voiceassistant.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import io.livekit.android.compose.state.rememberParticipantTrackReferences
import io.livekit.android.compose.ui.VideoTrackView
import io.livekit.android.room.participant.Participant
import io.livekit.android.room.track.Track

/**
 * The reference model: a video track the agent publishes, named [TRACK_NAME],
 * showing the finished build rendered on the server and slowly turning, the
 * current step's brick in colour (backend/agent/src/render.py). This device
 * only decodes and draws it; which side it shows and what is highlighted are
 * the agent's decisions, made from the conversation. Black in the video is
 * transparent on the see-through display, so the model appears to float.
 *
 * Nothing is drawn until the track is subscribed, so a guide without a model
 * leaves the space empty.
 */
@Composable
fun ModelView(agent: Participant?, modifier: Modifier = Modifier) {
    if (agent == null) return
    val tracks by rememberParticipantTrackReferences(
        sources = listOf(Track.Source.CAMERA),
        passedParticipant = agent,
    )
    val model = tracks.firstOrNull { it.publication?.name == TRACK_NAME } ?: return
    VideoTrackView(trackReference = model, modifier = modifier)
}

private const val TRACK_NAME = "model"
