package io.livekit.android.example.voiceassistant.ui

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.Placeable
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
 * dropped word shows up here as a dropped word. (The Gemini plugin delivers
 * that transcript once per turn, so the green line appears whole; the agent's
 * streams in and grows word by word.) [ReceivedMessage.id] is stable across
 * those updates, which is what lets the list stay put.
 *
 * The newest turn is never cut short: it is measured first and gets as many
 * lines as the space allows, and older turns are stacked above it only while
 * they still fit. So a long answer pushes the history off the top rather than
 * ending in "...". A plain custom layout, not a LazyColumn: there is no
 * scrolling on the glasses and never more than [MAX_ITEMS] items, and it
 * composes identically in both eyes.
 *
 * @param wearerIdentity the local participant; everything else is the agent.
 */
@Composable
fun Captions(messages: List<ReceivedMessage>, wearerIdentity: Participant.Identity?, modifier: Modifier = Modifier) {
    val recent = messages.takeLast(MAX_ITEMS)
    Layout(
        modifier = modifier,
        content = {
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
                    maxLines = if (newest) Int.MAX_VALUE else 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    ) { measurables, constraints ->
        val spacing = 8.dp.roundToPx()
        val width = constraints.maxWidth
        val placed = arrayOfNulls<Placeable>(measurables.size)
        // Newest first, each with whatever height is left; stop at the first
        // one that does not fit whole.
        var remaining = constraints.maxHeight
        for (i in measurables.indices.reversed()) {
            if (remaining <= 0) break
            val p = measurables[i].measure(
                constraints.copy(minWidth = width, minHeight = 0, maxHeight = remaining)
            )
            if (p.height > remaining) break
            placed[i] = p
            remaining -= p.height + spacing
        }
        layout(width, constraints.maxHeight) {
            var y = constraints.maxHeight
            for (i in placed.indices.reversed()) {
                val p = placed[i] ?: continue
                y -= p.height
                p.placeRelative(0, y)
                y -= spacing
            }
        }
    }
}

private const val MAX_ITEMS = 3
