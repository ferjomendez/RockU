package com.example.correacam

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var statusText: TextView
    private lateinit var toggleButton: Button

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            if (hasPermission(Manifest.permission.CAMERA)) {
                startCameraService()
            } else {
                statusText.text = "Se necesita el permiso de camara"
            }
        }

    // Refresca la pantalla cada segundo mientras la app es visible
    private val ticker = object : Runnable {
        override fun run() {
            refreshUi()
            statusText.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        statusText = findViewById(R.id.statusText)
        toggleButton = findViewById(R.id.toggleButton)
        toggleButton.setOnClickListener {
            if (CameraServerService.running) stopCameraService() else requestAndStart()
        }
    }

    override fun onResume() {
        super.onResume()
        ticker.run()
    }

    override fun onPause() {
        statusText.removeCallbacks(ticker)
        super.onPause()
    }

    private fun refreshUi() {
        if (CameraServerService.running) {
            val ip = Net.localIp() ?: "sin red WiFi"
            val port = CameraServerService.PORT
            val fps = String.format(Locale.US, "%.1f", FrameStore.fps)
            statusText.text = "Servidor activo\n\n" +
                "http://$ip:$port/\n" +
                "http://$ip:$port/capture\n" +
                "http://$ip:$port/status\n\n" +
                "${FrameStore.width}x${FrameStore.height}  |  $fps fps\n" +
                "3A: ${if (CameraState.locked) "BLOQUEADO" else "automatico"}" +
                if (CameraState.manualExposureNs != null) "  |  exposicion manual" else ""
            toggleButton.text = "Detener"
        } else {
            statusText.text = "Servidor detenido"
            toggleButton.text = "Iniciar"
        }
    }

    private fun hasPermission(permission: String) =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED

    private fun requestAndStart() {
        val needed = mutableListOf(Manifest.permission.CAMERA)
        if (Build.VERSION.SDK_INT >= 33) needed.add(Manifest.permission.POST_NOTIFICATIONS)
        val missing = needed.filter { !hasPermission(it) }
        if (missing.isEmpty()) startCameraService() else permissionLauncher.launch(missing.toTypedArray())
    }

    private fun startCameraService() {
        ContextCompat.startForegroundService(this, Intent(this, CameraServerService::class.java))
    }

    private fun stopCameraService() {
        stopService(Intent(this, CameraServerService::class.java))
    }
}
