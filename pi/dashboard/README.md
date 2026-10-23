# Panel y pantalla de RockU (versión simulador)

Interfaz web de la correa. Por ahora los datos vienen de un simulador en el navegador (`js/sim.js`), así que se puede abrir sin Pi, sin teléfono y sin correa.

## Cómo verlo

Abrir `index.html` (panel completo) o `mini.html` (pantalla de 3.5", 480x320) directamente en el navegador. No necesita servidor ni internet: la fuente está incluida.

- `index.html?auto=0` desactiva el ciclo automático de fallas.
- En `mini.html` hay atajos de teclado para la demo: 1 normal, 2 detener, 3 desalinear a la izquierda, 4 desalinear a la derecha, 5 piedra, 6 cortar señal, 7 calibrar.

## Archivos

| Archivo | Contenido |
|---|---|
| `index.html`, `css/dashboard.css`, `js/dashboard.js` | Panel completo |
| `mini.html`, `css/mini.css`, `js/mini.js` | Pantalla de la Pi (se escala a la ventana, en la Pi vale 1) |
| `css/tokens.css` | Colores del logo, fuente y tonos de estado compartidos |
| `js/sim.js` | Simulador y máquina de estados con confirmación por persistencia |
| `js/scene.js` | Dibujo de la correa vista desde arriba (también las miniaturas de evidencia) |

## Pasar a datos reales

`sim.js` entrega las mismas medidas que `Detector` y `Clasificador` de `pi/deteccion.py`: velocidad, desvío, ángulo, distancia del sensor y estado. Para conectar la correa real, el servidor Flask debe exponer `/api/stream` (SSE, 1 a 10 Hz) con esos campos y los eventos, y los dos frontends cambian la fuente del simulador por ese stream. Los colores de estado y los textos no cambian.

En la pantalla de la Pi: Chromium en modo kiosco apuntando a `http://localhost:5000/mini`.
