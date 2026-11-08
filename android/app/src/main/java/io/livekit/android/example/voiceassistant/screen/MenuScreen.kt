package io.livekit.android.example.voiceassistant.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.livekit.android.example.voiceassistant.Lab
import io.livekit.android.example.voiceassistant.ui.Eyes
import io.livekit.android.example.voiceassistant.ui.theme.Blue500
import kotlinx.serialization.Serializable

@Serializable
object MenuRoute

/**
 * Which of the three ways to run a call the wearer wants; the app opens here. A swipe on the temple moves the pick, a tap
 * enters it, a double tap leaves the app (MainActivity). Debug lists the builds and Games the user study's games, two
 * lists kept apart (Tasks.Kind), so the sheets stay a plain list of builds. Process-wide like Tasks, since the screen is
 * composed once per eye and the touchpad is handled outside the Compose tree.
 */
object Menu {
    enum class Entry(val title: String, val what: String) {
        LAB("Lab", "the lab console starts and ends the tasks"),
        DEBUG("Debug", "pick a build here and start it"),
        GAMES("Games", "pick a trial of the user study's games"),
    }

    var selected by mutableIntStateOf(0)
        private set

    /** Opens on the entry whose list holds the task the launch named (`-e task a-1` opens on Games). */
    fun openOn(entry: Entry) {
        selected = entry.ordinal
    }

    val pick: Entry get() = Entry.entries[selected]

    fun move(delta: Int) {
        selected = Math.floorMod(selected + delta, Entry.entries.size)
    }
}

/** The entries, the pick bright on blue, with the console's address under `Lab` so a wrong launch shows here. */
@Composable
fun MenuScreen() {
    val selected = Menu.selected
    val console = Lab.console

    Eyes {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top,
            modifier = Modifier.fillMaxSize()
        ) {
            Text("RayNeo assistant", color = MaterialTheme.colorScheme.onBackground, fontSize = 20.sp)
            Spacer(Modifier.size(16.dp))
            Menu.Entry.entries.forEachIndexed { i, e ->
                val on = i == selected
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 2.dp)
                        .background(if (on) Blue500 else Color.Transparent, RoundedCornerShape(8.dp))
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    Text(e.title, color = if (on) Color.White else Color(0xFFBDBDBD), fontSize = 20.sp,
                         fontWeight = if (on) FontWeight.Bold else FontWeight.Normal)
                    Text(e.what, color = if (on) Color.White else Color(0xFF9E9E9E), fontSize = 15.sp)
                    if (e == Menu.Entry.LAB) {
                        Text(console ?: "no console address: launch with glasses.ps1 -Lab <ip>",
                             color = if (console == null) Color(0xFFFF8A80) else if (on) Color.White else Color(0xFF9E9E9E), fontSize = 15.sp)
                    }
                }
            }
            Spacer(Modifier.weight(1f))
            Text("swipe: choose · tap: enter · double tap: leave", color = Color(0xFF9E9E9E), fontSize = 14.sp)
        }
    }
}
