# API del servidor RockU (Flask en la Pi)

Contrato entre el servidor (`pi/servidor.py`) y los dos frontends (`pi/dashboard/index.html` y `mini.html`).
Todo en español, JSON UTF-8, tiempos en milisegundos desde epoch (`t`), duraciones en segundos (`dur_s`).
Puerto 5000. CORS abierto (`Access-Control-Allow-Origin: *`) para poder abrir el panel desde un archivo local.

## Estados (claves fijas)

`CALIBRANDO`, `NORMAL`, `DETENIDA`, `DESALINEADA`, `OBJETO_DETECTADO`, `SIN_SENAL`.
Mapeo desde `Clasificador`: `SIN_LINEAS` crudo se trata como `SIN_SENAL` solo si tampoco llegan frames; si llegan frames pero no hay líneas, conservar el último estado confirmado.
`OBJETO_DETECTADO` lo genera el evento del ESP32 (`POST /event`) y se mantiene 4 s (prioridad sobre NORMAL, DESALINEADA y DETENIDA mientras dura). `SIN_SENAL` si no llega un frame válido del teléfono en 2 s.

## Unidades

- `vel` en cm/s (el detector entrega mm/s: dividir por 10)
- `lat` desvío lateral en mm respecto de la referencia calibrada, positivo a la derecha
- `ang` ángulo en grados respecto de la referencia
- `dist` distancia del HC-SR04 en mm (base con correa vacía: 120)
- Límites usados por el frontend: detenida bajo 0.8 cm/s, desvío mayor a 8 mm, ángulo mayor a 2 grados. En modo real salen de `calibracion.json`.

## GET /api/snapshot

Estado completo para pintar el panel al cargar:

```json
{
  "fuente": "sim",
  "t": 1792716000000,
  "estado": "NORMAL",
  "desde": 1792715300000,
  "cand": {"estado": "DETENIDA", "n": 5, "need": 20},
  "medida": {"vel": 10.1, "lat": 0.3, "ang": 0.1, "dist": 120.4},
  "senal": true,
  "fps": 14.6,
  "latencia_ms": 70,
  "cpu": 31.0,
  "temp_c": 53.0,
  "esp_ultimo_ms": 1792715580000,
  "calibrando": null,
  "silenciada": false,
  "limites": {"vel_min": 0.8, "lat_max": 8, "ang_max": 2, "dist_base": 120, "obj_caida": 25},
  "muestras": [{"t": 1792715999000, "vel": 10.0, "lat": 0.2, "ang": 0.1, "dist": 120.1, "estado": "NORMAL"}],
  "segmentos": [{"estado": "NORMAL", "t0": 1792712400000, "t1": null}],
  "eventos": [{"id": 12, "t": 1792715580000, "tipo": "OBJETO_DETECTADO", "dur_s": 5.0, "detalle": "Obstáculo a 74 mm del sensor (correa vacía: 120 mm)", "valor": "46 mm de alto", "foto": "/foto/12.jpg", "snap": {"vel": 10.1, "lat": 0.4, "ang": 0.1, "dist": 74.0}}]
}
```

- `calibrando`: `null` o `{"progreso": 0.0 a 1.0}`
- `muestras`: una por segundo, últimas 900 (15 min), orden cronológico
- `segmentos`: tramos de estado de la última hora, `t1` null el tramo abierto
- `eventos`: más reciente primero, máximo 200; `dur_s` null si sigue en curso; `foto` null si no hay (en `sim` siempre null)
- En `fuente: "sim"` el servidor genera datos con la misma lógica que `pi/dashboard/js/sim.js` (misma máquina de estados con persistencia, escenarios y ruido). En `fuente: "real"` salen de teléfono, `Detector`, `Clasificador` y ESP32.

## GET /api/stream (Server-Sent Events)

`Content-Type: text/event-stream`. Al conectar envía primero un evento `snapshot` con el JSON de arriba y luego:

| evento | frecuencia | datos |
|---|---|---|
| `tick` | 5 Hz | `{"t","estado","desde","cand","medida","senal","fps","latencia_ms","cpu","temp_c","esp_ultimo_ms","calibrando","silenciada"}` (mismos campos que el snapshot) |
| `muestra` | 1 Hz | un objeto de `muestras` |
| `evento` | al confirmarse | un objeto de `eventos` (con `dur_s` null) |
| `evento_fin` | al cerrarse | `{"id","dur_s"}` |
| `estado` | al cambiar | `{"t","prev","next"}` |

Enviar un comentario `: ping` cada 15 s para mantener viva la conexión.

## Otros endpoints

- `GET /api/status`: igual a `tick`, sin historial.
- `GET /api/events?tipo=DETENIDA&desde=<ms>&limite=100`: lista de eventos (mismo formato).
- `GET /api/frame.jpg`: último frame anotado (líneas medidas, estado). `404` en fuente `sim`.
- `GET /foto/<id>.jpg`: foto de evidencia.
- `POST /api/cmd` con `{"accion":"calibrar"}` | `{"accion":"silenciar","valor":true}` | `{"accion":"escenario","nombre":"detener"}` (solo `sim`; nombres: `normal`, `detener`, `izquierda`, `derecha`, `angulo`, `objeto`, `senal`, `calibrar`) | `{"accion":"objetivo","vel":10,"lat":0,"ang":0}` (solo `sim`) | `{"accion":"auto","valor":true}` (solo `sim`). Respuesta `{"ok":true}`.
- `POST /event` (lo llama el ESP32): `{"distancia_mm": 74, "n": 12}`. Dispara `OBJETO_DETECTADO` y la foto.
- `GET /export/eventos.csv` y `GET /export/muestras.csv`: `?desde=<ms>&hasta=<ms>&sep=;`. UTF-8 con BOM, separador `;` por defecto, decimales con punto.
- `GET /` y `GET /mini`: sirven `pi/dashboard/index.html` y `mini.html`. El resto de `pi/dashboard/` se sirve en la raíz (`/css/...`, `/js/...`, `/fonts/...`).

## Frontend

El frontend intenta `GET /api/snapshot` (mismo origen o `?api=http://IP:5000`). Si responde, usa `js/remote.js` y deja de usar el simulador del navegador. Si falla, cae al simulador local.
