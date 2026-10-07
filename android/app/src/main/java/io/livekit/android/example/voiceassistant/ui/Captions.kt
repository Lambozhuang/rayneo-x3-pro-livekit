package io.livekit.android.example.voiceassistant.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.compose.types.ReceivedMessage
import io.livekit.android.room.participant.Participant

/**
 * The conversation, newest at the bottom and brightest, the wearer's turns in
 * green. The wearer's lines are not what they said but what the model heard:
 * the transcript comes back from the model, late and sometimes wrong, and on a
 * network-quality test bed that is the point, a dropped word shows up here as
 * a dropped word. The agent's lines stream in and grow word by word;
 * [ReceivedMessage.id] is stable across those updates, which is what lets the
 * list stay put.
 *
 * A full-duplex model (GPT-Live) does not stop when the wearer talks over it,
 * so its transcript keeps growing in the same segment after the wearer's
 * line has arrived, and the words it said after the interruption would land
 * in the bubble above it. [split] cuts an agent segment where a wearer line
 * came in, and shows what followed as a new bubble below, in the order it
 * was actually heard. Transcript deltas also arrive with a leading space; the
 * text is trimmed so every line starts at the margin.
 *
 * Every line is shown whole. Short, the column sits at the bottom of its
 * space; longer than the space, it scrolls and stays pinned to the newest
 * line as it grows (there is no pointer, so no one scrolls back). The scroll
 * position is per eye (Eyes composes this twice); both copies follow the same
 * bottom, so they agree. At most [MAX_ITEMS] lines are kept.
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
    val scroll = rememberScrollState()
    // Whenever the content grows (a new line, a longer one), go to the bottom.
    LaunchedEffect(scroll) {
        snapshotFlow { scroll.maxValue }.collect { scroll.scrollTo(it) }
    }
    Box(modifier = modifier) {
        Column(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .fillMaxWidth()
                .verticalScroll(scroll, enabled = false),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
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
                )
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

private const val MAX_ITEMS = 40
