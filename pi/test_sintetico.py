#!/usr/bin/env python3
"""Prueba con imagenes sinteticas: genera escenarios, calibra y evalua.

    python3 test_sintetico.py [--dir /tmp/sint]
"""
import argparse
import os
import subprocess
import sys

import cv2
import numpy as np

import deteccion as D
import simulador as S
import analizar as A

MM_PX_TRABAJO = S.MM_PX * S.W / D.ANCHO_TRABAJO  # 0.585


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/sint")
    ap.add_argument("--reusar", action="store_true")
    a = ap.parse_args()
    esc = S.Escena(seed=1)
    E = {  # nombre: (segmentos, kwargs)
        "normal_100": ([(6, 100, 0, 0)], {}),
        "normal_60": ([(6, 60, 0.4, 0.1)], {}),
        "normal_150": ([(6, 150, -0.4, -0.1)], {}),
        "normal_100_jitter": ([(6, 100, 0, 0)], {"jitter_t": 0.03}),
        "normal_luz": ([(6, 100, 0, 0)], {"exp_s": 0.005}),
        "detenida": ([(6, 0, 0, 0)], {}),
        "desalineada_der": ([(6, 100, 8, 2)], {}),
        "desalineada_izq": ([(6, 100, -8, -2)], {}),
        "desalineada_leve": ([(6, 100, 4, 0)], {}),
        "desalineada_angulo": ([(6, 100, 0, 1.6)], {}),
        "transicion": ([(3, 100, 0, 0), (4, 0, 0, 0), (3, 100, 0, 0),
                        (4, 100, 8, 2), (3, 100, 0, 0)], {}),
    }
    if not a.reusar:
        for n, (seg, kw) in E.items():
            print("generando", n)
            S.generar(os.path.join(a.dir, n), seg, n, escena=esc, seed=sum(map(ord, n)), **kw)

    c = D.calibrar(A.medir_carpeta(os.path.join(a.dir, "normal_100")),
                   A.medir_carpeta(os.path.join(a.dir, "detenida")))
    c.guardar(os.path.join(a.dir, "calib.json"))
    print("\nCalibracion:", {k: round(v, 3) for k, v in c.__dict__.items()})
    print(f"mm/px esperado {MM_PX_TRABAJO:.3f}  estimado {c.mm_por_px:.3f}")

    fallos = 0
    for n, (seg, kw) in E.items():
        print(f"\n=== {n}")
        ms = A.medir_carpeta(os.path.join(a.dir, n))
        v = [x for x in D._vel_ventana(ms, c.mm_por_px, 5) if x is not None]
        vel_ver = seg[0][1]
        if n.startswith("normal") or n.startswith("desalineada"):
            err = 100 * (np.median(v) - vel_ver) / vel_ver
            print(f"velocidad: real {vel_ver} mm/s, medida {np.median(v):.1f} ({err:+.1f}%)")
            if abs(err) > 5:
                print("FALLO: error de velocidad > 5%")
                fallos += 1
        clf = D.Clasificador(c)
        infos = [clf.actualizar(m) for m in ms]
        import json
        meta = json.load(open(os.path.join(a.dir, n, "meta.json")))["etiquetas_frame"]
        mapa = {"NORMAL": "normal", "DETENIDA": "detenida", "DESALINEADA": "desalineada"}
        cam = [i for i in range(1, len(meta)) if meta[i] != meta[i - 1]]
        valid = [i for i in range(8, len(meta)) if all(abs(i - x) > 8 for x in cam)]
        ok = sum(mapa.get(infos[i]["estado"]) == meta[i] for i in valid)
        pr = 100 * ok / len(valid)
        lat = [m.lateral_px * c.mm_por_px for m in ms if m.lineas_ok]
        ang = [m.angulo_deg for m in ms if m.lineas_ok]
        print(f"lateral mediana {np.median(lat):+.2f} mm, angulo {np.median(ang):+.2f} deg, "
              f"precision {pr:.1f}%")
        if pr < 97:
            print("FALLO: precision < 97%", [(meta[i], infos[i]["estado"]) for i in valid
                                             if mapa.get(infos[i]["estado"]) != meta[i]][:5])
            fallos += 1
    print("\nRESULTADO:", "OK" if fallos == 0 else f"{fallos} fallos")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
