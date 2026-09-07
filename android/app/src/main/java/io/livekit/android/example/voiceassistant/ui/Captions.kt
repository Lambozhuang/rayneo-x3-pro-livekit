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

/**
 * The agent's last few sentences, newest at the bottom and brightest. Only the
 * agent's side: the wearer knows what they just said, and echoing it back took
 * half the panel in the starter's chat log. Transcripts stream in, so the last
 * line grows word by word while the agent speaks; [ReceivedMessage.id] is
 * stable across those updates, which is what lets the list stay put.
 *
 * Not a LazyColumn. There is no scrolling on the glasses and never more than
 * [MAX_LINES] items, and a plain Column composes identically in both eyes.
 */
@Composable
fun Captions(messages: List<ReceivedMessage>, modifier: Modifier = Modifier) {
    val recent = messages.takeLast(MAX_LINES)
    Column(
        verticalArrangement = Arrangement.spacedBy(10.dp),
        horizontalAlignment = Alignment.Start,
        modifier = modifier
    ) {
        recent.forEachIndexed { i, message ->
            val newest = i == recent.lastIndex
            Text(
                text = message.message,
                color = if (newest) Color(0xFFEEEEEE) else Color(0xFF8A8A8A),
                fontSize = if (newest) 22.sp else 18.sp,
                lineHeight = if (newest) 30.sp else 24.sp,
                maxLines = if (newest) 4 else 2,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

private const val MAX_LINES = 2
