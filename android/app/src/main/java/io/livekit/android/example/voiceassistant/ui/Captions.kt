package io.livekit.android.example.voiceassistant.ui

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
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
 * dropped word shows up here as a dropped word. The agent's lines stream in
 * and grow word by word; [ReceivedMessage.id] is stable across those updates,
 * which is what lets the list stay put.
 *
 * A full-duplex model (GPT-Live) does not stop when the wearer talks over it,
 * so its transcript keeps growing in the same segment after the wearer's
 * line has arrived, and the words it said after the interruption would land
 * in the bubble above it. [split] cuts an agent segment where a wearer line
 * came in, and shows what followed as a new bubble below, in the order it
 * was actually heard. Transcript deltas also arrive with a leading space; the
 * text is trimmed so every line starts at the margin.
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
    // agent message id -> the wearer message ids that arrived while it was
    // still growing, with the agent text length at that moment. Plain memory,
    // not state: recomposition is driven by `messages` already.
    val cuts = remember { mutableMapOf<String, MutableList<Pair<String, Int>>>() }
    val recent = split(messages, wearerIdentity, cuts).takeLast(MAX_ITEMS)
    Layout(
        modifier = modifier,
        content = {
            recent.forEachIndexed { i, line ->
                val newest = i == recent.lastIndex
                Text(
                    text = line.text,
                    color = when {
                        line.wearer && newest -> Color(0xFF8CE99A)
                        line.wearer -> Color(0xFF5E9A66)
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

private class Line(val text: String, val wearer: Boolean)

/**
 * The messages as lines to show, in the order they were heard. An agent
 * message that kept growing after a wearer message arrived is cut at the
 * length it had then; the remainder is shown after that wearer message (and
 * cut again at the next one, if any). Empty pieces are dropped.
 */
private fun split(
    messages: List<ReceivedMessage>,
    wearerIdentity: Participant.Identity?,
    cuts: MutableMap<String, MutableList<Pair<String, Int>>>,
): List<Line> {
    val wearerIds = messages.filter { it.fromParticipant?.identity == wearerIdentity }.map { it.id }.toSet()
    // Record, for every agent message, the wearer messages that came after
    // it, the first time each is seen.
    for ((i, m) in messages.withIndex()) {
        if (m.id in wearerIds) continue
        val list = cuts.getOrPut(m.id) { mutableListOf() }
        for (w in messages.drop(i + 1)) {
            if (w.id in wearerIds && list.none { it.first == w.id }) list.add(w.id to m.message.length)
        }
    }
    // Pieces that belong after a given wearer message.
    val after = mutableMapOf<String, MutableList<String>>()
    val out = mutableListOf<Line>()
    for (m in messages) {
        if (m.id in wearerIds) {
            m.message.trimStart().takeIf { it.isNotEmpty() }?.let { out.add(Line(it, true)) }
            after.remove(m.id)?.forEach { out.add(Line(it, false)) }
            continue
        }
        val text = m.message
        val points = (cuts[m.id] ?: emptyList()).map { it.second.coerceAtMost(text.length) }
        var start = 0
        text.substring(0, points.firstOrNull() ?: text.length).trimStart().takeIf { it.isNotEmpty() }?.let { out.add(Line(it, false)) }
        val ids = cuts[m.id] ?: emptyList()
        for ((k, cut) in points.withIndex()) {
            start = cut
            val end = points.getOrNull(k + 1) ?: text.length
            val piece = text.substring(start, end).trimStart()
            if (piece.isNotEmpty()) after.getOrPut(ids[k].first) { mutableListOf() }.add(piece)
        }
    }
    // Wearer messages that were cut points but are outside the list (older
    // than what we were given) would strand their pieces; show those last.
    after.values.flatten().forEach { out.add(Line(it, false)) }
    return out
}

private const val MAX_ITEMS = 3
