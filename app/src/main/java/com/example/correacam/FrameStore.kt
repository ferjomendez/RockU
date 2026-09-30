package com.example.correacam

import android.os.SystemClock

/** Ultimo frame JPEG disponible y estadisticas. Lo escribe la camara, lo lee el servidor HTTP. */
object FrameStore {
    @Volatile var latest: ByteArray? = null
    @Volatile var width = 0
    @Volatile var height = 0
    @Volatile var frames = 0L
    @Volatile var fps = 0.0
    private var lastTs = 0L

    fun update(jpeg: ByteArray, w: Int, h: Int) {
        val now = SystemClock.elapsedRealtime()
        if (lastTs != 0L) {
            val inst = 1000.0 / (now - lastTs).coerceAtLeast(1)
            fps = if (fps == 0.0) inst else fps * 0.9 + inst * 0.1
        }
        lastTs = now
        width = w
        height = h
        frames++
        latest = jpeg
    }

    fun reset() {
        latest = null
        width = 0
        height = 0
        frames = 0
        fps = 0.0
        lastTs = 0
    }
}
