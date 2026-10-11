package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.example.voiceassistant.Tasks
import io.livekit.android.example.voiceassistant.TokenEndpoint
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.theme.Blue500
import kotlinx.serialization.Serializable

@Serializable
object ConnectRoute

/**
 * Before a call: which build. The list comes from the backend (Tasks); a swipe
 * on the temple moves the pick, a tap starts the call with it, a double tap
 * leaves the app (MainActivity). Nothing here takes a touch: the wearer cannot
 * see their finger. The backend address and credential come from the adb launch
 * (`glasses.ps1`, TokenEndpoint); there is no keyboard to type them on glasses.
 */
@Composable
fun ConnectScreen() {
    val context = LocalContext.current
    val endpoint = TokenEndpoint.get(context)
    LaunchedEffect(endpoint) { Tasks.load(context, endpoint) }
    val tasks = Tasks.list
    val selected = Tasks.selected
    val problem = Tasks.problem

    Eyes {
        // One 640x480 panel less the safe-area margin: roughly 592x432 dp.
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top,
            modifier = Modifier.fillMaxSize()
        ) {
            Text("Choose a build", color = MaterialTheme.colorScheme.onBackground, fontSize = 20.sp)
            Spacer(Modifier.size(10.dp))
            when {
                problem != null -> Text(
                    "$problem\ntap starts the backend's default build",
                    color = Color(0xFFFF8A80), fontSize = 16.sp, lineHeight = 22.sp,
                )
                tasks.isEmpty() -> Text("loading…", color = Color(0xFF9E9E9E), fontSize = 16.sp)
                else -> TaskList(tasks, selected, Modifier.weight(1f))
            }
            Spacer(Modifier.size(8.dp))
            Text("swipe: choose · tap: start · double tap: leave", color = Color(0xFF9E9E9E), fontSize = 14.sp)
        }
    }
}

/** The pick bright on blue, kept in view; per eye like BuildSteps, both copies follow `selected`. */
@Composable
private fun TaskList(tasks: List<Tasks.Task>, selected: Int, modifier: Modifier = Modifier) {
    val list = rememberLazyListState()
    LaunchedEffect(selected) { list.animateScrollToItem((selected - 2).coerceAtLeast(0)) }
    LazyColumn(state = list, userScrollEnabled = false, modifier = modifier.fillMaxWidth(),
               verticalArrangement = Arrangement.spacedBy(2.dp)) {
        itemsIndexed(tasks) { i, t ->
            val on = i == selected
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(if (on) Blue500 else Color.Transparent, RoundedCornerShape(8.dp))
                    .padding(horizontal = 10.dp, vertical = 3.dp)
            ) {
                Text("${t.number}.", color = if (on) Color.White else Color(0xFF9E9E9E), fontSize = 18.sp,
                     modifier = Modifier.width(36.dp))
                Text(t.title, color = if (on) Color.White else Color(0xFFBDBDBD), fontSize = 18.sp,
                     fontWeight = if (on) FontWeight.Bold else FontWeight.Normal, maxLines = 1,
                     overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
