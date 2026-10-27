package io.livekit.android.example.voiceassistant

import android.app.Application
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Matrix
import android.opengl.GLES20
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.Camera
import io.livekit.android.LiveKit
import io.livekit.android.LiveKitOverrides
import io.livekit.android.room.track.LocalVideoTrack
import io.livekit.android.room.track.LocalVideoTrackOptions
import io.livekit.android.room.track.VideoCaptureParameter
import io.livekit.android.room.track.video.CameraCapturerUtils
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.ByteBuffer
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import livekit.org.webrtc.CameraXHelper
import livekit.org.webrtc.EglBase
import livekit.org.webrtc.GlRectDrawer
import livekit.org.webrtc.GlUtil
import livekit.org.webrtc.TextureBufferImpl
import livekit.org.webrtc.VideoFrame
import livekit.org.webrtc.VideoFrameDrawer
import livekit.org.webrtc.VideoSink
import livekit.org.webrtc.getCameraX

/**
 * Sets the camera's exposure compensation for the call, and records the scene at several compensations to
 * choose one by.
 *
 * The X3 Pro's main camera takes a compensation of -12 to +12 in steps of 1/6 EV (docs/glasses-spec.md), so -6
 * is one stop darker. Its auto exposure meters the whole frame, and on the lab desk, a dark table under room
 * light, it pushed the gain to its ceiling and washed the studs off a white brick. LiveKit opens the camera
 * through libwebrtc's Camera2Session, which asks for auto exposure at compensation 0 and gives no way in; the
 * SDK's CameraX module (livekit-android-camerax) opens it through CameraX instead and hands out CameraX's
 * [Camera], whose control takes the compensation. So [install] registers that module's camera provider before
 * any camera track exists, and [apply] sets the compensation on a call's camera track when its camera opens.
 *
 *   --ei exposure <n>          `glasses.ps1 -Exposure n`: the compensation index for the calls of this launch;
 *                              a launch without it leaves the camera at 0, as before
 *   --ez exposure_sweep true   `glasses.ps1 -ExposureSweep`: instead of the build picker, open the camera as a
 *                              call does and record it as `-Record` does, [HOLD_S] seconds at each index in
 *                              [SWEEP], into the app's external files dir, `exposure/`, then leave
 *                              (ExposureScreen); the script pulls the recording
 *
 *   adb logcat -v time -s rayneo-camera
 */
@OptIn(ExperimentalCamera2Interop::class)
object Exposure {
    private const val TAG = "rayneo-camera"
    private const val EXTRA = "exposure"
    const val EXTRA_SWEEP = "exposure_sweep"

    /** The indices the sweep records, 0 first so the auto exposure's own choice is the reference. */
    val SWEEP = listOf(0, -2, -4, -6)

    /**
     * How long the camera gets after opening before a compensation is set. The HAL comes up dark and brightens over
     * its first second; a compensation set inside that second is taken against the dark start and the auto exposure
     * never comes up: a call that set -6 as the camera opened ran three times darker than a sweep that set -6 after
     * settling at 0 (gain 1.7 against 9.8, and the HAL's shadow lift switched off). After a settled start the same
     * -6 takes a quarter off the brightness, as the sweep shows.
     */
    private const val AE_START_MS = 2_000L

    /** How long each compensation is held, in seconds; the auto exposure settles on a new one within a second. */
    const val HOLD_S = 5

    /** The compensation index of this launch; null when the launch did not set one. */
    var index: Int? = null
        private set

    private var provider: CameraCapturerUtils.CameraProvider? = null

    fun applyIntent(intent: Intent?) {
        index = if (intent?.hasExtra(EXTRA) == true) intent.getIntExtra(EXTRA, 0) else null
        Log.i(TAG, index?.let { "compensation $it for this launch" } ?: "compensation not set, the camera's own 0")
    }

    /** Makes every camera track from here on open through CameraX; once per process. */
    fun install(activity: ComponentActivity) {
        if (provider != null) return
        val p = CameraXHelper.createCameraProvider(activity)
        if (!p.isSupported(activity)) {
            Log.w(TAG, "CameraX is not supported here; the camera opens through Camera2 and takes no compensation")
            return
        }
        CameraCapturerUtils.registerCameraProvider(p)
        provider = p
        Log.i(TAG, "camera provider: CameraX")
    }

    /**
     * Waits for the track's camera to open and its auto exposure to settle, logs what the camera offers, and sets
     * this launch's compensation on it.
     */
    suspend fun apply(track: LocalVideoTrack) {
        val camera = cameraOf(track) ?: return
        val n = index ?: return
        delay(AE_START_MS)
        set(camera, n)
    }

    private suspend fun cameraOf(track: LocalVideoTrack): Camera? {
        val flow = track.capturer.getCameraX()
        if (flow == null) {
            Log.w(TAG, "the camera track is not on CameraX; no compensation")
            return null
        }
        val camera = flow.filterNotNull().first()
        val s = camera.cameraInfo.exposureState
        Log.i(TAG, "camera open: compensation ${s.exposureCompensationRange.lower}..${s.exposureCompensationRange.upper}" +
            " step ${s.exposureCompensationStep} supported=${s.isExposureCompensationSupported} now ${s.exposureCompensationIndex}")
        return camera
    }

    /** Sets the compensation and waits until the camera has taken it. */
    private suspend fun set(camera: Camera, index: Int) {
        val s = camera.cameraInfo.exposureState
        if (!s.isExposureCompensationSupported) {
            Log.w(TAG, "this camera takes no compensation")
            return
        }
        val n = index.coerceIn(s.exposureCompensationRange.lower, s.exposureCompensationRange.upper)
        if (n != index) Log.w(TAG, "compensation $index is outside the range; using $n")
        val future = camera.cameraControl.setExposureCompensationIndex(n)
        val result = suspendCancellableCoroutine { c ->
            future.addListener({ c.resume(runCatching { future.get() }) }, { it.run() })
        }
        result.onSuccess { Log.i(TAG, "compensation set to $it") }
            .onFailure { Log.e(TAG, "compensation $n refused: $it") }
    }

    /**
     * Opens the camera as a call does (the same size and rate, no room) and records it as a recorded call does
     * (Recording.Video, the same second encoder) into `exposure/video.mp4` with `video.csv`, holding each index of
     * [SWEEP] for [HOLD_S] seconds in order after [AE_START_MS] at the camera's own exposure. `camera.txt` says
     * roughly which second each compensation starts at (the camera opens a few seconds into the file) and the
     * frame's mean brightness each second, read off a GL drawing of the frame as the encoder gets it (the I420
     * conversion, VideoFrame.toJpeg, smears a CameraX frame on this device, so it is not used). `exposure/done`
     * marks the end. [report] gets a line for the screen at each step.
     */
    suspend fun sweep(app: Application, report: (String) -> Unit): File {
        val dir = File(app.getExternalFilesDir(null), "exposure").apply { deleteRecursively(); mkdirs() }
        val eglBase = EglBase.create()
        val room = LiveKit.create(app, overrides = LiveKitOverrides(eglBase = eglBase))
        val track = room.localParticipant.createVideoTrack(
            options = LocalVideoTrackOptions(captureParams = VideoCaptureParameter(1920, 1080, Recording.FPS)),
        )
        val shot = Shot()
        val gl = GlShot(eglBase.eglBaseContext)
        val video = Recording.Video(dir, eglBase.eglBaseContext)
        try {
            track.addRenderer(shot)
            track.startCapture()
            report("opening the camera")
            val camera = withTimeout(10_000) { cameraOf(track) } ?: error("the camera is not on CameraX")
            val notes = File(dir, "camera.txt")
            notes.writeText(
                "compensation ${camera.cameraInfo.exposureState.exposureCompensationRange} step " +
                    "${camera.cameraInfo.exposureState.exposureCompensationStep}, $HOLD_S s per step; " +
                    "each line: the compensation, the second of video.mp4 it starts at, the frame's mean brightness " +
                    "(0-255) each second\n",
            )
            track.addRenderer(video)
            delay(AE_START_MS)  // as a call does before its compensation
            for ((i, n) in SWEEP.withIndex()) {
                set(camera, n)
                val trace = ArrayList<Int>()
                for (sec in 1..HOLD_S) {
                    report("compensation $n: $sec/$HOLD_S s")
                    delay(1_000)
                    trace.add(gl.draw(withTimeout(5_000) { shot.next() }).mean)
                }
                notes.appendText("comp $n from ${i * HOLD_S} s: ${trace.joinToString(" ")}\n")
                Log.i(TAG, "comp $n from ${i * HOLD_S} s: brightness ${trace.joinToString(" ")}")
            }
            set(camera, 0)
        } finally {
            track.removeRenderer(video)
            withContext(Dispatchers.IO) { video.close() }  // it waits for the encoder to drain, seconds at most
            gl.release()
            track.removeRenderer(shot)
            runCatching { track.stopCapture() }
            room.release()
            eglBase.release()
        }
        File(dir, "done").writeText("${SWEEP.size}\n")
        Log.i(TAG, "sweep done: ${SWEEP.size} frames in $dir")
        return dir
    }

    /** A camera frame, retained for [GlShot], with its rotation. */
    private class Taken(val rotation: Int, val frame: VideoFrame)

    /** Hands the next camera frame to whoever asked for one. */
    private class Shot : VideoSink {
        @Volatile private var take: ((Taken) -> Unit)? = null

        suspend fun next(): Taken = suspendCancellableCoroutine { c ->
            take = { c.resume(it) }
            c.invokeOnCancellation { take = null }
        }

        private var described = false

        override fun onFrame(frame: VideoFrame) {
            if (!described) {  // what the capturer hands out, once: the buffer's kind, size and texture transform
                described = true
                val b = frame.buffer
                val matrix = (b as? TextureBufferImpl)?.transformMatrix?.let { m ->
                    FloatArray(9).also { m.getValues(it) }.joinToString(" ") { "%.3f".format(it) }
                }
                Log.i(TAG, "first frame: ${b.javaClass.simpleName} ${b.width}x${b.height} rotation ${frame.rotation}" +
                    (matrix?.let { " transform [$it]" } ?: ""))
            }
            val t = take ?: return
            take = null
            frame.retain()  // for the GL drawing, which releases it
            t(Taken(frame.rotation, frame))
        }
    }

    /** Draws a frame through GL into an off-screen buffer, as Recording draws it into its encoder, and reads it back. */
    private class GlShot(private val shared: EglBase.Context) {
        private val thread = HandlerThread("exposure-gl").apply { start() }
        private val handler = Handler(thread.looper)
        private var egl: EglBase? = null
        private val drawer = GlRectDrawer()
        private val frameDrawer = VideoFrameDrawer()

        /** The frame unrotated as a JPEG, its rotation, and its mean brightness over the whole frame, 0 to 255. */
        class Picture(val jpeg: ByteArray, val rotation: Int, val mean: Int)

        /** The mean of the pixels' brightness, from every 8th pixel each way. */
        private fun meanOf(b: Bitmap): Int {
            var sum = 0L
            var count = 0L
            for (y in 0 until b.height step 8) for (x in 0 until b.width step 8) {
                val p = b.getPixel(x, y)
                sum += ((p shr 16 and 255) * 299 + (p shr 8 and 255) * 587 + (p and 255) * 114) / 1000
                count++
            }
            return (sum / count).toInt()
        }

        /** Draws the frame and reads it back; releases the frame. */
        suspend fun draw(taken: Taken): Picture = suspendCancellableCoroutine { c ->
            val frame = taken.frame
            handler.post {
                try {
                    val w = frame.buffer.width
                    val h = frame.buffer.height
                    val e = egl ?: EglBase.create(shared, EglBase.CONFIG_PIXEL_BUFFER).also {
                        it.createPbufferSurface(w, h)
                        egl = it
                    }
                    e.makeCurrent()
                    frameDrawer.drawFrame(VideoFrame(frame.buffer, 0, frame.timestampNs), drawer, null)
                    val pixels = ByteBuffer.allocateDirect(w * h * 4)
                    GLES20.glReadPixels(0, 0, w, h, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, pixels)
                    GlUtil.checkNoGLES2Error("glReadPixels")
                    val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888).also { pixels.rewind(); it.copyPixelsFromBuffer(pixels) }
                    // GL reads from the bottom row up.
                    val upright = Bitmap.createBitmap(bitmap, 0, 0, w, h, Matrix().apply { postScale(1f, -1f) }, false)
                    val out = ByteArrayOutputStream()
                    upright.compress(Bitmap.CompressFormat.JPEG, 95, out)
                    c.resume(Picture(out.toByteArray(), taken.rotation, meanOf(upright)))
                } catch (e: Exception) {
                    c.resumeWithException(e)
                } finally {
                    frame.release()
                }
            }
        }

        fun release() {
            handler.post {
                drawer.release()
                frameDrawer.release()
                egl?.release()
            }
            thread.quitSafely()
        }
    }
}
