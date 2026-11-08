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
 * What the wearer can pick before a call, from the backend's `GET /tasks` (the numbered task files the agent has), in
 * two lists the menu keeps apart (Menu): the builds, the sheets of tasks/sheet.html (numbers under 100), and the games
 * of the user study, game A's trials (`a-<k>`), every sheet as a trial of game B (the sheet with `game` "B", which
 * rides in the token request so the agent plays the game on it), and free play. The connect screen lists the kind
 * entered from the menu; a swipe on the temple moves the pick (MainActivity), a tap starts the call with it, and the
 * token request carries it (`/getToken?task=<name>[&game=B]`) to the agent. The last pick of each kind is kept across
 * launches; `-e task <name>` on an adb launch sets it in whichever list has the name. In lab mode the console names a
 * task by its number, looked up in the builds (Lab).
 *
 * Process-wide state on purpose: the screen is composed once per eye (Eyes), and
 * the touchpad is handled in the activity, outside the Compose tree.
 */
object Tasks {
    /** One entry: the task file's name, its number, what the list shows, and the game it is played as ("" for a build). */
    data class Task(val name: String, val number: Int, val title: String, val game: String = "", val label: String = "$number.")

    enum class Kind(val heading: String) { BUILDS("Choose a build"), GAMES("Choose a game") }

    /** Which list the connect screen shows, set by the menu's entry (MainActivity). */
    var kind by mutableStateOf(Kind.BUILDS)

    private var builds by mutableStateOf<List<Task>>(emptyList())
    private var games by mutableStateOf<List<Task>>(emptyList())
    private var selectedBuild by mutableIntStateOf(0)
    private var selectedGame by mutableIntStateOf(0)
    /** Why there is no list, for the screen; null while loading or once loaded. */
    var problem by mutableStateOf<String?>(null)
        private set

    /** The list of the kind entered, and the pick in it. */
    val list: List<Task> get() = if (kind == Kind.BUILDS) builds else games
    val selected: Int get() = if (kind == Kind.BUILDS) selectedBuild else selectedGame
    val pick: Task? get() = list.getOrNull(selected)

    /** Whether any list has the task with this name: the launch's `-e task` chooses the menu's entry by it (MainActivity). */
    fun isGame(name: String?) = name != null && games.any { it.name == name } && builds.none { it.name == name }

    /** Fetch the list from the backend next to the token endpoint and sort it into the two kinds. Network on Dispatchers.IO. */
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
        result.onSuccess { all ->
            builds = all.filter { it.number < 100 }
            // Game A's trials, then every sheet as game B, then free play; the superseded placement trials (b-<k>) are left out.
            games = all.filter { it.name.startsWith("a-") }.map { it.copy(label = "A") } +
                builds.map { it.copy(title = it.title, game = "B", label = "B") } +
                all.filter { it.name == "free" }.map { it.copy(label = "·") }
            val saved = prefs(context).getString(KEY, null)
            selectedBuild = builds.indexOfFirst { it.name == saved }.coerceAtLeast(0)
            selectedGame = games.indexOfFirst { it.name == saved && (it.game.isEmpty() || saved !in builds.map { b -> b.name }) }.coerceAtLeast(0)
            if (all.isEmpty()) problem = "the backend lists no tasks"
        }.onFailure {
            Log.w(TAG, "could not load the task list from $url", it)
            problem = "no task list from ${url.host}:${url.port}"
        }
    }

    /** Move the pick of the kind shown by [delta], wrapping around, and remember it. */
    fun move(context: Context, delta: Int) {
        if (list.isEmpty()) return
        if (kind == Kind.BUILDS) selectedBuild = Math.floorMod(selectedBuild + delta, builds.size)
        else selectedGame = Math.floorMod(selectedGame + delta, games.size)
        prefs(context).edit().putString(KEY, list[selected].name).apply()
    }

    /** Picks up `-e task <name>` from an adb-launched intent. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }?.let { prefs(context).edit().putString(KEY, it.trim()).apply() }
    }

    /** The task name the launch or the last pick left, for choosing the menu's entry before the lists are loaded. */
    fun saved(context: Context): String? = prefs(context).getString(KEY, null)

    private fun prefs(context: Context) = context.getSharedPreferences("rayneo", Context.MODE_PRIVATE)

    private const val KEY = "task"
    private const val TAG = "rayneo-tasks"
}
