"""Fuentes de datos del servidor RockU.

Clase base `Fuente` con la interfaz comun (snapshot, stream por suscripcion, comandos,
historial) y dos implementaciones:

- `FuenteSim`: port a Python de pi/dashboard/js/sim.js. Misma maquina de estados con
  persistencia, escenarios, ruido, historial de 1 hora y ciclo automatico.
- `FuenteReal`: telefono (CorreaCam), `Detector` y `Clasificador` de deteccion.py y los
  eventos POST /event del ESP32 con el HC-SR04.

Contrato de la API: docs/api.md. Unidades: vel en cm/s, lat y dist en mm, ang en grados,
tiempos en milisegundos desde epoch.
"""
import hashlib
import json
import logging
import os
import queue
import random
import threading
import time
from collections import deque

log = logging.getLogger("rockU")

ESTADOS = ["CALIBRANDO", "NORMAL", "DETENIDA", "DESALINEADA", "OBJETO_DETECTADO", "SIN_SENAL"]
LIM = {"vel_nom": 10.0, "vel_min": 0.8, "lat_max": 8.0, "ang_max": 2.0, "dist_base": 120.0, "obj_caida": 25.0}
MAX_EVENTOS = 200
MAX_MUESTRAS = 900
VENTANA_SEG_MS = 3600 * 1000


def ahora_ms():
    return int(time.time() * 1000)


def _r(v, d=1):
    return None if v is None else round(float(v), d)


# ---------------------------------------------------------------------------
# Lectura de CPU y temperatura (Raspberry Pi). Si no hay /proc o /sys devuelve None.
# ---------------------------------------------------------------------------
class _Sistema:
    def __init__(self):
        self._ant = None

    def cpu(self):
        try:
            with open("/proc/stat") as f:
                p = [int(x) for x in f.readline().split()[1:]]
        except (OSError, ValueError):
            return None
        total, ocioso = sum(p), p[3] + (p[4] if len(p) > 4 else 0)
        ant, self._ant = self._ant, (total, ocioso)
        if not ant or total == ant[0]:
            return None
        return round(100.0 * (1 - (ocioso - ant[1]) / (total - ant[0])), 1)

    @staticmethod
    def temp():
        for ruta in ("/sys/class/thermal/thermal_zone0/temp",):
            try:
                with open(ruta) as f:
                    return round(int(f.read().strip()) / 1000.0, 1)
            except (OSError, ValueError):
                pass
        return None


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class Fuente:
    nombre = "base"

    def __init__(self, registro=None, dir_fotos=None):
        self.registro = registro
        self.dir_fotos = dir_fotos
        if dir_fotos:
            os.makedirs(dir_fotos, exist_ok=True)
        self.lock = threading.RLock()
        self._parar = threading.Event()
        self._hilos = []
        self._subs = []
        self._subs_lock = threading.Lock()
        self._sys = _Sistema()

        self.estado = "NORMAL"
        self.desde = ahora_ms()
        self.cand = {"estado": "NORMAL", "n": 0, "need": 1}
        self.medida = {"vel": LIM["vel_nom"], "lat": 0.0, "ang": 0.0, "dist": LIM["dist_base"]}
        self.senal = True
        self.fps = 0.0
        self.latencia_ms = None
        self.cpu = None
        self.temp_c = None
        self.esp_ultimo_ms = None
        self.calibrando = None           # None o {"progreso": 0..1}
        self.silenciada = False
        self.limites = {"vel_min": LIM["vel_min"], "lat_max": LIM["lat_max"], "ang_max": LIM["ang_max"],
                        "dist_base": LIM["dist_base"], "obj_caida": LIM["obj_caida"]}
        self.muestras = deque(maxlen=MAX_MUESTRAS)
        self.segmentos = []
        self.eventos = []                # mas reciente primero
        self._evento_abierto = None
        self._seq = 0

    # ----- ciclo de vida -----
    def iniciar(self):
        self._lanzar(self._hilo_pub, "pub")

    def detener(self):
        self._parar.set()
        for h in self._hilos:
            h.join(timeout=3)
        if self.registro:
            self.registro.flush()

    def _lanzar(self, fn, nombre):
        h = threading.Thread(target=fn, name="rockU-" + nombre, daemon=True)
        h.start()
        self._hilos.append(h)

    # ----- publicacion (SSE) -----
    def suscribir(self):
        q = queue.Queue(maxsize=500)
        with self._subs_lock:
            self._subs.append(q)
        return q

    def desuscribir(self, q):
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)

    def _pub(self, nombre, datos):
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait((nombre, datos))
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait((nombre, datos))
                except (queue.Empty, queue.Full):
                    pass

    # ----- vistas -----
    def status(self):
        with self.lock:
            return {
                "t": ahora_ms(), "estado": self.estado, "desde": self.desde, "cand": dict(self.cand),
                "medida": {k: _r(v) for k, v in self.medida.items()},
                "senal": self.senal, "fps": _r(self.fps), "latencia_ms": _r(self.latencia_ms, 0),
                "cpu": self.cpu, "temp_c": self.temp_c, "esp_ultimo_ms": self.esp_ultimo_ms,
                "calibrando": dict(self.calibrando) if self.calibrando else None,
                "silenciada": self.silenciada,
            }

    def snapshot(self):
        with self.lock:
            s = self.status()
            s["fuente"] = self.nombre
            s["limites"] = dict(self.limites)
            s["muestras"] = [dict(m) for m in self.muestras]
            corte = ahora_ms() - VENTANA_SEG_MS
            s["segmentos"] = [dict(g) for g in self.segmentos if g["t1"] is None or g["t1"] >= corte]
            s["eventos"] = [dict(e) for e in self.eventos[:MAX_EVENTOS]]
            return s

    def lista_eventos(self, tipo=None, desde=None, limite=100):
        limite = max(1, min(int(limite), MAX_EVENTOS))
        if self.registro:
            return self.registro.cargar_eventos(limite, tipo, desde)
        with self.lock:
            out = [dict(e) for e in self.eventos
                   if (not tipo or e["tipo"] == tipo) and (desde is None or e["t"] >= desde)]
        return out[:limite]

    # ----- estado, segmentos y eventos -----
    def _aplicar_estado(self, nuevo, t=None):
        """Cambia el estado confirmado: cierra segmento y evento, abre los nuevos y avisa."""
        with self.lock:
            if nuevo == self.estado:
                return
            t = t or ahora_ms()
            prev = self.estado
            if self.segmentos and self.segmentos[-1]["t1"] is None:
                self.segmentos[-1]["t1"] = t
            self.segmentos.append({"estado": nuevo, "t0": t, "t1": None})
            if self._evento_abierto:
                ev = self._evento_abierto
                self._evento_abierto = None
                ev["dur_s"] = round((t - ev["t"]) / 1000.0, 1)
                if self.registro:
                    self.registro.cerrar_evento(ev["id"], ev["dur_s"])
                self._pub("evento_fin", {"id": ev["id"], "dur_s": ev["dur_s"]})
            self.estado, self.desde = nuevo, t
            self.cand = {"estado": nuevo, "n": 0, "need": 1}
            if nuevo == "NORMAL":
                self.silenciada = False
            self._pub("estado", {"t": t, "prev": prev, "next": nuevo})
            if nuevo not in ("NORMAL", "CALIBRANDO"):
                ev = self._crear_evento(nuevo, t)
                self._evento_abierto = ev
                self._pub("evento", dict(ev))

    def _crear_evento(self, tipo, t, snap=None, dur_s=None):
        m = self.medida
        snap = snap or {"vel": _r(m["vel"]), "lat": _r(m["lat"]), "ang": _r(m["ang"]), "dist": _r(m["dist"])}
        detalle, valor = textos_evento(tipo, snap, self.limites)
        ev = {"id": 0, "t": t, "tipo": tipo, "dur_s": dur_s, "detalle": detalle, "valor": valor,
              "foto": None, "snap": snap}
        if self.registro:
            ev["id"] = self.registro.guardar_evento(ev)
        else:
            self._seq += 1
            ev["id"] = self._seq
        self.eventos.insert(0, ev)
        del self.eventos[MAX_EVENTOS:]
        return ev

    def _asignar_foto(self, eid, jpg):
        """Guarda la foto de evidencia y la enlaza al evento."""
        if not self.dir_fotos or not jpg:
            return None
        ruta = os.path.join(self.dir_fotos, "%d.jpg" % eid)
        with open(ruta, "wb") as f:
            f.write(jpg)
        url = "/foto/%d.jpg" % eid
        with self.lock:
            for e in self.eventos:
                if e["id"] == eid:
                    e["foto"] = url
        if self.registro:
            self.registro.actualizar_foto(eid, url)
        return url

    def ruta_foto(self, eid):
        if not self.dir_fotos:
            return None
        ruta = os.path.join(self.dir_fotos, "%d.jpg" % int(eid))
        return ruta if os.path.isfile(ruta) else None

    # ----- historial persistido -----
    def _restaurar(self):
        """Carga muestras y eventos desde el registro. Devuelve True si habia datos."""
        reg = self.registro
        if not reg or reg.vacia():
            return False
        ahora = ahora_ms()
        self.muestras.extend(reg.cargar_muestras(MAX_MUESTRAS))
        self.eventos = reg.cargar_eventos(MAX_EVENTOS)
        t_ult = reg.ultima_muestra_t() or ahora
        # eventos que quedaron abiertos al apagar: se cierran en la ultima muestra
        for e in self.eventos:
            if e["dur_s"] is None:
                e["dur_s"] = round(max(0, t_ult - e["t"]) / 1000.0, 1)
                reg.cerrar_evento(e["id"], e["dur_s"])
        self._seq = max([e["id"] for e in self.eventos] + [0])
        # segmentos de la ultima hora: tramos de eventos con huecos en NORMAL
        corte = ahora - VENTANA_SEG_MS
        recientes = sorted((e for e in self.eventos if e["t"] + (e["dur_s"] or 0) * 1000 >= corte), key=lambda e: e["t"])
        t = max(corte, self.muestras[0]["t"]) if self.muestras else ahora
        for e in recientes:
            t0, t1 = max(e["t"], corte), e["t"] + int((e["dur_s"] or 0) * 1000)
            if t0 > t:
                self.segmentos.append({"estado": "NORMAL", "t0": t, "t1": t0})
            if t1 > max(t, t0):
                self.segmentos.append({"estado": e["tipo"], "t0": t0, "t1": t1})
                t = t1
        return True

    # ----- publicador: tick 5 Hz, muestra 1 Hz -----
    def _hilo_pub(self):
        n = 0
        prox = time.monotonic()
        while not self._parar.is_set():
            prox += 0.2
            n += 1
            try:
                if n % 5 == 0 and self.nombre == "real":
                    c = self._sys.cpu()
                    if c is not None:
                        self.cpu = c
                    self.temp_c = self._sys.temp()
                self._pub("tick", self.status())
                if n % 5 == 0:
                    m = self._tomar_muestra()
                    self._pub("muestra", m)
            except Exception:                      # el publicador nunca debe morir
                log.exception("error en el publicador")
            esp = prox - time.monotonic()
            if esp > 0:
                self._parar.wait(esp)
            else:
                prox = time.monotonic()

    def _tomar_muestra(self):
        with self.lock:
            m = self.medida
            s = {"t": ahora_ms(), "vel": _r(m["vel"]), "lat": _r(m["lat"]), "ang": _r(m["ang"]),
                 "dist": _r(m["dist"]), "estado": self.estado}
            self.muestras.append(s)
        if self.registro:
            self.registro.guardar_muestra(s)
        return s

    # ----- interfaz que implementan las fuentes -----
    def cmd(self, d):
        """Ejecuta un comando de /api/cmd. Devuelve (ok, mensaje)."""
        acc = d.get("accion")
        if acc == "silenciar":
            with self.lock:
                self.silenciada = bool(d.get("valor", not self.silenciada))
            return True, ""
        if acc == "calibrar":
            return self._calibrar()
        return self._cmd_fuente(acc, d)

    def _calibrar(self):
        return False, "no disponible"

    def _cmd_fuente(self, acc, d):
        return False, "accion desconocida o no disponible en esta fuente: %s" % acc

    def evento_esp(self, distancia_mm, n=None):
        raise NotImplementedError

    def frame_jpg(self):
        return None


def textos_evento(tipo, snap, limites):
    """Detalle y medida del evento, con los mismos textos que sim.js."""
    base = limites.get("dist_base", LIM["dist_base"])
    if tipo == "DETENIDA":
        return "Velocidad bajo %.1f cm/s" % limites.get("vel_min", LIM["vel_min"]), "%.1f cm/s" % (snap.get("vel") or 0.0)
    if tipo == "DESALINEADA":
        lat, ang = snap.get("lat") or 0.0, snap.get("ang") or 0.0
        sg = "+" if lat >= 0 else ""
        return ("Desvío %s%.1f mm, ángulo %s%.1f°" % (sg, lat, "+" if ang >= 0 else "", ang), "%s%.1f mm" % (sg, lat))
    if tipo == "OBJETO_DETECTADO":
        d = snap.get("dist") or base
        return ("Obstáculo a %d mm del sensor (correa vacía: %d mm)" % (round(d), round(base)),
                "%d mm de alto" % round(base - d))
    if tipo == "SIN_SENAL":
        return "Sin frames del teléfono", "Sin datos"
    return "", ""


# ---------------------------------------------------------------------------
# Simulador
# ---------------------------------------------------------------------------
NEED = {"DETENIDA": 20, "DESALINEADA": 15, "OBJETO_DETECTADO": 3, "SIN_SENAL": 20, "NORMAL": 8}  # ticks de 0.1 s
PASO = 0.1


def _gauss(rng):
    return (rng.random() + rng.random() + rng.random() - 1.5) / 1.5


class FuenteSim(Fuente):
    nombre = "sim"

    def __init__(self, registro=None, dir_fotos=None, auto=True, escala=1.0, semilla=None, sembrar=True):
        super().__init__(registro, dir_fotos)
        self.rng = random.Random(semilla)
        self.auto = auto
        self.escala = float(escala)         # >1 acelera el tiempo simulado (pruebas)
        self.a = {"vel": LIM["vel_nom"], "lat": 0.0, "ang": 0.0}
        self.tg = dict(self.a)
        self.ticks = 0
        self.senal_sim = True
        self.calib = None                   # ticks que faltan de calibracion
        self.obj_hold = 0
        self.obj_dist = 0                   # ticks con caida de distancia en el sensor
        self.obj_alto = 40.0
        self.incidente_hasta = 0.0
        self.auto_en = self.rng.uniform(8, 14)
        self._cand_estado, self._cand_n = "NORMAL", 0
        self.esp_ultimo_ms = ahora_ms() - 420000
        self.fps, self.latencia_ms = 14.6, 70
        self.cpu, self.temp_c = 31.0, 53.0
        restaurado = self._restaurar() if registro else False
        if not restaurado and sembrar:
            self._sembrar()
        if not self.segmentos:
            self.segmentos.append({"estado": "NORMAL", "t0": self.desde, "t1": None})
        else:
            if self.segmentos[-1]["t1"] is not None:
                self.segmentos.append({"estado": "NORMAL", "t0": self.segmentos[-1]["t1"], "t1": None})
        self.desde = self.segmentos[-1]["t0"]

    # ----- historial inicial: una hora con algunos incidentes -----
    def _sembrar(self):
        ahora = ahora_ms()
        plan = [
            (3480, 38, "DESALINEADA", {"lat": 10.4, "ang": 1.2}),
            (3120, 4, "OBJETO_DETECTADO", {"dist": 78.0}),
            (2760, 71, "DETENIDA", {}),
            (2250, 5, "OBJETO_DETECTADO", {"dist": 69.0}),
            (1860, 24, "DESALINEADA", {"lat": -9.1, "ang": -2.6}),
            (1320, 12, "SIN_SENAL", {}),
            (960, 48, "DETENIDA", {}),
            (420, 5, "OBJETO_DETECTADO", {"dist": 74.0}),
        ]
        t = ahora - 3600000
        self.segmentos.append({"estado": "CALIBRANDO", "t0": t, "t1": t + 30000})
        t += 30000
        for ago, dur, tipo, d in plan:
            t0, t1 = ahora - ago * 1000, ahora - ago * 1000 + dur * 1000
            if t0 > t:
                self.segmentos.append({"estado": "NORMAL", "t0": t, "t1": t0})
            self.segmentos.append({"estado": tipo, "t0": t0, "t1": t1})
            t = t1
            snap = {"vel": 0.0 if tipo == "DETENIDA" else 10.1, "lat": d.get("lat", 0.4), "ang": d.get("ang", 0.1),
                    "dist": d.get("dist", LIM["dist_base"])}
            ev = self._crear_evento(tipo, t0, snap=snap, dur_s=float(dur))
            if self.registro:
                self.registro.cerrar_evento(ev["id"], float(dur))
        self.segmentos.append({"estado": "NORMAL", "t0": t, "t1": None})
        for i in range(300, 0, -1):
            self.muestras.append({
                "t": ahora - i * 1000, "vel": _r(LIM["vel_nom"] + _gauss(self.rng) * 0.14),
                "lat": _r(_gauss(self.rng) * 0.7), "ang": _r(_gauss(self.rng) * 0.12, 2),
                "dist": _r(LIM["dist_base"] + _gauss(self.rng) * 0.9), "estado": "NORMAL"})

    # ----- ciclo -----
    def iniciar(self):
        super().iniciar()
        self._lanzar(self._hilo_sim, "sim")

    def _hilo_sim(self):
        prox = time.monotonic()
        paso = PASO / self.escala
        while not self._parar.is_set():
            prox += paso
            try:
                self._paso()
            except Exception:
                log.exception("error en el simulador")
            esp = prox - time.monotonic()
            if esp > 0:
                self._parar.wait(esp)
            else:
                prox = time.monotonic()

    # ----- escenarios y comandos -----
    def _restaurar_objetivos(self):
        self.tg.update(vel=LIM["vel_nom"], lat=0.0, ang=0.0)
        self.senal_sim = True
        self.incidente_hasta = 0.0

    def escenario(self, nombre):
        secs = self.ticks * PASO
        rng = self.rng
        with self.lock:
            if nombre == "normal":
                self._restaurar_objetivos()
            elif nombre == "detener":
                self.tg["vel"] = 0.0
                self.incidente_hasta = secs + rng.uniform(10, 15)
            elif nombre in ("izquierda", "derecha"):
                sg = -1 if nombre == "izquierda" else 1
                self.tg["lat"] = sg * rng.uniform(10.5, 15)
                self.tg["ang"] = sg * rng.uniform(0.8, 2.4)
                self.incidente_hasta = secs + rng.uniform(12, 17)
            elif nombre == "angulo":
                self.tg["ang"] = rng.choice([-1, 1]) * rng.uniform(3.2, 4.6)
                self.tg["lat"] = rng.uniform(-4, 4)
                self.incidente_hasta = secs + rng.uniform(12, 17)
            elif nombre == "objeto":
                self.obj_dist, self.obj_alto = rng.randint(6, 9), rng.uniform(34, 54)
            elif nombre == "senal":
                self.senal_sim = False
                self.incidente_hasta = secs + rng.uniform(6, 9)
            elif nombre == "calibrar":
                self._calibrar()
            else:
                return False
        return True

    def _calibrar(self):
        with self.lock:
            self.calib = 60
        return True, ""

    def _cmd_fuente(self, acc, d):
        if acc == "escenario":
            ok = self.escenario(d.get("nombre"))
            return ok, "" if ok else "escenario desconocido: %s" % d.get("nombre")
        if acc == "objetivo":
            with self.lock:
                for k in ("vel", "lat", "ang"):
                    if d.get(k) is not None:
                        self.tg[k] = float(d[k])
                self.incidente_hasta = 0.0
            return True, ""
        if acc == "auto":
            self.auto = bool(d.get("valor", True))
            return True, ""
        return False, "accion desconocida: %s" % acc

    def evento_esp(self, distancia_mm, n=None):
        """Evento del sensor de distancia: dispara OBJETO_DETECTADO (4 s)."""
        with self.lock:
            self.esp_ultimo_ms = ahora_ms()
            self.obj_hold = 40
            self.medida["dist"] = float(distancia_mm)
            self.obj_dist = 4
            self.obj_alto = max(1.0, LIM["dist_base"] - float(distancia_mm))
            self._cand_estado, self._cand_n = "OBJETO_DETECTADO", NEED["OBJETO_DETECTADO"]
            self._evaluar_estado(ahora_ms(), forzar=True)
            return self._evento_abierto["id"] if self._evento_abierto else None

    # ----- un paso de 0.1 s -----
    def _paso(self):
        with self.lock:
            a, tg, rng = self.a, self.tg, self.rng
            ahora = ahora_ms()
            self.ticks += 1
            secs = self.ticks * PASO
            kv = 1 - pow(2.718281828, -PASO / (0.35 if tg["vel"] < a["vel"] else 0.9))
            kl = 1 - pow(2.718281828, -PASO / 0.9)
            a["vel"] += (tg["vel"] - a["vel"]) * kv
            if a["vel"] < 0.01 and tg["vel"] == 0:
                a["vel"] = 0.0
            a["lat"] += (tg["lat"] - a["lat"]) * kl
            a["ang"] += (tg["ang"] - a["ang"]) * kl

            d = LIM["dist_base"]
            if self.obj_dist > 0:                      # la piedra pasa bajo el sensor
                d = LIM["dist_base"] - self.obj_alto
                self.obj_dist -= 1
                if self.obj_hold == 0 and self.obj_dist <= 5:
                    self.obj_hold = 45
                    self.esp_ultimo_ms = ahora
            if self.obj_hold > 0:
                self.obj_hold -= 1
            if self.incidente_hasta and secs >= self.incidente_hasta:
                self._restaurar_objetivos()

            m = self.medida
            if self.senal_sim:
                m["vel"] = max(0.0, a["vel"] + _gauss(rng) * (0.03 if a["vel"] < 0.3 else 0.14))
                m["lat"] = a["lat"] + _gauss(rng) * 0.35
                m["ang"] = a["ang"] + _gauss(rng) * 0.07
                m["dist"] = d + _gauss(rng) * (1.2 if d < LIM["dist_base"] - 5 else 0.7)
                self.fps = 14.3 + _gauss(rng) * 0.5
                self.latencia_ms = 70 + _gauss(rng) * 6 + (-8 if a["vel"] == 0 else 0)
            else:
                self.fps = 0.0
            self.senal = self.senal_sim
            self.cpu = round(max(18.0, min(58.0, self.cpu + _gauss(rng) * 1.6 + (31 - self.cpu) * 0.05)), 1)
            self.temp_c = round(max(48.0, min(62.0, self.temp_c + _gauss(rng) * 0.1 + (53 - self.temp_c) * 0.01)), 1)

            self._evaluar_estado(ahora)
            self._auto_director()

    def _evaluar_estado(self, ahora, forzar=False):
        m = self.medida
        if self.calib is not None:
            if not forzar:
                self.calib -= 1
            self.calibrando = {"progreso": round(1 - max(0, self.calib) / 60.0, 3)}
            raw = "CALIBRANDO"
            if self.calib <= 0:
                self.calib, self.calibrando, raw = None, None, "NORMAL"
                self._cand_estado, self._cand_n = "NORMAL", NEED["NORMAL"]
        else:
            self.calibrando = None
            if not self.senal:
                raw = "SIN_SENAL"
            elif self.obj_hold > 0:
                raw = "OBJETO_DETECTADO"
            elif m["vel"] < LIM["vel_min"]:
                raw = "DETENIDA"
            elif abs(m["lat"]) > LIM["lat_max"] or abs(m["ang"]) > LIM["ang_max"]:
                raw = "DESALINEADA"
            else:
                raw = "NORMAL"
        if raw == self.estado:
            self._cand_estado, self._cand_n = raw, 0
            self.cand = {"estado": raw, "n": 0, "need": 1}
            return
        if forzar:
            self._cand_estado, self._cand_n = raw, NEED.get(raw, 5)
        elif self._cand_estado == raw:
            self._cand_n += 1
        else:
            self._cand_estado, self._cand_n = raw, 1
        need = 1 if raw == "CALIBRANDO" else NEED.get(raw, 5)
        self.cand = {"estado": raw, "n": min(self._cand_n, need), "need": need}
        if self._cand_n >= need:
            self._aplicar_estado(raw, ahora)

    def _auto_director(self):
        if not self.auto or self.incidente_hasta or self.estado != "NORMAL" or self.calib is not None or self.obj_dist:
            return
        self.auto_en -= PASO
        if self.auto_en <= 0:
            self.escenario(self.rng.choice(["detener", "izquierda", "derecha", "objeto", "objeto", "angulo", "senal"]))
            self.auto_en = self.rng.uniform(16, 30)


# ---------------------------------------------------------------------------
# Fuente real: telefono + Detector + Clasificador + ESP32
# ---------------------------------------------------------------------------
class FuenteReal(Fuente):
    nombre = "real"

    SEG_SIN_SENAL = 2.0       # sin frame valido durante este tiempo: SIN_SENAL
    SEG_OBJETO = 4.0          # duracion de OBJETO_DETECTADO tras un evento del ESP32

    def __init__(self, telefono, ruta_calibracion="calibracion.json", registro=None, dir_fotos=None,
                 fps_objetivo=10.0, calib_s=6.0, sesion=None):
        super().__init__(registro, dir_fotos)
        import cv2                                           # importados aqui para que la fuente sim no los exija
        import numpy as np
        import requests
        import deteccion
        self.cv2, self.np, self.requests, self.det_mod = cv2, np, requests, deteccion
        self.base = telefono.rstrip("/")
        if self.base.endswith("/capture"):
            self.base = self.base[:-len("/capture")]
        self.ses = sesion or requests.Session()
        self.ruta_calib = ruta_calibracion
        self.fps_obj = fps_objetivo
        self.calib_s = calib_s
        self.det = deteccion.Detector()
        self.sin_calibrar = True
        self.calib = deteccion.Calibracion()
        if ruta_calibracion and os.path.isfile(ruta_calibracion):
            try:
                self.calib = deteccion.Calibracion.cargar(ruta_calibracion)
                self.sin_calibrar = False
            except Exception:
                log.exception("no pude leer %s, parto en CALIBRANDO", ruta_calibracion)
        self.clf = deteccion.Clasificador(self.calib)
        self._ult_clf = "NORMAL"
        self._actualizar_limites()

        self.estado = "CALIBRANDO"
        self.medida = {"vel": 0.0, "lat": 0.0, "ang": 0.0, "dist": LIM["dist_base"]}
        self._ultimo_ok = time.monotonic()                   # gracia de arranque para el teléfono
        self._hash = None
        self._fps_ema = 0.0
        self._t_frame = None
        self._n_frames = 0
        self._ult_img = None
        self._ult_m = None
        self._ult_jpg = None
        self._cache_anot = (None, None)
        self._obj_hasta = 0.0
        self._calib_buf = None
        self._calib_t0 = 0.0
        self.error_calibracion = None
        self.senal = True
        self._restaurar() if registro else None
        if self.segmentos and self.segmentos[-1]["t1"] is not None:
            self.segmentos.append({"estado": "CALIBRANDO", "t0": self.segmentos[-1]["t1"], "t1": None})
        elif not self.segmentos:
            self.segmentos.append({"estado": "CALIBRANDO", "t0": self.desde, "t1": None})
        self.desde = self.segmentos[-1]["t0"]

    def _actualizar_limites(self):
        c = self.calib
        self.limites = {"vel_min": round(c.umbral_vel_mm_s / 10.0, 2), "lat_max": round(c.umbral_lateral_mm, 2),
                        "ang_max": round(c.umbral_angulo_deg, 2), "dist_base": LIM["dist_base"],
                        "obj_caida": LIM["obj_caida"]}

    def iniciar(self):
        super().iniciar()
        self._lanzar(self._hilo_captura, "captura")
        self._lanzar(self._hilo_eval, "eval")

    # ----- captura y deteccion -----
    def _hilo_captura(self):
        paso = 1.0 / self.fps_obj
        prox = time.monotonic()
        while not self._parar.is_set():
            ahora = time.monotonic()
            if ahora < prox:
                self._parar.wait(min(prox - ahora, 0.02))
                continue
            prox += paso
            if prox < ahora - paso:
                prox = ahora
            try:
                self._una_captura()
            except Exception:
                log.exception("error procesando un frame")
                self._parar.wait(0.2)

    def _pedir_jpg(self, timeout=1.5):
        """Pide /capture al telefono. Devuelve (bytes o None, ms de latencia)."""
        t0 = time.monotonic()
        try:
            r = self.ses.get(self.base + "/capture", timeout=timeout)
            if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
                return r.content, (time.monotonic() - t0) * 1000.0
        except self.requests.RequestException:
            pass
        return None, None

    def _una_captura(self):
        jpg, lat = self._pedir_jpg()
        if jpg is None:
            self._parar.wait(0.15)
            return
        h = hashlib.md5(jpg).hexdigest()
        if h == self._hash:                      # mismo frame que el anterior: no sirve para medir movimiento
            return
        self._hash = h
        img = self.cv2.imdecode(self.np.frombuffer(jpg, self.np.uint8), self.cv2.IMREAD_REDUCED_GRAYSCALE_2)
        if img is None:
            return
        t = time.monotonic()
        with self.lock:
            hubo_corte = t - self._ultimo_ok > self.SEG_SIN_SENAL
            if hubo_corte:                       # tras un corte, el frame previo ya no sirve para correlacionar
                self.det.prev = None
                self.clf.q.clear()
        m = self.det.procesar(img, t)
        info = self.clf.actualizar(m)
        with self.lock:
            self._ultimo_ok = t
            self.latencia_ms = lat
            if self._t_frame:
                inst = 1.0 / max(1e-3, t - self._t_frame)
                self._fps_ema = inst if not self._fps_ema else 0.8 * self._fps_ema + 0.2 * inst
            self._t_frame, self.fps = t, self._fps_ema
            self._n_frames += 1
            self._ult_img, self._ult_m, self._ult_info, self._ult_jpg = img, m, info, jpg
            if self._calib_buf is not None:
                self._calib_buf.append(m)
            mm = self.medida
            if info["vel_mm_s"] is not None:
                mm["vel"] = info["vel_mm_s"] / 10.0
            if info["lateral_mm"] is not None:
                mm["lat"], mm["ang"] = info["lateral_mm"], info["angulo_deg"]
            if time.monotonic() >= self._obj_hasta:
                mm["dist"] = LIM["dist_base"]

    # ----- evaluacion del estado a 10 Hz -----
    def _hilo_eval(self):
        prox = time.monotonic()
        while not self._parar.is_set():
            prox += 0.1
            try:
                self._evaluar()
            except Exception:
                log.exception("error evaluando el estado")
            esp = prox - time.monotonic()
            if esp > 0:
                self._parar.wait(esp)
            else:
                prox = time.monotonic()

    def _estado_clf(self):
        e = self.clf.estado
        if e == "SIN_LINEAS":                    # hay frames pero sin lineas: se conserva el ultimo estado confirmado
            return self._ult_clf if not self.sin_calibrar else "CALIBRANDO"
        if e != "CALIBRANDO":
            self._ult_clf = e
        return e

    def _evaluar(self):
        ahora = time.monotonic()
        with self.lock:
            self.senal = (ahora - self._ultimo_ok) < self.SEG_SIN_SENAL
            self._avanzar_calibracion(ahora)
            if not self.senal:
                nuevo = "SIN_SENAL"
            elif self._calib_buf is not None or self.sin_calibrar:
                nuevo = "CALIBRANDO"
            elif ahora < self._obj_hasta:
                nuevo = "OBJETO_DETECTADO"
            else:
                nuevo = self._estado_clf()
            # candidato en curso del clasificador, para la barra de confirmacion
            cand = self.clf._cand
            if cand and cand != "SIN_LINEAS" and cand != self.estado and not self.sin_calibrar:
                self.cand = {"estado": cand, "n": int(self.clf._n), "need": int(self.clf.persist)}
            else:
                self.cand = {"estado": nuevo, "n": 0, "need": 1}
            self._aplicar_estado(nuevo)

    # ----- calibracion -----
    def _calibrar(self):
        """Mide `calib_s` segundos con la correa en condicion normal y recalcula umbrales.

        Usa calibrar() de deteccion.py con las Medida acumuladas del detector en marcha. No
        incluye una grabacion de correa detenida (se podria pasar como `detenida=` para fijar
        el piso del umbral de velocidad): ese es el punto de extension.
        """
        with self.lock:
            if self._calib_buf is not None:
                return False, "ya hay una calibración en curso"
            if not self.senal:
                return False, "sin imagen del teléfono"
            self._calib_buf = []
            self._calib_t0 = time.monotonic()
            self.error_calibracion = None
            self.calibrando = {"progreso": 0.0}
        return True, ""

    def _avanzar_calibracion(self, ahora):
        if self._calib_buf is None:
            self.calibrando = None
            return
        prog = (ahora - self._calib_t0) / self.calib_s
        if prog < 1.0:
            self.calibrando = {"progreso": round(prog, 3)}
            return
        buf, self._calib_buf, self.calibrando = self._calib_buf, None, None
        try:
            c = self.det_mod.calibrar(buf)
        except Exception as e:                   # pocas lineas, correa quieta, etc.
            self.error_calibracion = str(e)
            log.warning("calibración fallida: %s", e)
            return
        self.calib, self.sin_calibrar = c, False
        self.clf = self.det_mod.Clasificador(c)
        self._ult_clf = "NORMAL"
        self._actualizar_limites()
        if self.ruta_calib:
            try:
                c.guardar(self.ruta_calib)
            except OSError:
                log.exception("no pude guardar %s", self.ruta_calib)
        log.info("calibración lista: %s", self.limites)

    # ----- evento del ESP32 -----
    def evento_esp(self, distancia_mm, n=None):
        """POST /event: confirma el objeto, lo mantiene 4 s y guarda una foto del telefono."""
        with self.lock:
            self.esp_ultimo_ms = ahora_ms()
            self._obj_hasta = time.monotonic() + self.SEG_OBJETO
            self.medida["dist"] = float(distancia_mm)
            ya_abierto = self.estado == "OBJETO_DETECTADO"
        self._evaluar()
        with self.lock:
            ev = self._evento_abierto if self.estado == "OBJETO_DETECTADO" else None
            eid = ev["id"] if ev else None
        if eid and not ya_abierto:
            threading.Thread(target=self._foto_evento, args=(eid,), daemon=True).start()
        return eid

    def _foto_evento(self, eid):
        jpg, _ = self._pedir_jpg(timeout=1.5)     # captura inmediata
        if jpg is None:
            jpg = self._ult_jpg                   # respaldo: el ultimo frame recibido
        try:
            self._asignar_foto(eid, jpg)
        except OSError:
            log.exception("no pude guardar la foto del evento %s", eid)

    # ----- frame anotado -----
    def frame_jpg(self):
        with self.lock:
            n, img, m = self._n_frames, self._ult_img, self._ult_m
            estado = self.estado
            if self._cache_anot[0] == (n, estado):
                return self._cache_anot[1]
        if img is None:
            return None
        cv2, np = self.cv2, self.np
        g = self.det_mod.preparar(img)
        vis = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
        h, w = g.shape
        colores = {"NORMAL": (74, 138, 11), "DETENIDA": (42, 52, 214), "DESALINEADA": (0, 161, 242),
                   "OBJETO_DETECTADO": (239, 114, 0), "SIN_SENAL": (128, 106, 91), "CALIBRANDO": (128, 106, 91)}
        col = colores.get(estado, (128, 128, 128))
        if m is not None and m.lineas_ok:
            ym = (h - 1) / 2
            cx = (w - 1) / 2 + m.lateral_px
            pend = np.tan(np.radians(m.angulo_deg))
            for lado in (-0.5, 0.5):
                x_mid = cx + lado * m.dist_px
                p0 = (int(x_mid - pend * ym), 0)
                p1 = (int(x_mid + pend * (h - 1 - ym)), h - 1)
                cv2.line(vis, p0, p1, (0, 200, 255), 2)
        rotulo = estado.replace("_", " ")          # putText no dibuja acentos: los estados ya no los llevan
        cv2.rectangle(vis, (0, 0), (w, 30), col, -1)
        mm = self.medida
        txt = "%s   vel %.1f cm/s  lat %+.1f mm  ang %+.1f" % (rotulo, mm["vel"], mm["lat"], mm["ang"])
        cv2.putText(vis, txt, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 70])
        jpg = buf.tobytes() if ok else None
        with self.lock:
            self._cache_anot = ((n, estado), jpg)
        return jpg
