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
 *   start_task   the console names a task by number; it is the build with that number on the task sheet (Tasks), the
 *                same list the debug picker shows, training and experiment alike. The call starts with it, and the
 *                token request carries the run's identity and the console's address for the agent (VoiceAssistantRoute),
 *                which reports the call's record to the console when the call ends (backend/agent/src/qoe.py).
 *   end_task     the call ends. The wearer may also end it first with a double tap, as the contract allows.
 *   clock        answered at once with this clock, for the console's offset.
 *
 * When the call ends, however it ended, `callEnded` reports the run to the console (`POST /task-ended`) with how far the
 * build got, from the step list the agent published. The report waits in SharedPreferences until the console has taken
 * it, so a restart loses nothing, and the socket is opened only once nothing is waiting, as the contract asks. A socket
 * that drops during a task abandons the task and reports nothing: the console resets that run itself. The console's
 * address comes from the launch (`glasses.ps1 -Lab <ip>`, `-e lab_console http://<ip>:8080`), like the token endpoint.
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
        var endedByConsole = false
    }

    /** What MainActivity does when the console speaks: open the call with a run, or leave it. */
    interface Screens {
        fun startCall(run: Run)
        fun endCall()
    }

    /** The console's device server, `http://<host>:8080`, from the launch; null until a launch gave one. */
    var console by mutableStateOf<String?>(null)
        private set
    /** One line for the lab screen: what the connection is doing. */
    var status by mutableStateOf("off")
        private set
    /** The task in progress, from start_task until the report is queued. */
    var run by mutableStateOf<Run?>(null)
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

    /** Picks up `-e lab_console <url>` from an adb-launched intent and remembers it. */
    fun applyIntent(context: Context, intent: Intent?) {
        intent?.getStringExtra(KEY)?.takeIf { it.isNotBlank() }
            ?.let { prefs(context).edit().putString(KEY, it.trim().trimEnd('/')).apply() }
        console = prefs(context).getString(KEY, null)
    }

    /** Lab mode begins: the task list for looking numbers up, any waiting report, then the socket. */
    fun start(context: Context) {
        app = context.applicationContext
        console = prefs(app).getString(KEY, null)
        if (active) return
        active = true
        backoffS = 1
        scope.launch { Tasks.load(app, TokenEndpoint.get(app)) }
        connect()
    }

    /** Lab mode ends: the socket closes and nothing reconnects. A task in progress is abandoned. */
    fun stop() {
        active = false
        main.removeCallbacks(reconnect)
        socket?.close(1000, "leaving lab mode")
        socket = null
        run = null
        status = "off"
    }

    /**
     * The call screen is gone: if a run was on, report it. `stepsDone` is the agent's current step index, which equals
     * `stepsTotal` once the build is finished (guide.py); null when the agent never published a build.
     */
    fun callEnded(room: String?, stepsDone: Int?, stepsTotal: Int) {
        val r = run ?: return
        run = null
        val log = JSONObject()
            .put("room", room ?: JSONObject.NULL)
            .put("task", r.task.name)
            .put("task_number", r.taskNumber)
            .put("steps_total", stepsTotal)
            .put("steps_done", stepsDone ?: JSONObject.NULL)
            .put("completed", stepsTotal > 0 && (stepsDone ?: 0) >= stepsTotal)
            .put("ended_by", if (r.endedByConsole) "console" else "glasses")
        Log.i(TAG, "task ended: sid=${r.sid} run_id=${r.runId} room=$room steps=$stepsDone/$stepsTotal by=${if (r.endedByConsole) "console" else "glasses"}")
        status = "task ${r.taskNumber} ended; reporting"
        enqueue(report(r.sid, r.runId, r.startedAt, System.currentTimeMillis(), log))
    }

    private val reconnect = Runnable { connect() }

    private fun connect() {
        if (!active || socket != null) return
        val base = console
        if (base == null) {
            status = "no console address: launch with glasses.ps1 -Lab <ip>"
            return
        }
        if (pending().length() > 0) {  // the contract: open the socket only when the retry queue is empty
            status = "delivering ${pending().length()} report(s) before connecting"
            flush()
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

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = onMain {
            if (webSocket === socket) lost("closed $code $reason")
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = onMain {
            if (webSocket === socket) lost(t.message ?: t.toString())
        }
    }

    private fun onMain(block: () -> Unit) {
        main.post(block)
    }

    private fun lost(why: String) {
        socket = null
        Log.w(TAG, "connection lost: $why")
        run?.let {  // the contract: a task whose socket dropped is abandoned and not reported
            Log.w(TAG, "task abandoned: sid=${it.sid} run_id=${it.runId}")
            run = null
            screens?.endCall()
        }
        if (!active) return
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
                    r.endedByConsole = true
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
        val number = data.getInt("task_number")
        if (run != null) {
            Log.w(TAG, "start_task while a task is in progress; ignored: $data")
            return
        }
        val task = Tasks.list.firstOrNull { it.number == number }
        if (task == null) {
            // No frame says no to the console; the report says it, so the run does not wait for one that never comes.
            val why = if (Tasks.list.isEmpty()) "the glasses have no task list from the backend" else "no task number $number"
            Log.w(TAG, "start_task task_number=$number: $why; reported at once")
            status = "the console asked for task $number: $why"
            val now = System.currentTimeMillis()
            enqueue(report(sid, runId, now, now, JSONObject().put("error", why).put("task_number", number)))
            return
        }
        val r = Run(sid, runId, data.optString("run_type"), number, data.optString("label"), data.optBoolean("log"),
                    data.optInt("max_duration_s"), task, System.currentTimeMillis())
        run = r
        status = "task $number, ${task.title}"
        Log.i(TAG, "start_task sid=$sid run_id=$runId ${r.runType} task=${task.name} label=${r.label} log=${r.wantsLog} max_s=${r.maxDurationS}")
        screens?.startCall(r)
    }

    /** A report as the contract has it, with the console it is for; `sent_at` is added at each attempt. */
    private fun report(sid: String, runId: Int, startedAt: Long, endedAt: Long, log: JSONObject) = JSONObject()
        .put("console", console)
        .put("body", JSONObject()
            .put("sid", sid).put("run_id", runId).put("role", "target")
            .put("started_at", startedAt).put("ended_at", endedAt).put("log", log))

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

    /** What the console shows for this participant. */
    private const val NAME = "RayNeo X3 Pro"
    private const val KEY = "lab_console"
    private const val KEY_REPORTS = "lab_reports"
    private const val TAG = "rayneo-lab"
}
