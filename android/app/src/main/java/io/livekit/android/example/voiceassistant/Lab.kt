package io.livekit.android.example.voiceassistant

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject

/**
 * The glasses as QoE Lab's target device. QoE Lab is the lab's console: it shapes the network, runs the session and
 * decides which task runs when; its contract is qoe-lab/docs/developer-guide.md, Participant Contract. In lab mode
 * (the menu's `Lab`, MainActivity) the glasses hold one WebSocket to the console and do what it says:
 *
 *   start_task   the console names a task by its number within the run's phase, training or experiment, and the
 *                two phases count separately (the contract). The first TRAINING_TASKS builds of the task sheet
 *                (Tasks, the same list the debug picker shows) are the training tasks, in sheet order, and the rest
 *                are the experiment's: training task k is sheet number k, experiment task k is sheet number
 *                k + TRAINING_TASKS, so a subject never builds in the experiment what they practised on. The call
 *                starts with that build, and the
 *                token request carries the run's identity and the console's address for the agent (VoiceAssistantRoute),
 *                which reports the call's record to the console when the call ends (backend/agent/src/qoe.py).
 *                A start_task during a task means the console has reset that run: the call is left without a
 *                report and the new task starts.
 *                In a block of the user study's games (`-e game A|B`, glasses.ps1 -Game; the game is the glasses'
 *                launch parameter, not the console's) the game rides in the token request (`&game=`,
 *                VoiceAssistantRoute). Game B plays on the sheets, named by the numbers the same way (gpt/report.py);
 *                game A has trial files of its own, `a-1` to `a-6` (gpt/pick.py): experiment run k is trial k and
 *                training run k is trial GAME_A_EXPERIMENT_RUNS + k.
 *   end_task     the call ends. The call also ends by itself when the agent publishes `rayneo.call.over`, the build
 *                finished and said so (gpt/agent.py, VoiceAssistantScreen); the wearer's double tap does nothing in
 *                lab mode (MainActivity), so a task cannot end by mistake. A triple tap, the experimenter's and
 *                said nowhere on screen, ends a lab call or leaves the lab screen for the menu.
 *   clock        answered at once with this clock, for the console's offset.
 *
 * When the call ends, however it ended, `callEnded` reports the run to the console (`POST /task-ended`) with how far the
 * build got, from the step list the agent published, and with what the glasses measured during the call (CallLog): the
 * link's statistics, the agent's voice arriving, the pictures arriving and showing, the call's bounds, each event timed
 * in ms from the task's start. The report waits in SharedPreferences until the console has taken
 * it, so a restart loses nothing, and the socket is opened only once nothing is waiting, as the contract asks. A socket
 * that drops during a task abandons the task and reports nothing: the console resets that run itself. The console
 * closes the socket with the reason `replaced` when another device takes the target's one slot; then nothing reconnects,
 * or the two would take the slot from each other, and the lab screen says so. The console's address comes from the
 * launch (`glasses.ps1 -Lab <ip>`, `-e lab_console http://<ip>:8080`), like the token endpoint.
 *
 * The participant reads one sentence on the lab screen, `stage` (LabScreen): to wait, to take the build apart and answer
 * the questionnaire, or to tell the experimenter. The connection's own state is `status`, for the log.
 *
 * Process-wide state like Tasks: the screens read it, MainActivity drives it, and the socket outlives any one screen.
 * Everything here runs on the main thread except the network calls.
 *
 *   adb logcat -v time -s rayneo-lab
 */
object Lab {
    /** One task the console started, from its start_task to the report. */
    class Run(
        val sid: String,
        val runId: Int,
        val runType: String,
        val taskNumber: Int,
        val label: String,
        val wantsLog: Boolean,
        val maxDurationS: Int,
        val task: Tasks.Task,
        val startedAt: Long,
    ) {
        var endedBy = "glasses"  // "console" after its end_task, "finished" after the agent's rayneo.call.over
    }

    /** What the participant reads on the lab screen, one sentence per line, for the stage they are in; `text` is the
     *  build session's wording, [wording] the one for the launch's game (the user's words of 2026-11-09). */
    enum class Stage(val text: String) {
        WAITING("Please wait.\nThe experimenter will start the task."),
        AFTER_TASK("The task is over.\nTake the build apart, then answer the questionnaire.\nPlease wait for the next task."),
        PROBLEM("Something went wrong.\nPlease tell the experimenter.");

        /** The stage's sentences for [game] ("a", "b" or null for a session of builds). */
        fun wording(game: String?): String = when {
            game == null -> text
            this == WAITING -> "Please wait.\nThe experimenter will start the next trial."
            this == AFTER_TASK && game == "a" -> "The trial is over.\nPut the bricks back, then answer the questions on the tablet."
            this == AFTER_TASK -> "The trial is over.\nTake the build apart, then answer the questions on the tablet."
            else -> text
        }
    }

    /** What MainActivity does when the console speaks: open the call with a run (false if it cannot), or leave it. */
    interface Screens {
        fun startCall(run: Run): Boolean
        fun endCall()
    }

    /** The console's device server, `http://<host>:8080`, from the launch; null until a launch gave one. */
    var console by mutableStateOf<String?>(null)
        private set
    /** The game this launch's calls are trials of ("a" or "b"), from `-e game`; null for builds. Read by MainActivity
     *  for every call's route, lab or debug. */
    var game by mutableStateOf<String?>(null)
        private set
    /** One line for the lab screen: what the connection is doing. */
    var status by mutableStateOf("off")
        private set
    /** The task in progress, from start_task until the report is queued. */
    var run by mutableStateOf<Run?>(null)
        private set
    /** The stage the participant is in, for the lab screen. */
    var stage by mutableStateOf(Stage.WAITING)
        private set
    var screens: Screens? = null

    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val http = OkHttpClient()
    private lateinit var app: Context
    private var socket: WebSocket? = null
    private var active = false
    private var backoffS = 1L
    private var flushing: Job? = null

    /** Picks up `-e lab_console <url>` from an adb-launched intent and remembers it; `-e game A|B` follows every launch,
     *  given or not, so a launch without it is a session of builds. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }
            ?.let { prefs(context).edit().putString(KEY, it.trim().trimEnd('/')).apply() }
        console = prefs(context).getString(KEY, null)
        if (intent != null) {
            val g = intent.getStringExtra(KEY_GAME)?.trim()?.lowercase()?.takeIf { it.isNotBlank() }
            prefs(context).edit().apply { if (g != null) putString(KEY_GAME, g) else remove(KEY_GAME) }.apply()
        }
        game = prefs(context).getString(KEY_GAME, null)
    }

    /** Lab mode begins: the task list for looking numbers up, any waiting report, then the socket. */
    fun start(context: Context) {
        app = context.applicationContext
        console = prefs(app).getString(KEY, null)
        if (active) return
        active = true
        backoffS = 1
        connect()
    }

    /** Lab mode ends: the socket closes and nothing reconnects. A task in progress is abandoned. */
    fun stop() {
        active = false
        main.removeCallbacks(reconnect)
        socket?.close(1000, "leaving lab mode")
        socket = null
        run = null
        stage = Stage.WAITING
        status = "off"
    }

    /** The agent ended the task, the build finished and said so (VoiceAssistantScreen): the report says so. */
    fun finished(sid: String, runId: Int) {
        val r = run ?: return
        if (r.sid == sid && r.runId == runId) r.endedBy = "finished"
    }

    /**
     * The lab screen in one of its stages without a console, to look at it on a device or the emulator (glasses.ps1
     * -MockLab): waiting, after (a task), problem. Nothing connects.
     */
    fun mock(state: String) {
        console = "http://192.168.50.177:8080"
        status = "mock: $state"
        stage = when (state) {
            "after" -> Stage.AFTER_TASK
            "problem" -> Stage.PROBLEM
            else -> Stage.WAITING
        }
    }

    /**
     * The call screen of the run `sid`/`runId` is gone: if that run is still on, report it; a run the console has
     * replaced in the meantime is not. `stepsDone` is the agent's current step index, which equals `stepsTotal` once the
     * build is finished (guide.py); null when the agent never published a build. `events` is what the glasses measured
     * during the call (CallLog), each stamped with the glasses' clock, reported as `t_ms` from the task's start. The
     * log goes only when start_task asked for one, as the contract says.
     */
    fun callEnded(sid: String, runId: Int, room: String?, stepsDone: Int?, stepsTotal: Int, events: JSONArray) {
        val r = run ?: return
        if (r.sid != sid || r.runId != runId) return
        run = null
        val log = JSONObject()
            .put("room", room ?: JSONObject.NULL)
            .put("task", r.task.name)
            .put("run_type", r.runType)
            .put("task_number", r.taskNumber)  // the console's number within the phase
            .put("sheet_number", r.task.number)  // the build's number on the task sheet
            .put("steps_total", stepsTotal)
            .put("steps_done", stepsDone ?: JSONObject.NULL)
            .put("completed", stepsTotal > 0 && (stepsDone ?: 0) >= stepsTotal)
            .put("ended_by", r.endedBy)
            .put("events", timed(events, r.startedAt))
        Log.i(TAG, "task ended: sid=${r.sid} run_id=${r.runId} room=$room steps=$stepsDone/$stepsTotal by=${r.endedBy} events=${events.length()}")
        stage = Stage.AFTER_TASK
        status = "task ${r.taskNumber} ended; reporting"
        enqueue(report(r.sid, r.runId, r.startedAt, System.currentTimeMillis(), if (r.wantsLog) log else null))
    }

    /** The events with their `at`, the glasses' wall clock, turned into `t_ms` from `start`, as the contract advises. */
    private fun timed(events: JSONArray, start: Long): JSONArray {
        val out = JSONArray()
        for (i in 0 until events.length()) {
            val e = events.getJSONObject(i)
            val t = JSONObject().put("t_ms", e.getLong("at") - start)
            for (k in e.keys()) if (k != "at") t.put(k, e.get(k))
            out.put(t)
        }
        return out
    }

    private val reconnect = Runnable { connect() }

    private fun connect() {
        if (!active || socket != null) return
        val base = console
        if (base == null) {
            status = "no console address: launch with glasses.ps1 -Lab <ip>"
            stage = Stage.PROBLEM
            return
        }
        if (pending().length() > 0) {  // the contract: open the socket only when the retry queue is empty
            status = "delivering ${pending().length()} report(s) before connecting"
            flush()
            return
        }
        if (!Tasks.loaded) {  // the task list first, so that a start_task can be answered with a call
            status = "loading the task list from ${host(TokenEndpoint.get(app))}"
            scope.launch {
                Tasks.load(app, TokenEndpoint.get(app))
                if (!active) return@launch
                if (Tasks.loaded) {
                    connect()
                } else {
                    status = "${Tasks.problem ?: "no task list"}; retrying in $backoffS s"
                    main.postDelayed(reconnect, backoffS * 1000)
                    backoffS = minOf(backoffS * 2, 30)
                }
            }
            return
        }
        val url = base.replaceFirst("http", "ws") + "/participant?role=target&name=" + URLEncoder.encode(NAME, "UTF-8")
        status = "connecting to ${host(base)}"
        Log.i(TAG, "connecting to $url")
        socket = http.newWebSocket(Request.Builder().url(url).build(), listener)
    }

    private val listener = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) = onMain {
            if (webSocket !== socket) return@onMain
            backoffS = 1
            Log.i(TAG, "connected")
            if (run == null) status = "connected to ${host(console!!)}; waiting for the console"
        }

        override fun onMessage(webSocket: WebSocket, text: String) = onMain {
            if (webSocket === socket) handle(webSocket, text)
        }

        // The console closed its side; closing ours completes the handshake, and onClosed follows.
        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, reason)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = onMain {
            if (webSocket === socket) lost("closed $code $reason", replaced = reason == "replaced")
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = onMain {
            if (webSocket === socket) lost(t.message ?: t.toString())
        }
    }

    private fun onMain(block: () -> Unit) {
        main.post(block)
    }

    private fun lost(why: String, replaced: Boolean = false) {
        socket = null
        Log.w(TAG, "connection lost: $why")
        run?.let {  // the contract: a task whose socket dropped is abandoned and not reported
            Log.w(TAG, "task abandoned: sid=${it.sid} run_id=${it.runId}")
            run = null
            screens?.endCall()
        }
        if (!active) return
        if (replaced) {
            active = false
            status = "another device took the console's target slot; relaunch to take it back"
            stage = Stage.PROBLEM
            return
        }
        status = "no console at ${host(console!!)}: $why; retrying in $backoffS s"
        main.postDelayed(reconnect, backoffS * 1000)
        backoffS = minOf(backoffS * 2, 30)
    }

    private fun handle(ws: WebSocket, text: String) {
        val frame = runCatching { JSONObject(text) }.getOrNull()
        if (frame == null) {
            Log.w(TAG, "not a JSON frame: $text")
            return
        }
        val data = frame.optJSONObject("data") ?: JSONObject()
        when (val type = frame.optString("type")) {
            "clock" -> ws.send(JSONObject().put("type", "clock").put("data", JSONObject()
                .put("t1", data.opt("t1")).put("t2", System.currentTimeMillis())).toString())
            "start_task" -> runCatching { startTask(data) }.onFailure { Log.w(TAG, "bad start_task $data", it) }
            "end_task" -> {
                val r = run
                if (r != null && r.sid == data.optString("sid") && r.runId == data.optInt("run_id")) {
                    Log.i(TAG, "end_task sid=${r.sid} run_id=${r.runId}")
                    r.endedBy = "console"
                    screens?.endCall()
                } else {
                    Log.i(TAG, "end_task for no task in progress: $data")
                }
            }
            else -> Log.i(TAG, "frame ignored: $type")
        }
    }

    private fun startTask(data: JSONObject) {
        val sid = data.getString("sid")
        val runId = data.getInt("run_id")
        val runType = data.optString("run_type")
        val number = data.getInt("task_number")
        run?.let {  // the contract: the console has reset that run; the call goes, unreported, and the new task starts
            Log.w(TAG, "start_task during sid=${it.sid} run_id=${it.runId}: that run is abandoned without a report")
            run = null
        }
        val g = game
        val sheet: Int  // the build's number on the task sheet, or game A's trial number
        val task: Tasks.Task?
        if (g == "a") {
            sheet = if (runType == "training") number + GAME_A_EXPERIMENT_RUNS else number
            val known = sheet in 1..GAME_A_TRIALS && (runType == "training" || number <= GAME_A_EXPERIMENT_RUNS)
            task = if (known) Tasks.named("a-$sheet") else null
            if (task == null) {
                failed(sid, runId, number, "no $runType run $number in game A (trial a-$sheet)")
                return
            }
        } else {
            sheet = if (runType == "training") number else number + TRAINING_TASKS
            task = Tasks.build(sheet)?.takeIf { runType != "training" || number <= TRAINING_TASKS }
            if (task == null) {
                failed(sid, runId, number, if (!Tasks.loaded) "the glasses have no task list from the backend"
                                           else "no $runType task number $number (sheet number $sheet)")
                return
            }
        }
        val r = Run(sid, runId, runType, number, data.optString("label"), data.optBoolean("log"),
                    data.optInt("max_duration_s"), task, System.currentTimeMillis())
        run = r
        stage = Stage.WAITING  // the call screen covers the lab screen while the task runs
        status = "task $number, ${task.title}"
        Log.i(TAG, "start_task sid=$sid run_id=$runId ${r.runType} task_number=$number sheet=$sheet task=${task.name} game=${g ?: "-"} label=${r.label} log=${r.wantsLog} max_s=${r.maxDurationS}")
        if (screens?.startCall(r) != true) {  // not on the lab screen: the run would otherwise stay on for ever
            run = null
            failed(sid, runId, number, "the glasses could not open the call")
        }
    }

    /**
     * A task that cannot start is reported at once as failed, with the reason in one sentence: no frame says no to the
     * console, and the report puts the run back in its queue and shows the operator why, so it does not wait for an end
     * that never comes. The glasses are idle again for the next start_task.
     */
    private fun failed(sid: String, runId: Int, number: Int, why: String) {
        Log.w(TAG, "start_task task_number=$number sid=$sid run_id=$runId failed: $why; reported at once")
        status = "the console started task $number: $why"
        stage = Stage.PROBLEM
        val now = System.currentTimeMillis()
        enqueue(report(sid, runId, now, now, JSONObject().put("error", why).put("task_number", number), outcome = "failed"))
    }

    /**
     * A report as the contract has it, with the console it is for; `sent_at` is added at each attempt. `outcome` is
     * "failed" for a task that could not run; left out, the console takes the run as completed.
     */
    private fun report(sid: String, runId: Int, startedAt: Long, endedAt: Long, log: JSONObject?, outcome: String? = null) = JSONObject()
        .put("console", console)
        .put("body", JSONObject()
            .put("sid", sid).put("run_id", runId).put("role", "target")
            .put("started_at", startedAt).put("ended_at", endedAt)
            .put("outcome", outcome).put("log", log))  // a null value leaves the key out

    private fun enqueue(report: JSONObject) {
        save(pending().put(report))
        flush()
    }

    /** Delivers the waiting reports in order, each until a 2xx (taken) or a 4xx (wrong, dropped), then connects if due. */
    private fun flush() {
        if (flushing?.isActive == true) return
        flushing = scope.launch {
            var wait = 1000L
            while (true) {
                val queue = pending()
                if (queue.length() == 0) break
                if (post(queue.getJSONObject(0))) {
                    queue.remove(0)
                    save(queue)
                    wait = 1000L
                } else {
                    status = "the console did not take a report; again in ${wait / 1000} s"
                    delay(wait)
                    wait = minOf(wait * 2, 30_000)
                }
            }
            if (active && run == null && socket != null) status = "connected to ${host(console!!)}; waiting for the console"
            if (active && socket == null) connect()
        }
    }

    /** True when the report is settled: taken, or refused as malformed, which no retry mends. */
    private suspend fun post(report: JSONObject): Boolean = withContext(Dispatchers.IO) {
        val url = report.getString("console") + "/task-ended"
        val body = JSONObject(report.getJSONObject("body").toString()).put("sent_at", System.currentTimeMillis())
        runCatching {
            val conn = URL(url).openConnection() as HttpURLConnection
            try {
                conn.requestMethod = "POST"
                conn.connectTimeout = 5000
                conn.readTimeout = 10000
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
                val code = conn.responseCode
                val answer = (if (code < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.readText()?.trim()
                when {
                    code in 200..299 -> { Log.i(TAG, "report taken: sid=${body.getString("sid")} run_id=${body.getInt("run_id")} $answer"); true }
                    code in 400..499 -> { Log.e(TAG, "report refused $code, dropped: $answer; body was $body"); true }
                    else -> { Log.w(TAG, "report not taken: $code $answer"); false }
                }
            } finally {
                conn.disconnect()
            }
        }.getOrElse {
            Log.w(TAG, "report not delivered to $url: $it")
            false
        }
    }

    private fun pending(): JSONArray =
        runCatching { JSONArray(prefs(app).getString(KEY_REPORTS, "[]")) }.getOrDefault(JSONArray())

    private fun save(queue: JSONArray) {
        prefs(app).edit().putString(KEY_REPORTS, queue.toString()).apply()
    }

    private fun host(url: String) = url.removePrefix("http://").removePrefix("https://")

    private fun prefs(context: Context) = context.getSharedPreferences("rayneo", Context.MODE_PRIVATE)

    /** How many builds at the top of the task sheet are the training tasks; the experiment's tasks are the rest (decided 2026-11-03). */
    const val TRAINING_TASKS = 3
    /** Game A's trial files per block, and how many the experiment's runs take, the training's runs taking the rest. */
    const val GAME_A_TRIALS = 6
    const val GAME_A_EXPERIMENT_RUNS = 4
    /** What the console shows for this participant. */
    private const val NAME = "RayNeo X3 Pro"
    private const val KEY = "lab_console"
    private const val KEY_GAME = "game"
    private const val KEY_REPORTS = "lab_reports"
    private const val TAG = "rayneo-lab"
}
