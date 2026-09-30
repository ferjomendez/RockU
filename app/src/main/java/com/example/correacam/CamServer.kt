package com.example.correacam

import android.os.SystemClock
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.util.Locale

/**
 * Servidor HTTP con el mismo contrato que el firmware del ESP32-CAM, mas control de la camara:
 *   GET /capture          -> ultimo frame JPEG
 *   GET /status           -> JSON con resolucion, fps y uptime
 *   GET /config           -> JSON con los ajustes y valores actuales (exposicion, ISO, foco)
 *   GET /config?lock=1    -> bloquea exposicion, balance de blancos y foco (lock=0 los libera)
 *   GET /config?exp=5&iso=800   -> exposicion manual en ms e ISO (exp=auto vuelve a automatico)
 *   GET /config?quality=85&maxfps=15&rot=90   -> calidad JPEG, tope de fps y giro extra
 *   GET /                 -> vista en vivo con botones de control
 */
class CamServer(port: Int) : NanoHTTPD(port) {

    private val startedAt = SystemClock.elapsedRealtime()

    private val indexHtml = """
        <!doctype html>
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>CorreaCam</title></head>
        <body style="margin:0;background:#111;color:#ccc;font-family:sans-serif">
        <div style="padding:8px">
          <button onclick="cfg('lock=1')" style="padding:10px 14px;font-size:16px">Bloquear exposicion / blancos / foco</button>
          <button onclick="cfg('lock=0')" style="padding:10px 14px;font-size:16px">Desbloquear</button>
          <button onclick="cfg('rot=' + ((rot + 90) % 360))" style="padding:10px 14px;font-size:16px">Girar 90</button>
        </div>
        <div style="padding:0 8px 8px">
          Exposicion <input id="expMs" type="number" step="0.5" min="0.1" value="5" style="width:70px;font-size:16px"> ms
          &nbsp; ISO <input id="isoVal" type="number" step="50" min="50" value="800" style="width:80px;font-size:16px">
          <button onclick="manual()" style="padding:10px 14px;font-size:16px">Aplicar manual</button>
          <button onclick="cfg('exp=auto')" style="padding:10px 14px;font-size:16px">Exposicion auto</button>
        </div>
        <div id="t" style="padding:0 8px 8px;font-size:14px">cargando...</div>
        <img id="i" style="display:block;margin:0 auto;max-width:100%;max-height:75vh">
        <script>
        var rot = 0;
        var i = document.getElementById('i');
        function next() {
          i.onload = function () { setTimeout(next, 60); };
          i.onerror = function () { setTimeout(next, 500); };
          i.src = '/capture?' + Date.now();
        }
        next();
        function show(c) {
          rot = c.rot;
          document.getElementById('t').textContent =
            (c.locked ? 'BLOQUEADO' : 'automatico') + (c.manual ? ' + exposicion MANUAL' : '') +
            '  |  exposicion ' + c.exposure_ms + ' ms  |  ISO ' + c.iso +
            '  |  foco ' + c.focus_diopters + ' D  |  calidad ' + c.quality +
            '  |  giro ' + c.rot;
        }
        function manual() {
          var e = document.getElementById('expMs').value;
          var s = document.getElementById('isoVal').value;
          cfg('exp=' + e + '&iso=' + s);
        }
        function cfg(q) {
          fetch('/config?' + q).then(function (r) { return r.json(); }).then(show).catch(function () {});
        }
        setInterval(function () { cfg(''); }, 1000);
        cfg('');
        </script></body></html>
    """.trimIndent()

    override fun serve(session: IHTTPSession): Response {
        return when (session.uri) {
            "/" -> newFixedLengthResponse(Response.Status.OK, "text/html", indexHtml)

            "/capture" -> {
                val jpg = FrameStore.latest
                if (jpg == null) {
                    newFixedLengthResponse(
                        Response.Status.SERVICE_UNAVAILABLE, MIME_PLAINTEXT, "sin frame todavia"
                    )
                } else {
                    newFixedLengthResponse(
                        Response.Status.OK, "image/jpeg", ByteArrayInputStream(jpg), jpg.size.toLong()
                    ).apply { addHeader("Cache-Control", "no-store") }
                }
            }

            "/status" -> {
                val ip = Net.localIp() ?: ""
                val fps = String.format(Locale.US, "%.1f", FrameStore.fps)
                val uptime = (SystemClock.elapsedRealtime() - startedAt) / 1000
                val json = "{\"ip\":\"$ip\",\"width\":${FrameStore.width},\"height\":${FrameStore.height}," +
                    "\"fps\":$fps,\"frames\":${FrameStore.frames},\"uptime_s\":$uptime," +
                    "\"locked\":${CameraState.locked}}"
                newFixedLengthResponse(Response.Status.OK, "application/json", json)
            }

            "/config" -> {
                applyConfig(session.parms)
                newFixedLengthResponse(Response.Status.OK, "application/json", configJson())
            }

            else -> newFixedLengthResponse(Response.Status.NOT_FOUND, MIME_PLAINTEXT, "no encontrado")
        }
    }

    private fun applyConfig(params: Map<String, String>) {
        params["quality"]?.toIntOrNull()?.let { CameraState.jpegQuality = it.coerceIn(30, 100) }
        params["maxfps"]?.toIntOrNull()?.let { CameraState.maxFps = it.coerceIn(1, 30) }
        params["rot"]?.toIntOrNull()?.let {
            if (it == 0 || it == 90 || it == 180 || it == 270) CameraState.extraRotation = it
        }
        params["exp"]?.let { exp ->
            val service = CameraServerService.instance
            if (exp == "auto" || exp == "0") {
                service?.setManualExposure(null, null)
            } else {
                exp.toDoubleOrNull()?.let { service?.setManualExposure(it, params["iso"]?.toIntOrNull()) }
            }
        }
        when (params["lock"]) {
            "1" -> CameraServerService.instance?.setLock(true)
            "0" -> CameraServerService.instance?.setLock(false)
        }
    }

    private fun configJson(): String {
        val exposureMs = CameraState.exposureNs
            ?.let { String.format(Locale.US, "%.2f", it / 1_000_000.0) } ?: "null"
        val focus = CameraState.focusDiopters
            ?.let { String.format(Locale.US, "%.2f", it) } ?: "null"
        return "{\"locked\":${CameraState.locked},\"manual\":${CameraState.manualExposureNs != null},\"quality\":${CameraState.jpegQuality}," +
            "\"maxfps\":${CameraState.maxFps},\"rot\":${CameraState.extraRotation}," +
            "\"exposure_ms\":$exposureMs,\"iso\":${CameraState.iso ?: "null"},\"focus_diopters\":$focus}"
    }
}
