package com.example.correacam

/** Ajustes en vivo de la camara y ultimos valores medidos. Se cambian por /config. */
object CameraState {
    @Volatile var locked = false
    @Volatile var exposureNs: Long? = null
    @Volatile var iso: Int? = null
    @Volatile var focusDiopters: Float? = null

    /** Foco fijado al pulsar Bloquear. */
    @Volatile var lockedFocus: Float? = null
    /** Exposicion manual en nanosegundos (null = exposicion automatica). */
    @Volatile var manualExposureNs: Long? = null
    @Volatile var manualIso: Int? = null

    @Volatile var jpegQuality = 85
    @Volatile var maxFps = 15
    /** Giro extra en grados (0, 90, 180, 270) que se suma al del sensor. */
    @Volatile var extraRotation = 0

    fun reset() {
        locked = false
        exposureNs = null
        iso = null
        focusDiopters = null
        lockedFocus = null
        manualExposureNs = null
        manualIso = null
        jpegQuality = 85
        maxFps = 15
        extraRotation = 0
    }
}
