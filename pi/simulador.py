"""Simulador de correa a escala: genera carpetas de frames con el mismo formato que grabar.py.

Geometria (coincide con el plan): correa de 150 mm, lineas longitudinales de 8 mm con
centro a 61 mm del eje, barras transversales de 6 mm con espaciado irregular
(periodo 434 mm), puntos de 5 mm. Camara mirando hacia abajo, 0.26 mm/px, 1080x1440.
"""
import csv
import json
import math
import os

import cv2
import numpy as np

MM_PX = 0.26
W, H = 1080, 1440
GAPS = [35, 62, 48, 85, 41, 70, 55, 38]
PERIODO = float(sum(GAPS))  # 434 mm
POS_BARRAS = np.concatenate([[0], np.cumsum(GAPS[:-1])]).astype(float)
PUNTOS_U = [-30, 25, -10, 38, -40, 12, 30]
PUNTOS = [(PUNTOS_U[i], POS_BARRAS[i] + GAPS[i] / 2) for i in range(7)]
RES1D = 0.1


class Escena:
    def __init__(self, seed=0, mm_px=MM_PX, w=W, h=H):
        rng = np.random.default_rng(seed)
        self.mm_px, self.w, self.h = mm_px, w, h
        xs = (np.arange(w) - (w - 1) / 2) * mm_px
        ys = (np.arange(h) - (h - 1) / 2) * mm_px
        X, Y = np.meshgrid(xs.astype(np.float32), ys.astype(np.float32))
        self.X, self.Y = X, Y
        # fondo oscuro estatico con textura y rectangulos tenues
        peq = rng.normal(0, 1, (36, 48)).astype(np.float32)
        bg = cv2.resize(peq, (w, h), interpolation=cv2.INTER_CUBIC) * 10 + 50
        bg += rng.normal(0, 3, (h, w)).astype(np.float32)
        for (x0, y0, x1, y1, v) in [(30, 300, 150, 520, 115), (900, 900, 1050, 1100, 100),
                                    (60, 1150, 200, 1300, 90), (880, 100, 1040, 260, 105)]:
            bg[y0:y1, x0:x1] = v
        self.bg = np.clip(bg, 25, 125).astype(np.float32)
        n = int(PERIODO / RES1D)
        t = np.arange(n) * RES1D
        d = np.abs(t[:, None] - POS_BARRAS[None, :])
        d = np.minimum(d, PERIODO - d)
        self.barras1d = (d < 3.0).any(axis=1)
        self.n1d = n
        self.grad = (1 + 0.15 * (self.Y / (h * mm_px / 2))).astype(np.float32)

    def render(self, s, lat=0.0, ang_deg=0.0, vel_mm_s=0.0, exp_s=0.03, rng=None, calidad=85):
        rng = rng or np.random.default_rng(0)
        th = math.radians(ang_deg)
        c, sn = math.cos(th), math.sin(th)
        dX = self.X - lat
        u = dX * c - self.Y * sn
        v = dX * sn + self.Y * c + s
        au = np.abs(u)
        img = self.bg.copy()
        belt = au <= 75
        img[belt] = 235
        dark = np.abs(au - 61) <= 4
        vm = np.mod(v, PERIODO)
        idx = (vm * (1 / RES1D)).astype(np.int32) % self.n1d
        dark |= (au < 57) & self.barras1d[idx]
        for du, dv in PUNTOS:
            dd = np.mod(vm - dv + PERIODO / 2, PERIODO) - PERIODO / 2
            dark |= (u - du) ** 2 + dd ** 2 <= 2.5 ** 2
        img[dark & belt] = 18
        L = int(round(vel_mm_s * exp_s / self.mm_px))
        if L >= 2:
            img = cv2.filter2D(img, -1, np.ones((L, 1), np.float32) / L)
        img = cv2.GaussianBlur(img, (0, 0), 1.2)
        img = img * self.grad + rng.normal(0, 3, img.shape).astype(np.float32)
        img = np.clip(img, 0, 255).astype(np.uint8)
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, calidad])
        return buf.tobytes()


def etiqueta_verdad(vel, lat, ang):
    if abs(vel) < 1.0:
        return "detenida"
    if abs(lat) > 3.0 or abs(ang) > 1.0:
        return "desalineada"
    return "normal"


def generar(carpeta, segmentos, etiqueta, fps=10.0, exp_s=0.03, seed=0, jitter_t=0.0,
            jitter_lat=0.15, jitter_ang=0.05, escena=None):
    """segmentos: lista de (duracion_s, vel_mm_s, lat_mm, ang_deg). Devuelve lista de verdades."""
    os.makedirs(carpeta, exist_ok=True)
    escena = escena or Escena(seed=1)
    rng = np.random.default_rng(seed)
    filas, verdad = [], []
    s, k = 0.0, 0
    dt = 1.0 / fps
    for dur, vel, lat, ang in segmentos:
        for _ in range(int(round(dur * fps))):
            la = lat + rng.normal(0, jitter_lat)
            an = ang + rng.normal(0, jitter_ang)
            jpg = escena.render(s, la, an, vel, exp_s, rng)
            nombre = f"f_{k:06d}.jpg"
            with open(os.path.join(carpeta, nombre), "wb") as f:
                f.write(jpg)
            t = k * dt + (rng.uniform(-jitter_t, jitter_t) if jitter_t else 0.0)
            filas.append((k, round(t, 4), nombre, len(jpg)))
            verdad.append(etiqueta_verdad(vel, lat, ang))
            s += vel * dt
            k += 1
    with open(os.path.join(carpeta, "indice.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "t_s", "archivo", "bytes"])
        w.writerows(filas)
    with open(os.path.join(carpeta, "meta.json"), "w") as f:
        json.dump({"etiqueta": etiqueta, "simulado": True, "etiquetas_frame": verdad}, f)
    return verdad
