package io.livekit.android.example.voiceassistant.ui

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.Placeable
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.compose.types.ReceivedMessage
import io.livekit.android.room.participant.Participant

/**
 * The conversation, in two parts: the agent's lines ([AgentLines]), and one
 * line for the wearer ([WearerLine]). The wearer's words are not what they
 * said but what the model heard: the transcript comes back from the model,
 * late and sometimes wrong, and on a network-quality test bed that is the
 * point, a dropped word shows up here as a dropped word. The agent's lines
 * stream in and grow word by word; [ReceivedMessage.id] is stable across
 * those updates, which is what lets the list stay put.
 *
 * A full-duplex model (GPT-Live) does not stop when the wearer talks over it,
 * so its transcript keeps growing in the same segment after the wearer's
 * line has arrived, and the words it said after the interruption would land
 * in the bubble above it. [split] cuts an agent segment where a wearer line
 * came in, and shows what followed as a new bubble below, in the order it
 * was actually heard. Transcript deltas also arrive with a leading space; the
 * text is trimmed so every line starts at the margin.
 *
 * Both parts read the same message list and record the cuts the same way
 * ([rememberCuts]), so they agree on where the agent's lines end and the
 * wearer's begin.
 */

/**
 * The agent's lines, newest at the bottom and brightest. Every line is shown
 * whole or not at all: the newest sits at the bottom of the space, the older
 * ones stack up above it as long as they fit, and the first that would be
 * cut is left out, so no line is ever half visible; only the newest line, when
 * it alone is taller than the space, is cut at its top, since its newest words
 * are at its bottom. Nothing scrolls (there is no pointer, so no one scrolls
 * back). At most [MAX_ITEMS] lines are kept.
 *
 * @param wearerIdentity the local participant; everything else is the agent.
 */
@Composable
fun AgentLines(messages: List<ReceivedMessage>, wearerIdentity: Participant.Identity?, modifier: Modifier = Modifier) {
    val recent = split(messages, wearerIdentity, rememberCuts()).filter { !it.wearer }.takeLast(MAX_ITEMS)
    AgentLinesView(recent.map { it.text }, modifier)
}

/** The agent's lines as text, laid out as [AgentLines] lays them out; the mock screen feeds it fixed lines. */
@Composable
fun AgentLinesView(lines: List<String>, modifier: Modifier = Modifier) {
    Layout(
        modifier = modifier.clipToBounds(),
        content = {
            lines.forEachIndexed { i, line ->
                val newest = i == lines.lastIndex
                Text(
                    text = line,
                    color = if (newest) Color(0xFFEEEEEE) else Color(0xFF8A8A8A),
                    fontSize = if (newest) 20.sp else 16.sp,
                    lineHeight = if (newest) 26.sp else 22.sp,
                )
            }
        },
    ) { measurables, constraints ->
        val gap = LINE_GAP.roundToPx()
        val placeables = measurables.map { it.measure(constraints.copy(minHeight = 0, maxHeight = Constraints.Infinity)) }
        // From the newest upward: the newest always, each older one only if it fits whole.
        val shown = mutableListOf<Placeable>()
        var used = 0
        for (p in placeables.asReversed()) {
            val need = p.height + if (shown.isEmpty()) 0 else gap
            if (shown.isNotEmpty() && used + need > constraints.maxHeight) break
            used += need
            shown.add(p)
        }
        layout(constraints.maxWidth, constraints.maxHeight) {
            var y = constraints.maxHeight
            for (p in shown) {
                y -= p.height
                p.placeRelative(0, y)
                y -= gap
            }
        }
    }
}

/** Space between two of the agent's lines. */
private val LINE_GAP = 8.dp

/**
 * What the model heard the wearer say, on one line, in green. Speech
 * recognition breaks a hesitant sentence into several segments, and showing
 * each as its own line scrolled the agent's words away; here the segments
 * that arrive between two agent lines are joined into the one line, and the
 * first segment after the agent has spoken replaces it. Too long for the
 * line, it keeps its tail, since the newest words are there, and starts with
 * an ellipsis; it is empty until the wearer has been heard.
 */
@Composable
fun WearerLine(messages: List<ReceivedMessage>, wearerIdentity: Participant.Identity?, modifier: Modifier = Modifier) {
    val lines = split(messages, wearerIdentity, rememberCuts())
    val text = lines.takeLastWhile { it.wearer }.ifEmpty { lines.dropLastWhile { !it.wearer }.takeLastWhile { it.wearer } }
        .joinToString(" ") { it.text }
    WearerLineView(text, modifier)
}

/** The wearer's line as text, laid out as [WearerLine] lays it out; the mock screen feeds it a fixed line. */
@Composable
fun WearerLineView(text: String, modifier: Modifier = Modifier) {
    Text(
        text = if (text.isEmpty()) " " else text,
        color = Color(0xFF8CE99A),
        fontSize = 20.sp,
        lineHeight = 26.sp,
        maxLines = 1,
        softWrap = false,
        overflow = TextOverflow.StartEllipsis,
        modifier = modifier,
    )
}

/**
 * agent message id -> the wearer message ids that arrived while it was still
 * growing, with the agent text length at that moment. Plain memory, not
 * state: recomposition is driven by the messages already. One per call site,
 * which is one per eye; every copy sees the same messages in the same order,
 * so they record the same cuts.
 */
@Composable
private fun rememberCuts(): MutableMap<String, MutableList<Pair<String, Int>>> = remember { mutableMapOf() }

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
