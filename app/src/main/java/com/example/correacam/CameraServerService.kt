package com.example.correacam

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.Matrix
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.TotalCaptureResult
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.util.Size
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.Camera2Interop
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Servicio en primer plano: abre la camara trasera, deja el ultimo frame como JPEG en FrameStore
 * y lo sirve por HTTP (CamServer). Sigue activo con la pantalla apagada.
 */
class CameraServerService : LifecycleService() {

    companion object {
        const val PORT = 8080
        private const val TAG = "CorreaCam"
        private const val CHANNEL_ID = "correacam"
        private const val NOTIF_ID = 1

        @Volatile
        var running = false

        /** Instancia activa, para que el servidor HTTP pueda pedir el bloqueo de 3A. */
        @Volatile
        var instance: CameraServerService? = null
    }

    private var server: CamServer? = null
    private lateinit var analysisExecutor: ExecutorService
    @Volatile private var camera: Camera? = null
    private var lastProcessed = 0L

    override fun onCreate() {
        super.onCreate()
        analysisExecutor = Executors.newSingleThreadExecutor()
        createChannel()

        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= 30) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA)
        } else {
            startForeground(NOTIF_ID, notification)
        }

        FrameStore.reset()
        CameraState.reset()
        try {
            server = CamServer(PORT).also { it.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false) }
        } catch (e: Exception) {
            Log.e(TAG, "No se pudo iniciar el servidor en el puerto $PORT", e)
            stopSelf()
            return
        }
        instance = this
        startCamera()
        running = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        // Si el sistema mata el servicio, no lo relanza solo: la camara exige que la app este visible
        return START_NOT_STICKY
    }

    @Suppress("UnsafeOptInUsageError")
    private fun startCamera() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            try {
                val provider = providerFuture.get()
                val resolution = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            Size(1280, 960),
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                        )
                    )
                    .build()
                val analysisBuilder = ImageAnalysis.Builder()
                    .setResolutionSelector(resolution)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)

                // Guarda los valores reales de exposicion, ISO y foco de cada frame
                Camera2Interop.Extender(analysisBuilder).setSessionCaptureCallback(
                    object : CameraCaptureSession.CaptureCallback() {
                        override fun onCaptureCompleted(
                            session: CameraCaptureSession,
                            request: CaptureRequest,
                            result: TotalCaptureResult
                        ) {
                            CameraState.exposureNs = result.get(CaptureResult.SENSOR_EXPOSURE_TIME)
                            CameraState.iso = result.get(CaptureResult.SENSOR_SENSITIVITY)
                            CameraState.focusDiopters = result.get(CaptureResult.LENS_FOCUS_DISTANCE)
                        }
                    }
                )

                val analysis = analysisBuilder.build()
                analysis.setAnalyzer(analysisExecutor) { image -> processFrame(image) }
                provider.unbindAll()
                camera = provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, analysis)
            } catch (e: Exception) {
                Log.e(TAG, "Error al iniciar la camara", e)
            }
        }, ContextCompat.getMainExecutor(this))
    }

    /** Bloquea (o libera) blancos, foco y exposicion en los valores actuales. */
    fun setLock(lock: Boolean): Boolean {
        if (camera == null) return false
        CameraState.lockedFocus = if (lock) CameraState.focusDiopters else null
        CameraState.locked = lock
        return applyCameraOptions()
    }

    /**
     * Exposicion manual: fija tiempo de exposicion (ms) e ISO.
     * Con exposureMs = null vuelve a exposicion automatica.
     */
    @Suppress("UnsafeOptInUsageError")
    fun setManualExposure(exposureMs: Double?, iso: Int?): Boolean {
        val cam = camera ?: return false
        if (exposureMs == null) {
            CameraState.manualExposureNs = null
            CameraState.manualIso = null
            return applyCameraOptions()
        }
        return try {
            val info = Camera2CameraInfo.from(cam.cameraInfo)
            val expRange = info.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE)
            val isoRange = info.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE)
            var ns = (exposureMs * 1_000_000.0).toLong()
            if (expRange != null) ns = expRange.clamp(ns)
            var sensitivity = iso ?: CameraState.iso ?: 400
            if (isoRange != null) sensitivity = isoRange.clamp(sensitivity)
            CameraState.manualExposureNs = ns
            CameraState.manualIso = sensitivity
            applyCameraOptions()
        } catch (e: Exception) {
            Log.e(TAG, "No se pudo fijar la exposicion manual", e)
            false
        }
    }

    /** Reconstruye las opciones de captura a partir del estado (bloqueo y exposicion manual). */
    @Suppress("UnsafeOptInUsageError")
    private fun applyCameraOptions(): Boolean {
        val cam = camera ?: return false
        return try {
            val control = Camera2CameraControl.from(cam.cameraControl)
            val exposure = CameraState.manualExposureNs
            if (!CameraState.locked && exposure == null) {
                control.clearCaptureRequestOptions()
            } else {
                val options = CaptureRequestOptions.Builder()
                if (exposure != null) {
                    options.setCaptureRequestOption(
                        CaptureRequest.CONTROL_AE_MODE, CaptureRequest.CONTROL_AE_MODE_OFF
                    )
                    options.setCaptureRequestOption(CaptureRequest.SENSOR_EXPOSURE_TIME, exposure)
                    options.setCaptureRequestOption(
                        CaptureRequest.SENSOR_SENSITIVITY, CameraState.manualIso ?: 400
                    )
                }
                if (CameraState.locked) {
                    if (exposure == null) {
                        options.setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK, true)
                    }
                    options.setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, true)
                    val focus = CameraState.lockedFocus
                    if (focus != null) {
                        options.setCaptureRequestOption(
                            CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_OFF
                        )
                        options.setCaptureRequestOption(CaptureRequest.LENS_FOCUS_DISTANCE, focus)
                    }
                }
                control.setCaptureRequestOptions(options.build())
            }
            true
        } catch (e: Exception) {
            Log.e(TAG, "No se pudieron aplicar las opciones de camara", e)
            false
        }
    }

    private fun processFrame(image: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            val minInterval = 1000L / CameraState.maxFps.coerceIn(1, 30)
            if (now - lastProcessed < minInterval) return
            lastProcessed = now

            var bmp = image.toBitmap()
            val rotation = (image.imageInfo.rotationDegrees + CameraState.extraRotation) % 360
            if (rotation != 0) {
                val m = Matrix().apply { postRotate(rotation.toFloat()) }
                bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, m, true)
            }
            val out = ByteArrayOutputStream(128 * 1024)
            bmp.compress(Bitmap.CompressFormat.JPEG, CameraState.jpegQuality, out)
            FrameStore.update(out.toByteArray(), bmp.width, bmp.height)
        } catch (e: Exception) {
            Log.w(TAG, "Frame descartado", e)
        } finally {
            image.close()
        }
    }

    private fun createChannel() {
        val channel = NotificationChannel(CHANNEL_ID, "CorreaCam", NotificationManager.IMPORTANCE_LOW)
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("CorreaCam activa")
            .setContentText("Sirviendo imagen en el puerto $PORT")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()

    override fun onDestroy() {
        running = false
        instance = null
        camera = null
        server?.stop()
        try {
            ProcessCameraProvider.getInstance(this).get().unbindAll()
        } catch (e: Exception) {
            // la camara ya estaba liberada
        }
        analysisExecutor.shutdown()
        super.onDestroy()
    }
}
