package io.livekit.android.example.voiceassistant

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.Executors
import livekit.org.webrtc.VideoFrame
import livekit.org.webrtc.VideoSink

/**
 * Debugging aid: saves camera frames as they leave the capturer, before the
 * encoder ever sees them. Paired with the agent's FRAME_DUMP_DIR, this splits
 * "the camera is soft" from "the transport made it soft": the two ends of the
 * pipe, side by side.
 *
 * Armed by a marker file rather than a UI or an intent extra, because there is
 * no UI for it and the intent already carries the endpoint:
 *
 *   adb shell touch /sdcard/Android/data/com.rayneo.x3pro.assistant/files/dump-frames
 *   adb pull  /sdcard/Android/data/com.rayneo.x3pro.assistant/files/frames
 *
 * Frames land as NNN-WxH-rotR.jpg in the app's external files dir (no storage
 * permission needed), one every [everyMs], at most [max] per call, written on
 * a worker thread so the capture thread never blocks.
 */
class FrameDump private constructor(private val dir: File) : VideoSink {
    private val everyMs = 3_000L
    private val max = 10
    private var last = 0L
    private var count = 0
    private val io = Executors.newSingleThreadExecutor()

    override fun onFrame(frame: VideoFrame) {
        val now = System.currentTimeMillis()
        if (count >= max || now - last < everyMs) return
        last = now
        count++
        val n = count
        val rotation = frame.rotation
        val i420 = frame.buffer.toI420() ?: return
        val w = i420.width
        val h = i420.height
        val nv21 = ByteArray(w * h * 3 / 2)
        // Y plane, honouring stride.
        for (row in 0 until h) {
            i420.dataY.position(row * i420.strideY)
            i420.dataY.get(nv21, row * w, w)
        }
        // NV21 is interleaved VU at quarter size.
        val cw = (w + 1) / 2
        val ch = (h + 1) / 2
        var o = w * h
        for (row in 0 until ch) {
            for (col in 0 until cw) {
                nv21[o++] = i420.dataV.get(row * i420.strideV + col)
                nv21[o++] = i420.dataU.get(row * i420.strideU + col)
            }
        }
        i420.release()
        io.execute {
            val file = File(dir, "%03d-%dx%d-rot%d.jpg".format(n, w, h, rotation))
            try {
                FileOutputStream(file).use { out ->
                    YuvImage(nv21, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 92, out)
                }
                Log.i(TAG, "saved ${file.name}")
            } catch (e: Exception) {
                // A debugging aid must never take the call down with it.
                Log.w(TAG, "could not write ${file.name}", e)
            }
        }
    }

    companion object {
        private const val TAG = "rayneo-framedump"

        /** Non-null only when the marker file is present. */
        fun ifArmed(context: Context): FrameDump? {
            val base = context.getExternalFilesDir(null) ?: return null
            if (!File(base, "dump-frames").exists()) return null
            val dir = File(base, "frames").apply { mkdirs() }
            Log.i(TAG, "armed; writing to $dir")
            return FrameDump(dir)
        }
    }
}
