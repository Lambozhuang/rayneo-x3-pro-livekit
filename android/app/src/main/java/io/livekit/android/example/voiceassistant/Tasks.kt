package io.livekit.android.example.voiceassistant

import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.net.HttpURLConnection
import java.net.URI
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * The builds the wearer can pick before a call, from the backend's `GET /tasks`
 * (the numbered task files the agent has). The connect screen lists them; a
 * swipe on the temple moves the pick (MainActivity), a tap starts the call with
 * it, and the token request carries it (`/getToken?task=<name>`) to the agent.
 * The last pick is kept across launches; `-e task <name>` on an adb launch sets it.
 *
 * Process-wide state on purpose: the screen is composed once per eye (Eyes), and
 * the touchpad is handled in the activity, outside the Compose tree.
 */
object Tasks {
    data class Task(val name: String, val number: Int, val title: String)

    var list by mutableStateOf<List<Task>>(emptyList())
        private set
    var selected by mutableIntStateOf(0)
        private set
    /** Why there is no list, for the screen; null while loading or once loaded. */
    var problem by mutableStateOf<String?>(null)
        private set

    val pick: Task? get() = list.getOrNull(selected)

    /** Fetch the list from the backend next to the token endpoint. Network on Dispatchers.IO. */
    suspend fun load(context: Context, tokenEndpoint: String) {
        problem = null
        val url = runCatching { URI(tokenEndpoint).resolve("tasks").toURL() }.getOrNull()
        if (url == null) {
            problem = "no backend address"
            return
        }
        val result = withContext(Dispatchers.IO) {
            runCatching {
                val conn = url.openConnection() as HttpURLConnection
                conn.connectTimeout = 3000
                conn.readTimeout = 3000
                try {
                    val tasks = JSONObject(conn.inputStream.bufferedReader().readText()).getJSONArray("tasks")
                    (0 until tasks.length()).map { i ->
                        val t = tasks.getJSONObject(i)
                        Task(t.getString("name"), t.getInt("number"), t.getString("title"))
                    }
                } finally {
                    conn.disconnect()
                }
            }
        }
        result.onSuccess { tasks ->
            list = tasks
            val saved = prefs(context).getString(KEY, null)
            selected = tasks.indexOfFirst { it.name == saved }.coerceAtLeast(0)
            if (tasks.isEmpty()) problem = "the backend lists no tasks"
        }.onFailure {
            Log.w(TAG, "could not load the task list from $url", it)
            problem = "no task list from ${url.host}:${url.port}"
        }
    }

    /** Move the pick by [delta], wrapping around, and remember it. */
    fun move(context: Context, delta: Int) {
        if (list.isEmpty()) return
        selected = Math.floorMod(selected + delta, list.size)
        prefs(context).edit().putString(KEY, list[selected].name).apply()
    }

    /** Picks up `-e task <name>` from an adb-launched intent. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }?.let { prefs(context).edit().putString(KEY, it.trim()).apply() }
    }

    private fun prefs(context: Context) = context.getSharedPreferences("rayneo", Context.MODE_PRIVATE)

    private const val KEY = "task"
    private const val TAG = "rayneo-tasks"
}
