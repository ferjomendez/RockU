#!/usr/bin/env python3
"""Graba frames etiquetados desde la app del telefono (Raspberry Pi o PC).

Ejemplos:
    python3 grabar.py normal --segundos 20
    python3 grabar.py detenida --segundos 10
    python3 grabar.py desalineada_izq --segundos 15 --url http://192.168.1.84:8080

Crea  <salida>/<etiqueta>_<fecha>/  con frames f_000000.jpg..., indice.csv y meta.json.
Los frames identicos consecutivos (el telefono no entrego uno nuevo) se descartan.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("etiqueta", help="normal | detenida | desalineada_izq | desalineada_der | ...")
    ap.add_argument("--url", default="http://192.168.1.84:8080")
    ap.add_argument("--segundos", type=float, default=20)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--salida", default=os.path.expanduser("~/correa/videos"))
    ap.add_argument("--espera", type=float, default=3, help="segundos antes de empezar")
    a = ap.parse_args()

    base = a.url.rstrip("/")
    if base.endswith("/capture"):
        base = base[:-len("/capture")]
    carpeta = os.path.join(a.salida, f"{a.etiqueta}_{datetime.now():%Y%m%d_%H%M%S}")
    os.makedirs(carpeta, exist_ok=True)
    ses = requests.Session()

    cfg = {}
    try:
        cfg = ses.get(base + "/config", timeout=3).json()
    except Exception as e:
        print(f"AVISO: no pude leer /config ({e})")
    if cfg and not cfg.get("locked"):
        print("AVISO: la camara NO tiene 3A bloqueado; la exposicion puede variar durante la grabacion.")

    if a.espera > 0:
        print(f"Empieza en {a.espera:.0f} s...")
        time.sleep(a.espera)
    print(f"Grabando '{a.etiqueta}' durante {a.segundos:.0f} s en {carpeta}")

    filas, prev_hash, dup, fallos = [], None, 0, 0
    t0 = time.monotonic()
    paso = 1.0 / a.fps
    proximo = t0
    while True:
        ahora = time.monotonic()
        if ahora - t0 >= a.segundos:
            break
        if ahora < proximo:
            time.sleep(min(proximo - ahora, 0.01))
            continue
        proximo += paso
        if proximo < ahora - paso:
            proximo = ahora
        try:
            r = ses.get(base + "/capture", timeout=2)
            t = time.monotonic() - t0
            if r.status_code != 200 or r.content[:2] != b"\xff\xd8":
                fallos += 1
                continue
        except requests.RequestException:
            fallos += 1
            continue
        h = hashlib.md5(r.content).hexdigest()
        if h == prev_hash:
            dup += 1
            continue
        prev_hash = h
        nombre = f"f_{len(filas):06d}.jpg"
        with open(os.path.join(carpeta, nombre), "wb") as f:
            f.write(r.content)
        filas.append((len(filas), round(t, 4), nombre, len(r.content)))

    with open(os.path.join(carpeta, "indice.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "t_s", "archivo", "bytes"])
        w.writerows(filas)
    dur = filas[-1][1] - filas[0][1] if len(filas) > 1 else 0
    fps_real = (len(filas) - 1) / dur if dur > 0 else 0
    with open(os.path.join(carpeta, "meta.json"), "w") as f:
        json.dump({"etiqueta": a.etiqueta, "url": base, "config": cfg,
                   "frames": len(filas), "duplicados": dup, "fallos": fallos,
                   "fps_real": round(fps_real, 2)}, f, indent=1)
    print(f"Listo: {len(filas)} frames, {fps_real:.1f} fps reales, {dup} duplicados, {fallos} fallos")
    if not filas:
        sys.exit(1)


if __name__ == "__main__":
    main()
