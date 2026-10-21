#!/usr/bin/env python3
"""Metricas del sistema de deteccion (precision, recall, F1, matriz de confusion, latencia).

El detector es de vision clasica (no se entrena): se CALIBRA con una grabacion normal y una
detenida, y se EVALUA sobre escenas distintas (otras velocidades, fondos, ruido, desalineaciones).
Hasta tener grabaciones reales de la correa, los datos vienen del simulador (simulador.py).

    python3 evaluar_metricas.py generar [--dir D] [--presupuesto 140]   # reanudable
    python3 evaluar_metricas.py evaluar [--dir D] [--salida docs/metricas]
    python3 evaluar_metricas.py evaluar --real CARPETA_NORMAL --real-det CARPETA_DET --real-test C1 C2 ...
"""
import argparse, csv, json, math, os, sys, time
from collections import Counter
from multiprocessing import Pool

import numpy as np

import deteccion as D
import simulador as S
import analizar as A

CLASES = ["normal", "detenida", "desalineada"]
MAPA = {"NORMAL": "normal", "DETENIDA": "detenida", "DESALINEADA": "desalineada"}
SALTAR, TOL, PERSIST, FPS = 8, 8, 3, 10.0


def especificaciones():
    E = {}
    E["cal_normal"] = dict(g="cal", segs=[(6, 100, 0, 0)], esc=1, seed=101)
    E["cal_detenida"] = dict(g="cal", segs=[(6, 0, 0, 0)], esc=1, seed=102)
    ls = [(0, 0), (0.4, 0.1), (-0.4, -0.1), (0.2, 0), (-0.2, 0.05)]
    for k, v in enumerate([60, 80, 100, 130, 150]):
        E[f"normal_{v}"] = dict(g="normal", segs=[(6, v, *ls[k])], esc=1 + k % 3, seed=200 + k)
    E["normal_jitter"] = dict(g="normal", segs=[(6, 100, 0, 0)], esc=2, seed=210, kw=dict(jitter_t=0.03))
    E["normal_exp5ms"] = dict(g="normal", segs=[(6, 100, 0, 0)], esc=3, seed=211, kw=dict(exp_s=0.005))
    E["normal_150_jit_exp"] = dict(g="normal", segs=[(6, 150, 0.2, 0)], esc=1, seed=212,
                                   kw=dict(jitter_t=0.03, exp_s=0.005))
    for k in range(3):
        E[f"detenida_{k}"] = dict(g="detenida", segs=[(6, 0, 0, 0)], esc=1 + k, seed=300 + k)
    des = [(4, 0), (6, 0), (8, 2), (-4, 0), (-6, 0), (-8, -2), (0, 1.6), (0, -1.6), (0, 2.5), (0.5, -2)]
    for k, (la, an) in enumerate(des):
        E[f"desal_{k}_lat{la}_ang{an}"] = dict(g="desalineada", segs=[(6, 100, la, an)],
                                               esc=1 + k % 3, seed=400 + k)
    E["trans_a"] = dict(g="transicion", esc=1, seed=500,
                        segs=[(3, 100, 0, 0), (4, 0, 0, 0), (3, 100, 0, 0), (4, 100, 8, 2), (3, 100, 0, 0)])
    E["trans_b"] = dict(g="transicion", esc=2, seed=501,
                        segs=[(3, 130, 0.2, 0), (3, 0, 0, 0), (3, 130, 0.2, 0), (3, 130, -6, 0), (3, 130, 0.2, 0)])
    for la in [0, 1, 2, 2.5, 3, 3.5, 4, 5, 6, 8]:
        E[f"blat_{la}"] = dict(g="barrido_lat", x=la, segs=[(2.5, 100, la, 0)], esc=1, seed=600 + int(la * 10))
    for an in [0, 0.4, 0.8, 1.0, 1.2, 1.5, 2, 3]:
        E[f"bang_{an}"] = dict(g="barrido_ang", x=an, segs=[(2.5, 100, 0, an)], esc=1, seed=700 + int(an * 10))
    for v in [0, 1, 2, 5, 10, 20, 30, 50, 100]:
        E[f"bvel_{v}"] = dict(g="barrido_vel", x=v, segs=[(2.5, v, 0, 0)], esc=1, seed=800 + v)
    return E


_ESC = {}


def _gen(args):
    nombre, spec, base = args
    ruta = os.path.join(base, nombre)
    if spec["esc"] not in _ESC:
        _ESC[spec["esc"]] = S.Escena(seed=spec["esc"])
    S.generar(ruta, spec["segs"], nombre, escena=_ESC[spec["esc"]], seed=spec["seed"], **spec.get("kw", {}))
    return nombre


def cmd_generar(a):
    E = especificaciones()
    pend = [(n, s, a.dir) for n, s in E.items() if not os.path.exists(os.path.join(a.dir, n, "meta.json"))]
    print(f"pendientes: {len(pend)} de {len(E)}")
    t0 = time.time()
    with Pool(2) as p:
        while pend and time.time() - t0 < a.presupuesto:
            lote, pend = pend[:2], pend[2:]
            for n in p.map(_gen, lote):
                print("ok", n, f"{time.time() - t0:.0f}s", flush=True)
    print("faltan:", len(pend))


def verdad_frames(spec, n):
    return [S.etiqueta_verdad(v, la, an) for dur, v, la, an in spec["segs"]
            for _ in range(int(round(dur * FPS)))][:n]


def prf(conf):
    out = {}
    for c in CLASES:
        tp = conf[c][c]
        fp = sum(conf[o][c] for o in CLASES if o != c)
        fn = sum(conf[c][p] for p in CLASES + ["otro"] if p != c)
        p_ = tp / (tp + fp) if tp + fp else float("nan")
        r_ = tp / (tp + fn) if tp + fn else float("nan")
        f = 2 * p_ * r_ / (p_ + r_) if p_ == p_ and r_ == r_ and p_ + r_ else float("nan")
        out[c] = dict(precision=p_, recall=r_, f1=f, soporte=tp + fn)
    return out


def correr(carpeta, calib, ver=None):
    ms = A.medir_carpeta(carpeta)
    clf = D.Clasificador(calib, persist=PERSIST)
    infos = [clf.actualizar(m) for m in ms]
    return ms, infos


def cmd_evaluar(a):
    E = especificaciones()
    if a.real:
        evaluar_real(a)
        return
    faltan = [n for n in E if not os.path.exists(os.path.join(a.dir, n, "meta.json"))]
    if faltan:
        sys.exit(f"faltan escenarios ({len(faltan)}); corre 'generar' de nuevo")
    cal = D.calibrar(A.medir_carpeta(os.path.join(a.dir, "cal_normal")),
                     A.medir_carpeta(os.path.join(a.dir, "cal_detenida")))
    print("calibracion:", {k: round(v, 3) for k, v in cal.__dict__.items()})
    conf_f = {c: Counter() for c in CLASES}   # con exclusion de transiciones (como analizar.py)
    conf_s = {c: Counter() for c in CLASES}   # estricto: solo se saltan los primeros frames
    filas, lat_err, ang_err, vel_err, barr = [], [], [], [], {"barrido_lat": [], "barrido_ang": [], "barrido_vel": []}
    lat_lat = []
    lats = {}
    for n, s in E.items():
        if s["g"] == "cal":
            continue
        ms, infos = correr(os.path.join(a.dir, n), cal)
        ver = verdad_frames(s, len(infos))
        pred = [MAPA.get(i["estado"], "otro") for i in infos]
        if s["g"].startswith("barrido"):
            idx = range(SALTAR, len(infos))
            cnt = Counter(pred[i] for i in idx)
            tot = sum(cnt.values())
            barr[s["g"]].append(dict(x=s["x"], **{k: cnt.get(k, 0) / tot for k in CLASES + ["otro"]}))
            continue
        cambios = [i for i in range(1, len(ver)) if ver[i] != ver[i - 1]]
        val_f = [i for i in range(SALTAR, len(ver)) if all(abs(i - c) > TOL for c in cambios)]
        val_s = list(range(SALTAR, len(ver)))
        for i in val_f:
            conf_f[ver[i]][pred[i]] += 1
        for i in val_s:
            conf_s[ver[i]][pred[i]] += 1
        acc = sum(pred[i] == ver[i] for i in val_f) / len(val_f)
        fila = dict(escenario=n, grupo=s["g"], frames=len(ver), validos=len(val_f), exactitud=round(acc, 4))
        # error de velocidad / lateral / angulo (frame a frame, contra lo inyectado)
        v_est = D._vel_ventana(ms, cal.mm_por_px, 5)
        seg_idx = [(v, la, an) for dur, v, la, an in s["segs"] for _ in range(int(round(dur * FPS)))]
        e_v = [(v_est[i], seg_idx[i][0]) for i in val_f if v_est[i] is not None and seg_idx[i][0] > 0 and ver[i] != "detenida"]
        if e_v:
            fila["vel_mediana_mm_s"] = round(float(np.median([x for x, _ in e_v])), 1)
            fila["vel_real_mm_s"] = e_v[0][1]
            vel_err += [100 * (x - y) / y for x, y in e_v]
        for i in val_f:
            if ms[i].lineas_ok:
                lat_err.append(ms[i].lateral_px * cal.mm_por_px - cal.lateral_ref_mm - seg_idx[i][1])
                ang_err.append(ms[i].angulo_deg - cal.angulo_ref_deg - seg_idx[i][2])
        # latencia de confirmacion en cada cambio de verdad
        if s["g"] == "transicion":
            for c in cambios:
                j = next((j for j in range(c, len(pred)) if pred[j] == ver[c]), None)
                lats.setdefault(f"{ver[c - 1]}->{ver[c]}", []).append(None if j is None else (j - c) / FPS)
        filas.append(fila)
    res = dict(calibracion=cal.__dict__, persist=PERSIST, fps=FPS)
    for nombre, conf in (("filtrado", conf_f), ("estricto", conf_s)):
        m = prf(conf)
        tot = sum(sum(conf[c].values()) for c in CLASES)
        ok = sum(conf[c][c] for c in CLASES)
        res[nombre] = dict(exactitud=ok / tot, frames=tot, macro_f1=float(np.nanmean([m[c]["f1"] for c in CLASES])),
                           clases=m, confusion={c: {p: conf[c][p] for p in CLASES + ["otro"]} for c in CLASES})
    res["error_velocidad_pct"] = dict(media=float(np.mean(vel_err)), mae=float(np.mean(np.abs(vel_err))),
                                      p95_abs=float(np.percentile(np.abs(vel_err), 95)))
    res["error_lateral_mm"] = dict(sesgo=float(np.mean(lat_err)), mae=float(np.mean(np.abs(lat_err))),
                                   p95_abs=float(np.percentile(np.abs(lat_err), 95)))
    res["error_angulo_deg"] = dict(sesgo=float(np.mean(ang_err)), mae=float(np.mean(np.abs(ang_err))),
                                   p95_abs=float(np.percentile(np.abs(ang_err), 95)))
    res["latencia_s"] = {k: dict(valores=v, media=(float(np.mean([x for x in v if x is not None]))
                                                  if any(x is not None for x in v) else None),
                                 sin_confirmar=sum(x is None for x in v)) for k, v in lats.items()}
    for g in barr:
        barr[g].sort(key=lambda d: d["x"])
    res["barridos"] = barr
    res["escenarios"] = filas
    os.makedirs(a.salida, exist_ok=True)
    with open(os.path.join(a.salida, "metricas.json"), "w") as f:
        json.dump(res, f, indent=1, default=float)
    with open(os.path.join(a.salida, "escenarios.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in filas for k in r}, key=lambda k: list(filas[0]).index(k) if k in filas[0] else 99))
        w.writeheader(); w.writerows(filas)
    figuras(res, a.salida)
    imprimir(res)


def evaluar_real(a):
    sys.exit("modo --real: pendiente de implementar cuando existan grabaciones etiquetadas")


def imprimir(r):
    for nombre in ("filtrado", "estricto"):
        x = r[nombre]
        print(f"\n== {nombre}: exactitud {100 * x['exactitud']:.2f}%  macro-F1 {x['macro_f1']:.3f}  ({x['frames']} frames)")
        for c in CLASES:
            m = x["clases"][c]
            print(f"  {c:12s} P {m['precision']:.3f}  R {m['recall']:.3f}  F1 {m['f1']:.3f}  n={m['soporte']}")
        print("  confusion (fila=verdad):", x["confusion"])
    for k in ("error_velocidad_pct", "error_lateral_mm", "error_angulo_deg"):
        print(k, {a: round(b, 3) for a, b in r[k].items()})
    print("latencia:", {k: (None if v["media"] is None else round(v["media"], 2), v["sin_confirmar"]) for k, v in r["latencia_s"].items()})
    for g, lst in r["barridos"].items():
        print(g, [(d["x"], {k: round(d[k], 2) for k in CLASES if d[k] > 0}) for d in lst])


def figuras(r, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    AZ, NA, GR = "#2a6fb0", "#d9822b", "#6b6b6b"
    # matriz de confusion
    x = r["filtrado"]
    M = np.array([[x["confusion"][c][p] for p in CLASES + ["otro"]] for c in CLASES], float)
    Mn = M / M.sum(1, keepdims=True)
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    ax.imshow(Mn, cmap="Blues", vmin=0, vmax=1)
    cols = CLASES + ["otro"]
    ax.set_xticks(range(4)); ax.set_xticklabels(cols); ax.set_yticks(range(3)); ax.set_yticklabels(CLASES)
    ax.set_xlabel("Estado predicho"); ax.set_ylabel("Estado real")
    for i in range(3):
        for j in range(4):
            ax.text(j, i, f"{int(M[i, j])}\n{100 * Mn[i, j]:.1f}%", ha="center", va="center",
                    color="white" if Mn[i, j] > 0.5 else "#222")
    ax.set_title("Matriz de confusion (por frame)")
    ax.spines[:].set_visible(False)
    fig.tight_layout(); fig.savefig(os.path.join(out, "matriz_confusion.png"), dpi=200); plt.close(fig)
    # P / R / F1 por clase
    fig, ax = plt.subplots(figsize=(6.4, 4))
    w = 0.26
    for k, (met, col) in enumerate([("precision", AZ), ("recall", NA), ("f1", GR)]):
        v = [x["clases"][c][met] for c in CLASES]
        b = ax.bar(np.arange(3) + (k - 1) * w, v, w - 0.03, label=met, color=col)
        for rect, val in zip(b, v):
            ax.text(rect.get_x() + rect.get_width() / 2, val + 0.005, f"{val:.2f}", ha="center", fontsize=9)
    ax.set_xticks(range(3)); ax.set_xticklabels(CLASES); ax.set_ylim(0, 1.1); ax.legend(frameon=False, ncol=3, loc="lower center")
    ax.set_title("Precision, recall y F1 por clase")
    fig.tight_layout(); fig.savefig(os.path.join(out, "prf_por_clase.png"), dpi=200); plt.close(fig)
    # barridos
    fig, axs = plt.subplots(1, 3, figsize=(13, 3.8))
    for ax, (g, etq, clave, xl, umb) in zip(axs, [("barrido_lat", "desalineada", "desalineada", "Desplazamiento lateral inyectado (mm)", 3.0),
                                                   ("barrido_ang", "desalineada", "desalineada", "Angulo inyectado (grados)", 1.0),
                                                   ("barrido_vel", "detenida", "detenida", "Velocidad de la correa (mm/s)", r["calibracion"]["umbral_vel_mm_s"])]):
        d = r["barridos"][g]
        ax.plot([e["x"] for e in d], [100 * e[clave] for e in d], "o-", color=AZ, lw=2, ms=6)
        ax.axvline(umb, color=GR, ls="--", lw=1); ax.text(umb, 50, " umbral", color=GR, fontsize=9)
        ax.set_xlabel(xl); ax.set_ylabel(f"% de frames clasificados {etq.upper()}"); ax.set_ylim(-3, 103)
    fig.suptitle("Sensibilidad del detector", y=1.0)
    fig.tight_layout(); fig.savefig(os.path.join(out, "sensibilidad.png"), dpi=200); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("generar"); p.add_argument("--dir", default=os.path.expanduser("~/sint_metricas"))
    p.add_argument("--presupuesto", type=float, default=140); p.set_defaults(f=cmd_generar)
    p = sub.add_parser("evaluar"); p.add_argument("--dir", default=os.path.expanduser("~/sint_metricas"))
    p.add_argument("--salida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "metricas"))
    p.add_argument("--real", default=None); p.set_defaults(f=cmd_evaluar)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
