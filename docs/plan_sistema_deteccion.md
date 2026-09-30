# Sistema de detección para correa transportadora (MVP)

Proyecto: Taller de Innovación, monitoreo de correas transportadoras para minería en Latinoamérica.
Última actualización: 30-09-2026.
Estado: pasos 1 y 1b completados. La cámara del sistema pasó a ser un teléfono Android. Siguiente: algoritmos de detección (paso 2).

## 1. Hardware

- Raspberry Pi 4 Model B (BCM2711), microSD 32 GB, Raspberry Pi OS 64 bits (Debian 13 trixie), usuario `fer`, hostname `correa-fm-uai`
- **Cámara: teléfono Samsung Galaxy S25 Ultra (Android 16)** con la app propia CorreaCam. Reemplaza a la ESP32-CAM como sensor de imagen
- ESP32-CAM (chip ESP32-D0WDQ6, sensor GC2145) con HC-SR04: queda solo como **nodo de distancia**. Su cámara ya no se usa
- Sensor ultrasónico HC-SR04 conectado a la ESP32-CAM
- Pantalla genérica 3.5" con touch XPT2046 (modelo exacto por confirmar: solo GPIO o con HDMI)
- Correa a escala de diseño propio (ver sección 4)
- Opcional: módulo RTC DS3231 (I2C), buzzer o LED por GPIO
- Computador de trabajo: Windows (Arduino IDE y Android Studio)

## 2. Alcance del MVP

Detecciones:
- Correa detenida o en movimiento
- Desalineación lateral
- Paso de objeto o piedra (HC-SR04)

Fuera del MVP (fase 2): rasgaduras, cuerpos extraños pequeños, modelos de ML, cámara oficial de Raspberry Pi por CSI (queda como mejora futura en el informe).

## 3. Arquitectura

### Red
- Desarrollo: todo en el WiFi de casa (Pi, teléfono y ESP32 en 192.168.1.x). IPs vistas hasta ahora: teléfono 192.168.1.84, ESP32 192.168.1.86.
- Demo final: la Pi crea su propio WiFi (punto de acceso) y teléfono y ESP32 se conectan a ella. El teléfono pierde sus datos móviles mientras esté en esa red.
- En la demo hay que fijar IPs (reserva DHCP en la Pi) para que la Pi encuentre siempre al teléfono y a la ESP32.

### Teléfono (cámara) con la app CorreaCam
App propia en Kotlin (CameraX + servidor HTTP NanoHTTPD), servicio en primer plano que sigue activo con la pantalla apagada. Puerto 8080. Mismo contrato que tenía el firmware de la ESP32:
- `GET /capture`: último frame JPEG
- `GET /status`: JSON con IP, resolución, fps y uptime
- `GET /config`: ajustes y valores reales (exposición, ISO, foco)
  - `?lock=1|0`: bloquea o libera exposición, balance de blancos y foco
  - `?exp=<ms>&iso=<n>`: exposición manual (`exp=auto` vuelve a automático)
  - `?quality=30..100`, `?maxfps=1..30`, `?rot=0|90|180|270`
- `GET /`: página con vista en vivo y botones de control, útil para apuntar, enfocar y calibrar

Decisiones de imagen:
- Resolución del frame: 1080x1440 (vertical), calidad JPEG 85, tope de 15 fps.
- Exposición, balance de blancos y foco bloqueados durante la operación, para que los algoritmos no se degraden por autoajuste.
- Exposición corta (objetivo menor a 5 ms) para evitar desenfoque por movimiento. Requiere buena iluminación (ver sección 4).
- Con luz de red de 50 Hz, usar exposición de 10 ms o 20 ms para evitar bandas de parpadeo, o usar lámparas LED de corriente continua.
- Cámara trasera principal, fija sobre la correa mirando hacia abajo.

### Nodo de distancia (ESP32-CAM con HC-SR04)
- Mide la distancia a la correa ~20 veces por segundo en el segundo núcleo.
- Guarda una distancia base (correa vacía). Si la lectura cae bajo la base menos un margen durante 2 o 3 lecturas seguidas, confirma objeto.
- Al confirmar, hace `POST /event` a la Pi con distancia y contador de eventos (ya no envía foto).
- La Pi, al recibir el evento, pide de inmediato `/capture` al teléfono y guarda ese frame como evidencia.
- Conexión del HC-SR04: VCC a 5V, GND a GND, TRIG a GPIO13, ECHO a GPIO14 con divisor de voltaje (1k y 2k).
- Evitar GPIO0, 2, 12, 15 y 16 (arranque, flash y cámara).
- Montaje: sensor 10 a 15 cm sobre la correa apuntando hacia abajo, aguas arriba del campo de la cámara. Distancia mínima confiable 2 a 3 cm, cono de ~15 grados.
- Firmware actual de la ESP32: `esp32cam_basico.ino` (sirve `/capture` y `/status`). Habrá que reemplazarlo por uno que solo mida distancia y envíe eventos.

### Raspberry Pi (nodo de análisis)
Un solo proceso Python con hilos:
1. Hilo de captura: pide frames al teléfono a ~8 a 10 fps.
2. Preprocesado: escala de grises, reducción a 640x480 y ROI sobre la correa. La resolución completa se usa solo para las fotos de eventos.
3. Detección de detención: `cv2.phaseCorrelate` entre frames. Si el desplazamiento queda bajo el umbral durante N segundos, estado DETENIDA. Entrega además velocidad relativa.
4. Detección de desalineación: líneas de borde y borde de la correa (umbral + contornos, o Canny/Hough), desvío lateral y ángulo contra una referencia calibrada.
5. Recepción de eventos de objeto desde la ESP32 y captura del frame asociado.
6. Máquina de estados con confirmación por persistencia de varios frames.

Estados: `CALIBRANDO`, `NORMAL`, `DETENIDA`, `DESALINEADA`, `OBJETO_DETECTADO`, `SIN_SENAL`.

La Pi usa la velocidad de la correa para ajustar la demora entre el disparo del sensor y la captura si la cámara mira un punto distinto al del sensor.

## 4. Correa a escala (diseño propuesto)

Medidas aproximadas. Las cifras de campo visual deben verificarse midiendo con la cámara real.

**Geometría**
- Ancho útil: 15 cm. Largo del lazo: al menos 60 cm.
- Material: blanco mate (lona, vinilo mate o papel grueso plastificado mate). Evitar brillos.
- Fondo bajo y junto a la correa: negro o gris oscuro mate, para que el borde de la correa tenga contraste.
- Uniones: una sola costura plana, sin relieve.

**Marcas (para medir alineación y movimiento)**
- Dos líneas negras longitudinales de 8 mm de ancho, a 10 mm de cada borde. Sirven para medir desalineación (desvío y ángulo).
- Marcas transversales negras de 6 mm de ancho, a lo ancho entre las líneas de borde, con espaciado irregular. Secuencia de separaciones (borde a borde de marca): 35, 62, 48, 85, 41, 70, 55 y 38 mm, que suma 434 mm y se repite. El periodo debe ser mayor que el campo visual (~37 cm) para que no haya ambigüedad en la correlación de fase. Sumar 6 a 8 puntos negros de 5 mm entre marcas.
- 6 a 8 puntos negros de 5 mm repartidos al azar en la zona central, como textura extra.
- Regla práctica: ningún detalle por debajo de 5 mm, porque al reducir a 640x480 un detalle menor queda de pocos píxeles.

**Cámara e iluminación**
- Teléfono a 25 a 30 cm sobre la correa, centrado, paralelo a ella y mirando hacia abajo. El campo visible es aproximadamente 1 x la altura en el lado corto de la imagen (medir al montar).
- Orientación: dejar el eje de avance de la correa a lo largo del lado largo de la imagen vertical. Si hace falta, se gira con `rot`.
- Dos lámparas LED de corriente continua (sin regulación PWM), laterales a ~45 grados y difusas, para evitar reflejos y sombras duras.
- Soporte rígido para el teléfono (trípode o brazo), sin vibración. Teléfono alimentado por USB para que no se descargue ni se caliente con la batería.

**Velocidad objetivo**
- 5 a 15 cm/s. A 10 fps la correa avanza entre 0.5 y 1.5 cm por frame, muy por debajo de un cuarto de la imagen. A 5 ms de exposición y 15 cm/s, el desenfoque es menor a 1 mm.

## 5. Salidas

### Registro
- SQLite con timestamp, tipo de evento y valores medidos.
- Foto del frame de cada evento.

### Servidor web (Flask)
- Panel con estado actual, velocidad, desvío, historial y video en vivo anotado.
- API: `/api/status` y `/api/events`.
- Descargas: `/export/eventos.csv` y `/export/muestras.csv`, con filtro por rango de fechas.

### Pantalla 3.5"
- Chromium en modo kiosco mostrando una página liviana (480x320) con el estado en grande.
- Botones táctiles: Calibrar, Silenciar alarma, Exportar a USB.
- Se hace después de los algoritmos (ver riesgos).

### Exportación CSV
- `muestras.csv`: una fila por segundo con timestamp, estado, velocidad relativa, desvío lateral, ángulo y distancia del sensor.
- `eventos.csv`: una fila por evento con timestamp, tipo, duración, valores medidos y nombre de la foto asociada.
- UTF-8 con BOM y separador configurable (coma o punto y coma) para que Excel en español lo abra bien.
- USB: al conectar un pendrive, el botón "Exportar a USB" (pantalla y web) copia CSV y fotos, y desmonta de forma segura antes de avisar.
- Online: descargas directas desde la web de la Pi. Subida automática a internet (Google Sheets o servidor propio) queda como módulo opcional y requiere Ethernet o un adaptador WiFi USB, porque el WiFi integrado lo ocupa el punto de acceso.

### Alertas
- Buzzer o LED por GPIO (opcional).

### Calibración
- Botón en pantalla o web que guarda la referencia de bordes y el umbral de movimiento con la correa en condición normal.

## 6. Resultados medidos (para el informe)

Comparación de fuentes de imagen, medida desde la Pi con 50 frames consecutivos por WiFi:

| Fuente | Resolución | Frames OK | Velocidad | Tamaño medio |
|---|---|---|---|---|
| ESP32-CAM (GC2145, formato crudo convertido a JPEG) | 320x240 | 50/50 | 5.6 fps | 5.6 KB (pared lisa) |
| Teléfono S25 Ultra (app CorreaCam) | 1080x1440 | 50/50 | 10.3 fps (app: hasta 15 fps) | 120 KB |

Observaciones sobre la ESP32-CAM: el sensor GC2145 no soporta JPEG por hardware con el driver de la ESP32. Entrega frames en formato crudo con mensajes `FB-SIZE` intermitentes, y la imagen mostró tinte verdoso. Por eso se descartó como cámara principal.

Observaciones sobre el teléfono: con poca luz, la exposición automática eligió 30 ms con ISO ~1000. Con exposición manual se puede fijar un tiempo corto, pero exige más iluminación.

## 7. Riesgos y detalles a cuidar

- La Pi 4 no tiene reloj de tiempo real. Sin internet los timestamps salen mal tras cada reinicio. Solución: sincronizar la hora desde el navegador que abre el panel, o usar un RTC DS3231.
- El ECHO del HC-SR04 sale a 5 V, la ESP32 trabaja a 3.3 V: divisor de voltaje obligatorio.
- La pantalla por GPIO ocupa el bus SPI. Confirmar pines libres cuando se conozca el modelo.
- Si la correa es lisa, la detección de detención por cámara no funciona sin marcas visibles.
- Teléfono como cámara: se calienta con la cámara activa, necesita alimentación continua, y Android puede cerrar el servicio si el sistema se queda sin recursos. La app corre como servicio en primer plano de tipo cámara y debe iniciarse con la app visible.
- El servidor del teléfono no tiene autenticación: solo usar en una red cerrada (punto de acceso de la Pi).
- El bloqueo de exposición y foco funciona, pero se debe volver a bloquear si cambia la iluminación o la distancia.
- Parpadeo de la luz de red (50 Hz) con exposiciones cortas: usar LED DC o exposición de 10 ms o 20 ms.

## 8. Orden de trabajo

Se confirma cada paso antes de avanzar al siguiente.

1. [Hecho] Puesta en marcha: Raspberry Pi OS, SSH, OpenCV, Flask y SQLite instalados. Prueba de imagen con la ESP32-CAM.
1b. [Hecho] Cámara del teléfono: app CorreaCam con `/capture`, `/status`, `/config`, bloqueo de exposición, blancos y foco, y exposición manual. Medida desde la Pi: 50/50 frames a 10.3 fps.
2. [Siguiente] Algoritmos de detección y grabación de material: `grabar.py` (frames etiquetados desde el teléfono) y `analizar.py` (velocidad por correlación de fase, desvío y ángulo de bordes, umbrales). Validación con imágenes sintéticas antes de usar la correa real.
3. Integrar captura, análisis y máquina de estados con la base de datos.
4. Servidor web, pantalla y exportación CSV.
5. Nodo de distancia: firmware de la ESP32 solo para HC-SR04, eventos a la Pi y alertas.
6. Punto de acceso WiFi de la Pi con IPs fijas para la demo.

## 9. Pendientes por confirmar

- Modelo exacto de la pantalla (solo GPIO o con HDMI, serigrafía del PCB tipo "MPI3501").
- Si se usará RTC DS3231.
- Si se quiere el módulo de subida automática a internet.
- Armar la correa según la sección 4 y conseguir el soporte para el teléfono.
- Etapa 2 de la app (`/stream`, batería, temperatura, aviso de desconexión), de baja prioridad.
