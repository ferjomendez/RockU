"""Deteccion de velocidad/detencion y alineacion de la correa a partir de frames.

Uso basico:
    det = Detector()
    m = det.procesar(frame_bgr, t_segundos)      # Medida
    clf = Clasificador(calibracion)
    info = clf.actualizar(m)                      # dict con estado confirmado
"""
import json
import math
from collections import deque
from dataclasses import dataclass, asdict

import cv2
import numpy as np

ANCHO_TRABAJO = 480
DIST_LINEAS_MM = 122.0      # separacion entre centros de las dos lineas (150 - 2*(10+4))
N_BANDAS = 6
FRACCION_ROI = 0.8          # ancho del ROI de movimiento respecto a la separacion de lineas
RESP_MIN = 0.03             # respuesta minima de phaseCorrelate para aceptar el desplazamiento


def preparar(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    if w != ANCHO_TRABAJO:
        s = ANCHO_TRABAJO / w
        gray = cv2.resize(gray, (ANCHO_TRABAJO, int(round(h * s))), interpolation=cv2.INTER_AREA)
    return gray


def _centros_en_perfil(banda):
    """Centros (x1, x2) de las dos lineas oscuras interiores en una banda horizontal, o None."""
    perfil = np.median(banda, axis=0).astype(np.float32)
    perfil = cv2.blur(perfil.reshape(1, -1), (5, 1)).ravel()
    if perfil.max() - perfil.min() < 60:
        return None
    p8 = np.clip(perfil, 0, 255).astype(np.uint8).reshape(1, -1)
    thr, _ = cv2.threshold(p8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    oscuro = perfil < thr
    n = len(perfil)
    d = np.diff(np.concatenate([[0], oscuro.astype(np.int8), [0]]))
    ini = np.where(d == 1)[0]
    fin = np.where(d == -1)[0] - 1
    cand = []
    for s, e in zip(ini, fin):
        if s == 0 or e == n - 1:
            continue  # toca el borde: es fondo
        ancho = e - s + 1
        if ancho < 3 or ancho > 0.1 * n:
            continue
        cand.append((ancho, s, e))
    if len(cand) < 2:
        return None
    cand = sorted(cand, reverse=True)[:2]
    cand = sorted(cand, key=lambda c: c[1])
    centros = []
    for _, s, e in cand:
        x = np.arange(s, e + 1)
        w = np.clip(thr - perfil[s:e + 1], 0, None)
        if w.sum() <= 0:
            return None
        centros.append(float((w * x).sum() / w.sum()))
    if centros[1] - centros[0] < 0.15 * n:
        return None
    return centros[0], centros[1]


def medir_alineacion(gray):
    h, w = gray.shape
    alto = h // N_BANDAS
    ys, c1, c2 = [], [], []
    for i in range(N_BANDAS):
        y0, y1 = i * alto, (i + 1) * alto
        r = _centros_en_perfil(gray[y0:y1])
        if r:
            ys.append((y0 + y1 - 1) / 2)
            c1.append(r[0])
            c2.append(r[1])
    if len(ys) < 3:
        return None
    ys, c1, c2 = np.array(ys), np.array(c1), np.array(c2)
    a1, b1 = np.polyfit(ys, c1, 1)
    a2, b2 = np.polyfit(ys, c2, 1)
    ym = (h - 1) / 2
    x1, x2 = a1 * ym + b1, a2 * ym + b2
    return dict(lateral_px=(x1 + x2) / 2 - (w - 1) / 2,
                angulo_deg=math.degrees(math.atan((a1 + a2) / 2)),
                dist_px=x2 - x1, centro_px=(x1 + x2) / 2)


@dataclass
class Medida:
    t: float = 0.0
    dt: float = float("nan")
    dx_px: float = float("nan")
    dy_px: float = float("nan")
    resp: float = float("nan")
    lateral_px: float = float("nan")
    angulo_deg: float = float("nan")
    dist_px: float = float("nan")
    lineas_ok: bool = False


class Detector:
    def __init__(self):
        self.prev = None
        self.prev_t = None
        self._win = {}

    def _hann(self, shape):
        if shape not in self._win:
            self._win[shape] = cv2.createHanningWindow((shape[1], shape[0]), cv2.CV_32F)
        return self._win[shape]

    def procesar(self, img, t):
        gray = preparar(img)
        h, w = gray.shape
        al = medir_alineacion(gray)
        m = Medida(t=float(t))
        if al:
            half = FRACCION_ROI * al["dist_px"] / 2
            x0, x1 = int(round(al["centro_px"] - half)), int(round(al["centro_px"] + half))
            m.lateral_px, m.angulo_deg, m.dist_px, m.lineas_ok = (
                al["lateral_px"], al["angulo_deg"], al["dist_px"], True)
        else:
            x0, x1 = w // 4, 3 * w // 4
        x0, x1 = max(0, x0), min(w, x1)
        if self.prev is not None and self.prev.shape == gray.shape and x1 - x0 > 16:
            a = self.prev[:, x0:x1].astype(np.float32)
            b = gray[:, x0:x1].astype(np.float32)
            a -= a.mean()
            b -= b.mean()
            (dx, dy), resp = cv2.phaseCorrelate(a, b, self._hann(a.shape))
            m.dx_px, m.dy_px, m.resp = float(dx), float(dy), float(resp)
            m.dt = float(t - self.prev_t)
        self.prev, self.prev_t = gray, t
        return m


@dataclass
class Calibracion:
    mm_por_px: float = 0.585
    lateral_ref_mm: float = 0.0
    angulo_ref_deg: float = 0.0
    ruido_lateral_mm: float = 0.0
    ruido_angulo_deg: float = 0.0
    umbral_vel_mm_s: float = 5.0
    umbral_lateral_mm: float = 3.0
    umbral_angulo_deg: float = 1.0
    vel_nominal_mm_s: float = 0.0
    fps: float = 10.0

    def guardar(self, ruta):
        with open(ruta, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @staticmethod
    def cargar(ruta):
        with open(ruta) as f:
            return Calibracion(**json.load(f))


def _vel_ventana(medidas, mm_px, ventana):
    """Velocidad (mm/s) por ventana deslizante: suma|dy| / suma dt, robusta al jitter de tiempos."""
    q = deque(maxlen=ventana)
    out = []
    for m in medidas:
        if m.resp == m.resp and m.resp >= RESP_MIN and m.dt > 0:
            q.append((abs(m.dy_px), m.dt))
        out.append(sum(a for a, _ in q) * mm_px / sum(b for _, b in q)
                   if len(q) >= 2 else None)
    return out


def calibrar(normal, detenida=None, ventana=5):
    ok = [m for m in normal if m.lineas_ok]
    if len(ok) < 5:
        raise ValueError("Muy pocos frames con lineas detectadas en la grabacion normal")
    mm_px = float(np.median([DIST_LINEAS_MM / m.dist_px for m in ok]))
    lat = np.array([m.lateral_px * mm_px for m in ok])
    ang = np.array([m.angulo_deg for m in ok])
    val = [m for m in normal if m.resp == m.resp and m.resp >= RESP_MIN and m.dt > 0]
    if len(val) < 5:
        raise ValueError("Sin medidas de movimiento validas en la grabacion normal")
    nominal = sum(abs(m.dy_px) for m in val) * mm_px / sum(m.dt for m in val)
    piso = 2.0
    if detenida:
        vs = [v for v in _vel_ventana(detenida, mm_px, ventana) if v is not None]
        if vs:
            piso = max(piso, 3.0 * max(vs))
    umbral = max(0.3 * nominal, piso)
    dts = [m.dt for m in normal if m.dt == m.dt and m.dt > 0]
    c = Calibracion(
        mm_por_px=mm_px,
        lateral_ref_mm=float(np.median(lat)), angulo_ref_deg=float(np.median(ang)),
        ruido_lateral_mm=float(lat.std()), ruido_angulo_deg=float(ang.std()),
        umbral_vel_mm_s=float(umbral),
        umbral_lateral_mm=float(max(3.0, 6 * lat.std())),
        umbral_angulo_deg=float(max(1.0, 6 * ang.std())),
        vel_nominal_mm_s=float(nominal),
        fps=float(1.0 / np.median(dts)) if dts else 10.0)
    if umbral > 0.6 * nominal:
        print(f"AVISO: el umbral de detencion ({umbral:.1f} mm/s) es alto respecto a la "
              f"velocidad nominal ({nominal:.1f} mm/s)")
    return c


class Clasificador:
    """Estado crudo por frame + confirmacion por persistencia."""

    def __init__(self, calib, persist=3, ventana=5):
        self.c = calib
        self.persist = persist
        self.q = deque(maxlen=ventana)
        self.estado = "CALIBRANDO"
        self._cand, self._n = None, 0

    def actualizar(self, m):
        c = self.c
        if m.resp == m.resp and m.resp >= RESP_MIN and m.dt > 0:
            self.q.append((abs(m.dy_px), m.dt))
        vel = (sum(a for a, _ in self.q) * c.mm_por_px / sum(b for _, b in self.q)
               if len(self.q) >= 2 else None)
        dlat = dang = None
        if not m.lineas_ok:
            crudo = "SIN_LINEAS"
        else:
            dlat = m.lateral_px * c.mm_por_px - c.lateral_ref_mm
            dang = m.angulo_deg - c.angulo_ref_deg
            if vel is not None and vel < c.umbral_vel_mm_s:
                crudo = "DETENIDA"
            elif abs(dlat) > c.umbral_lateral_mm or abs(dang) > c.umbral_angulo_deg:
                crudo = "DESALINEADA"
            else:
                crudo = "NORMAL"
        if self.estado == "CALIBRANDO" and crudo == self._cand and self._n + 1 >= self.persist:
            self.estado = crudo
        elif crudo == self.estado:
            self._cand, self._n = None, 0
        elif crudo == self._cand:
            self._n += 1
            if self._n >= self.persist:
                self.estado, self._cand, self._n = crudo, None, 0
        else:
            self._cand, self._n = crudo, 1
        return dict(t=m.t, crudo=crudo, estado=self.estado, vel_mm_s=vel,
                    lateral_mm=dlat, angulo_deg=dang)
