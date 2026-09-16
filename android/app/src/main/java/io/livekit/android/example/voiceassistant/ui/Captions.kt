package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.compose.types.ReceivedMessage
import io.livekit.android.room.participant.Participant

/**
 * The last few turns of the conversation, newest at the bottom and brightest,
 * the wearer's turns in green. The wearer's lines are not what they said but
 * what the model heard: the transcript comes back from the model, late and
 * sometimes wrong, and on a network-quality test bed that is the point, a
 * dropped word shows up here as a dropped word. Transcripts stream in, so the
 * last line grows word by word while someone speaks; [ReceivedMessage.id] is
 * stable across those updates, which is what lets the list stay put.
 *
 * Not a LazyColumn. There is no scrolling on the glasses and never more than
 * [MAX_LINES] items, and a plain Column composes identically in both eyes.
 *
 * @param wearerIdentity the local participant; everything else is the agent.
 */
@Composable
fun Captions(messages: List<ReceivedMessage>, wearerIdentity: Participant.Identity?, modifier: Modifier = Modifier) {
    val recent = messages.takeLast(MAX_LINES)
    Column(
        verticalArrangement = Arrangement.spacedBy(8.dp),
        horizontalAlignment = Alignment.Start,
        modifier = modifier
    ) {
        recent.forEachIndexed { i, message ->
            val newest = i == recent.lastIndex
            val wearer = message.fromParticipant?.identity == wearerIdentity
            Text(
                text = message.message,
                color = when {
                    wearer && newest -> Color(0xFF8CE99A)
                    wearer -> Color(0xFF5E9A66)
                    newest -> Color(0xFFEEEEEE)
                    else -> Color(0xFF8A8A8A)
                },
                fontSize = if (newest) 22.sp else 18.sp,
                lineHeight = if (newest) 30.sp else 24.sp,
                maxLines = if (newest) 3 else 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

private const val MAX_LINES = 3
