package io.livekit.android.example.voiceassistant

import android.content.Context
import android.content.Intent
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import livekit.org.webrtc.AudioTrackSink
import livekit.org.webrtc.EglBase
import livekit.org.webrtc.GlRectDrawer
import livekit.org.webrtc.VideoFrame
import livekit.org.webrtc.VideoFrameDrawer
import livekit.org.webrtc.VideoSink
import org.json.JSONObject

/**
 * Records a call on the glasses as material for offline work (re-encoding at other codecs, sizes and
 * bitrates, sending it through an impaired link): the camera as it leaves the capturer, before the
 * call's own encoder, and both voices as PCM. Only when the app is launched with `--ez record true`
 * (`glasses.ps1 -Record`); a launch without it turns recording off again, so a formal run is never
 * recorded by accident.
 *
 * The camera keeps the call's 15 fps (VoiceAssistantViewModel), so the recording holds the same frames the
 * call's own encoder sees and the call runs as it does unrecorded, apart from the second encoder's load.
 * (The first version captured at 30 for the recording's sake; the camera fell to 20–25 after about 100 s
 * and the call's own rate dipped with it, so the extra frames were not worth it.)
 *
 * Per call, under the app's external files dir, `recordings/<room>/`:
 *
 *   video.mp4    H.264 on a second hardware encoder in VBR up to [BITRATE], the sensor's 1920x1080 with
 *                the rotation as the MP4's orientation, as the call's own encoder sends it; on a desk scene
 *                it holds QP 20 at about 15 Mbps, far under the ceiling
 *   video.csv    one line per camera frame: n, its timestamp (ns, the capturer's clock), the wall clock
 *                when it arrived, and whether it was recorded or skipped
 *   mic.wav      the wearer's microphone as the call sends it; agent.wav the agent's voice as decoded here
 *   mic.csv, agent.csv   one line per 10 ms chunk: the wall clock when it arrived and its frames, so gaps
 *                and the time of any sample can be read back
 *   meta.json    the settings, the encoder, the counts, start and end wall clock
 *
 * The wall clocks pair with glasses.log and clock.json (deploy/pull_run.py pulls the directory beside
 * the call's record). A frame is skipped, not queued, when the one before is still being handed to the
 * encoder: a camera texture held here would hold up the camera, and the call's own encoder with it.
 *
 *   adb logcat -v time -s rayneo-record
 */
object Recording {
    /** The call's capture rate, which the recording follows; the second encoder is told the same. */
    const val FPS = 15
    private const val BITRATE = 70_000_000
    private const val TAG = "rayneo-record"
    private const val EXTRA = "record"

    /** Set on every launch from the intent; read when a call starts. */
    var armed = false
        private set

    fun applyIntent(intent: Intent?) {
        armed = intent?.getBooleanExtra(EXTRA, false) ?: false
        Log.i(TAG, if (armed) "armed: the next calls are recorded" else "off")
    }

    private var current: Call? = null

    /** The recording of the call in [room], made on first use; null when not armed. */
    fun forCall(context: Context, room: String, eglContext: EglBase.Context): Call? {
        if (!armed) return null
        current?.let { if (it.room == room) return it else end(it.room) }
        val base = context.getExternalFilesDir(null) ?: return null
        val dir = File(base, "recordings/$room").apply { mkdirs() }
        Log.i(TAG, "recording room=$room into $dir")
        return Call(room, dir, eglContext).also { current = it }
    }

    /** Finish the call's files off the main thread: draining the encoder can take a few seconds. */
    fun end(room: String) {
        val call = current?.takeIf { it.room == room } ?: return
        current = null
        Thread({ call.close() }, "record-close").start()
    }

    class Call(val room: String, private val dir: File, eglContext: EglBase.Context) {
        val video = Video(dir, eglContext)
        val mic = Wav(dir, "mic")
        val agent = Wav(dir, "agent")
        private val startedAt = System.currentTimeMillis()
        private var closed = false

        fun close() {
            if (closed) return
            closed = true
            video.close()
            mic.close()
            agent.close()
            val meta = JSONObject()
                .put("room", room).put("started_at_ms", startedAt).put("ended_at_ms", System.currentTimeMillis())
                .put("camera_fps", FPS).put("video", video.meta()).put("mic", mic.meta()).put("agent", agent.meta())
            File(dir, "meta.json").writeText(meta.toString(1))
            Log.i(TAG, "done room=$room $meta")
        }
    }

    /** The camera to video.mp4 through a second hardware H.264 encoder fed by its input surface. */
    class Video(private val dir: File, private val eglContext: EglBase.Context) : VideoSink {
        private val thread = HandlerThread("record-video").apply { start() }
        private val handler = Handler(thread.looper)
        private val codecThread = HandlerThread("record-codec").apply { start() }
        private val csv = Executors.newSingleThreadExecutor()
        private val csvOut = FileOutputStream(File(dir, "video.csv")).also {
            it.write("n,timestamp_ns,arrived_ms,recorded\n".toByteArray())
        }
        private val busy = AtomicBoolean(false)
        @Volatile private var stopping = false
        private var n = 0L
        private var recorded = 0L
        private var skipped = 0L
        private var written = 0L
        private var codec: MediaCodec? = null
        private var codecName: String? = null
        private var egl: EglBase? = null
        private val drawer = GlRectDrawer()
        private val frameDrawer = VideoFrameDrawer()
        private var muxer: MediaMuxer? = null
        private var track = -1
        private var size = ""
        private var rotation = 0
        private var error: String? = null
        private val drained = CountDownLatch(1)

        override fun onFrame(frame: VideoFrame) {
            val arrived = System.currentTimeMillis()
            n++
            val take = !stopping && error == null && busy.compareAndSet(false, true)
            val line = "$n,${frame.timestampNs},$arrived,${if (take) 1 else 0}\n"
            csv.execute { csvOut.write(line.toByteArray()) }
            if (!take) {
                if (!stopping) skipped++
                return
            }
            recorded++
            frame.retain()
            handler.post {
                try {
                    if (codec == null) start(frame)
                    egl!!.makeCurrent()
                    // As the call's own encoder draws it: the buffer unrotated, the rotation as metadata.
                    val upright = VideoFrame(frame.buffer, 0, frame.timestampNs)
                    frameDrawer.drawFrame(upright, drawer, null)
                    egl!!.swapBuffers(frame.timestampNs)
                } catch (e: Exception) {
                    error = "${e.javaClass.simpleName}: ${e.message}"
                    Log.e(TAG, "video stopped: $error", e)
                } finally {
                    frame.release()
                    busy.set(false)
                }
            }
        }

        /** On the first frame: the encoder at the frame's size, the muxer with its rotation, EGL on the encoder's surface. */
        private fun start(frame: VideoFrame) {
            val w = frame.buffer.width
            val h = frame.buffer.height
            size = "${w}x$h"
            rotation = frame.rotation
            val format = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, w, h).apply {
                setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
                setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_VBR)
                setInteger(MediaFormat.KEY_FRAME_RATE, FPS)
                setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileHigh)
            }
            val c = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
            codecName = c.name
            c.setCallback(object : MediaCodec.Callback() {
                override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {}
                override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
                    val m = MediaMuxer(File(dir, "video.mp4").path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
                    m.setOrientationHint(rotation)
                    track = m.addTrack(format)
                    m.start()
                    muxer = m
                }
                override fun onOutputBufferAvailable(codec: MediaCodec, index: Int, info: MediaCodec.BufferInfo) {
                    val out = codec.getOutputBuffer(index)
                    if (out != null && info.size > 0 && info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0) {
                        muxer?.writeSampleData(track, out, info)
                        written++
                    }
                    codec.releaseOutputBuffer(index, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) drained.countDown()
                }
                override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
                    error = "codec: ${e.diagnosticInfo}"
                    Log.e(TAG, "video stopped: $error", e)
                    drained.countDown()
                }
            }, Handler(codecThread.looper))
            c.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            val surface = c.createInputSurface()
            c.start()
            codec = c
            egl = EglBase.create(eglContext, EglBase.CONFIG_RECORDABLE).apply { createSurface(surface) }
            Log.i(TAG, "video: $codecName ${size} rotation=$rotation at $FPS fps, ${BITRATE / 1_000_000} Mbps")
        }

        fun close() {
            stopping = true
            val done = CountDownLatch(1)
            handler.post {
                try {
                    codec?.signalEndOfInputStream()
                } catch (e: Exception) {
                    Log.w(TAG, "end of stream: ${e.message}")
                    drained.countDown()
                }
                done.countDown()
            }
            done.await(2, TimeUnit.SECONDS)
            if (codec != null && !drained.await(3, TimeUnit.SECONDS)) Log.w(TAG, "video: encoder did not drain in 3 s")
            handler.post {
                runCatching { codec?.stop() }
                runCatching { codec?.release() }
                runCatching { muxer?.stop() }
                runCatching { muxer?.release() }
                runCatching { egl?.release() }
                drawer.release()
                frameDrawer.release()
            }
            thread.quitSafely()
            codecThread.quitSafely()
            csv.execute { csvOut.close() }
            csv.shutdown()
            Log.i(TAG, "video: $n frames from the camera, $recorded recorded, $skipped skipped, $written encoded")
        }

        fun meta(): JSONObject = JSONObject()
            .put("codec", codecName).put("size", size).put("rotation", rotation).put("bitrate", BITRATE)
            .put("camera_frames", n).put("recorded", recorded).put("skipped", skipped).put("encoded", written)
            .put("error", error)
    }

    /** One audio track's PCM to <name>.wav, as it comes, with a line per chunk in <name>.csv. */
    class Wav(dir: File, private val name: String) : AudioTrackSink {
        private val io = Executors.newSingleThreadExecutor()
        private val file = File(dir, "$name.wav")
        private val out = RandomAccessFile(file, "rw").apply { setLength(0); write(ByteArray(44)) }
        private val csvOut = FileOutputStream(File(dir, "$name.csv")).also {
            it.write("arrived_ms,frames,timestamp\n".toByteArray())
        }
        private var format: Triple<Int, Int, Int>? = null  // bits, rate, channels
        private var bytes = 0L
        private var chunks = 0L
        private var mismatched = 0L
        @Volatile private var closed = false

        override fun onData(data: ByteBuffer, bitsPerSample: Int, sampleRate: Int, channels: Int, frames: Int, timestamp: Long) {
            if (closed) return
            val arrived = System.currentTimeMillis()
            val copy = ByteArray(data.remaining()).also { data.duplicate().get(it) }
            val f = Triple(bitsPerSample, sampleRate, channels)
            io.execute {
                if (format == null) {
                    format = f
                    Log.i(TAG, "$name: $bitsPerSample-bit $sampleRate Hz x$channels")
                }
                if (f != format) {
                    mismatched++  // a WAV holds one format; the first one stays
                    return@execute
                }
                out.write(copy)
                bytes += copy.size
                chunks++
                csvOut.write("$arrived,$frames,$timestamp\n".toByteArray())
            }
        }

        fun close() {
            closed = true
            io.execute {
                val (bits, rate, ch) = format ?: Triple(16, 48000, 1)
                val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
                    put("RIFF".toByteArray()); putInt((36 + bytes).toInt()); put("WAVE".toByteArray())
                    put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(ch.toShort()); putInt(rate)
                    putInt(rate * ch * bits / 8); putShort((ch * bits / 8).toShort()); putShort(bits.toShort())
                    put("data".toByteArray()); putInt(bytes.toInt())
                }
                out.seek(0)
                out.write(header.array())
                out.close()
                csvOut.close()
                Log.i(TAG, "$name: $chunks chunks, ${bytes / 1024} KB, $mismatched in another format dropped")
            }
            io.shutdown()
            io.awaitTermination(3, TimeUnit.SECONDS)
        }

        fun meta(): JSONObject = JSONObject()
            .put("format", format?.let { "${it.first}-bit ${it.second} Hz x${it.third}" }).put("chunks", chunks)
            .put("bytes", bytes).put("mismatched", mismatched)
    }
}
