#!/usr/bin/env python3
"""Analisis offline de carpetas grabadas con grabar.py.

    python3 analizar.py medir    CARPETA [-o medidas.csv]
    python3 analizar.py calibrar CARPETA_NORMAL [--detenida CARPETA] -o calibracion.json
    python3 analizar.py evaluar  CARPETA -c calibracion.json [-o estados.csv]
"""
import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter

import cv2
import numpy as np

import deteccion as D


def cargar_carpeta(carpeta, fps=10.0):
    ruta = os.path.join(carpeta, "indice.csv")
    if os.path.exists(ruta):
        with open(ruta) as f:
            return [(float(r["t_s"]), os.path.join(carpeta, r["archivo"])) for r in csv.DictReader(f)]
    arch = sorted(glob.glob(os.path.join(carpeta, "*.jpg")))
    return [(i / fps, p) for i, p in enumerate(arch)]


def cargar_meta(carpeta):
    try:
        with open(os.path.join(carpeta, "meta.json")) as f:
            return json.load(f)
    except OSError:
        return {}


def medir_carpeta(carpeta, fps=10.0):
    det = D.Detector()
    out = []
    for t, p in cargar_carpeta(carpeta, fps):
        img = cv2.imread(p)
        if img is None:
            continue
        out.append(det.procesar(img, t))
    return out


def verdad_de(meta, carpeta, n):
    if "etiquetas_frame" in meta:
        return meta["etiquetas_frame"][:n]
    et = meta.get("etiqueta") or os.path.basename(carpeta.rstrip("/")).split("_")[0]
    if et.startswith("desalineada"):
        et = "desalineada"
    return [et] * n if et in ("normal", "detenida", "desalineada") else None


def resumen_medidas(ms, mm_px):
    v = D._vel_ventana(ms, mm_px, 5)
    v = [x for x in v if x is not None]
    ok = [m for m in ms if m.lineas_ok]
    print(f"frames: {len(ms)}  con lineas: {len(ok)}")
    if ok:
        lat = np.array([m.lateral_px * mm_px for m in ok])
        ang = np.array([m.angulo_deg for m in ok])
        print(f"lateral mm: mediana {np.median(lat):+.2f}  std {lat.std():.2f}")
        print(f"angulo deg: mediana {np.median(ang):+.2f}  std {ang.std():.2f}")
        print(f"separacion lineas: {np.median([m.dist_px for m in ok]):.1f} px "
              f"(mm/px estimado {np.median([D.DIST_LINEAS_MM / m.dist_px for m in ok]):.3f})")
    if v:
        print(f"velocidad mm/s: mediana {np.median(v):.1f}  min {min(v):.1f}  max {max(v):.1f}")
    resp = [m.resp for m in ms if m.resp == m.resp]
    if resp:
        print(f"respuesta phaseCorrelate: mediana {np.median(resp):.2f}  min {min(resp):.2f}")


def escribir_csv(ruta, filas, campos):
    with open(ruta, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)


def cmd_medir(a):
    ms = medir_carpeta(a.carpeta, a.fps)
    mm = a.mm_px
    resumen_medidas(ms, mm)
    if a.o:
        escribir_csv(a.o, [m.__dict__ for m in ms], list(D.Medida().__dict__.keys()))


def cmd_calibrar(a):
    normal = medir_carpeta(a.carpeta, a.fps)
    det = medir_carpeta(a.detenida, a.fps) if a.detenida else None
    c = D.calibrar(normal, det)
    c.guardar(a.o)
    print(json.dumps(c.__dict__, indent=2))
    print(f"Guardado en {a.o}")


def cmd_evaluar(a):
    c = D.Calibracion.cargar(a.c)
    ms = medir_carpeta(a.carpeta, a.fps)
    clf = D.Clasificador(c, persist=a.persist)
    infos = [clf.actualizar(m) for m in ms]
    resumen_medidas(ms, c.mm_por_px)
    cont = Counter(i["estado"] for i in infos)
    print("estados confirmados:", dict(cont))
    meta = cargar_meta(a.carpeta)
    ver = verdad_de(meta, a.carpeta, len(infos))
    if ver:
        mapa = {"NORMAL": "normal", "DETENIDA": "detenida", "DESALINEADA": "desalineada"}
        # se ignoran los primeros frames y los cercanos a un cambio de verdad
        cambios = [i for i in range(1, len(ver)) if ver[i] != ver[i - 1]]
        tol = a.tolerancia
        valid = [i for i in range(a.saltar, len(ver))
                 if all(abs(i - c_) > tol for c_ in cambios)]
        aciertos = sum(1 for i in valid if mapa.get(infos[i]["estado"]) == ver[i])
        print(f"precision (sin {a.saltar} iniciales y +-{tol} frames de cambios): "
              f"{aciertos}/{len(valid)} = {100 * aciertos / max(1, len(valid)):.1f}%")
        fallos = Counter((ver[i], infos[i]["estado"]) for i in valid
                         if mapa.get(infos[i]["estado"]) != ver[i])
        if fallos:
            print("errores (verdad, estado):", dict(fallos))
    if a.o:
        escribir_csv(a.o, infos, list(infos[0].keys()))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument("--fps", type=float, default=10.0, help="si la carpeta no tiene indice.csv")
    p = sub.add_parser("medir", parents=[comun])
    p.add_argument("carpeta")
    p.add_argument("-o")
    p.add_argument("--mm-px", type=float, default=0.585)
    p.set_defaults(f=cmd_medir)
    p = sub.add_parser("calibrar", parents=[comun])
    p.add_argument("carpeta")
    p.add_argument("--detenida")
    p.add_argument("-o", default="calibracion.json")
    p.set_defaults(f=cmd_calibrar)
    p = sub.add_parser("evaluar", parents=[comun])
    p.add_argument("carpeta")
    p.add_argument("-c", required=True)
    p.add_argument("-o")
    p.add_argument("--persist", type=int, default=3)
    p.add_argument("--saltar", type=int, default=8)
    p.add_argument("--tolerancia", type=int, default=8)
    p.set_defaults(f=cmd_evaluar)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
