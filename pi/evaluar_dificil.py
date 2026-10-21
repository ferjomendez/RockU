#!/usr/bin/env python3
"""Evaluacion adversarial: mismas metricas que evaluar_metricas.py pero con imagenes degradadas.

Calibra con las grabaciones LIMPIAS (cal_normal / cal_detenida de evaluar_metricas.py) y prueba con
ruido, bajo contraste, parpadeo, desenfoque, JPEG agresivo, vibracion, velocidad fluctuante,
cambio de escala (altura de camara), reflejo fijo y casos en la frontera de los umbrales.

    python3 evaluar_metricas.py generar          # una vez: crea cal_* limpias
    python3 evaluar_dificil.py generar [--presupuesto 140]   # reanudable
    python3 evaluar_dificil.py evaluar
"""
import argparse, csv, json, os, sys, time
from collections import Counter
from multiprocessing import Pool

import cv2
import numpy as np

import deteccion as D
import simulador as S
import analizar as A
import evaluar_metricas as M

CLASES, MAPA, FPS, SALTAR, TOL = M.CLASES, M.MAPA, 10.0, M.SALTAR, M.TOL
BASE = os.path.expanduser("~/sint_dificil")
CAL = os.path.expanduser("~/sint_metricas")


def fl(media, dur, lat=0.0, ang=0.0, amp=0.35, seed=0):
    r = np.random.default_rng(seed)
    return [(0.5, float(media * (1 + r.uniform(-amp, amp))), lat, ang) for _ in range(int(dur * 2))]


VIB = dict(jitter_lat=0.8, jitter_ang=0.3)
TODO = dict(sigma=10, contraste=0.6, flicker=0.7, drift=0.2, blur=1.5, q=40, shift=3)


def especificaciones():
    E, k = {}, [0]

    def add(n, g, segs, pert=None, kw=None):
        k[0] += 1
        E[n] = dict(nivel="extremo" if n.startswith("x") else "moderado", g=g, segs=segs, esc=1 + k[0] % 3, seed=1000 + k[0], pert=pert or {}, kw=kw or {})
    N = lambda v, la=0, an=0, d=6: [(d, v, la, an)]
    # normal
    add("n_ruido", "normal", N(100), dict(sigma=12))
    add("n_contraste", "normal", N(100), dict(contraste=0.5, sigma=8))
    add("n_flicker_deriva", "normal", N(130), dict(flicker=1.0, drift=0.3))
    add("n_defoco_jpeg", "normal", N(80), dict(blur=2.5, q=30))
    add("n_vibracion", "normal", N(100), dict(shift=4), VIB)
    add("n_vel_fluctuante", "normal", fl(100, 6, seed=1))
    add("n_vel_alta_blur", "normal", N(200))
    add("n_lento_ruido", "normal", N(45), dict(sigma=12))
    add("n_escala_108", "normal", N(100), dict(escala=1.08))
    add("n_glare_fijo", "normal", N(100), dict(glare=1))
    add("n_glare_lento", "normal", N(60), dict(glare=1, sigma=8))
    add("n_todo_junto", "normal", N(100), TODO, dict(jitter_t=0.03))
    # detenida
    add("d_ruido", "detenida", N(0), dict(sigma=12))
    add("d_contraste", "detenida", N(0), dict(contraste=0.5, sigma=8))
    add("d_flicker_deriva", "detenida", N(0), dict(flicker=1.0, drift=0.3))
    add("d_vibracion", "detenida", N(0), dict(shift=8), VIB)
    add("d_escala_108", "detenida", N(0), dict(escala=1.08))
    add("d_defoco_jpeg", "detenida", N(0), dict(blur=2.5, q=30))
    add("d_glare_fijo", "detenida", N(0), dict(glare=1))
    add("d_todo_junto", "detenida", N(0), TODO, dict(jitter_t=0.03))
    # desalineada (con margen sobre el umbral)
    add("a_ruido_lat", "desalineada", N(100, 4.5), dict(sigma=12))
    add("a_contraste_lat", "desalineada", N(100, -5), dict(contraste=0.5, sigma=8))
    add("a_vibracion_lat", "desalineada", N(100, 4.5), dict(shift=4), VIB)
    add("a_escala_092", "desalineada", N(100, 4.5), dict(escala=0.92))
    add("a_ruido_ang", "desalineada", N(100, 0, 1.6), dict(sigma=12))
    add("a_vibracion_ang", "desalineada", N(100, 0, -1.5), dict(shift=4), VIB)
    add("a_flicker_lat", "desalineada", N(100, -4), dict(flicker=1.0, drift=0.3))
    add("a_defoco_ang", "desalineada", N(100, 0, 1.6), dict(blur=2.5, q=30))
    add("a_glare_lat", "desalineada", N(100, 5), dict(glare=1))
    add("a_todo_junto", "desalineada", N(100, 4.5, 1.2), TODO, dict(jitter_t=0.03))
    # frontera: verdad del simulador usa lat>3 mm o ang>1 deg
    leve = dict(sigma=6, shift=2)
    for la in (2.5, 3.5):
        add(f"f_lat_{la}", "frontera", N(100, la), leve, dict(jitter_lat=0.4, jitter_ang=0.15))
    for an in (0.8, 1.2):
        add(f"f_ang_{an}", "frontera", N(100, 0, an), leve, dict(jitter_lat=0.4, jitter_ang=0.15))
    # transiciones con degradacion
    deg = dict(sigma=8, flicker=0.8, drift=0.15, shift=3, q=50)
    add("t_a", "transicion", [(3, 100, 0, 0), (4, 0, 0, 0), (3, 100, 0, 0), (4, 100, 5, 0), (3, 100, 0, 0)], deg, VIB)
    add("t_b", "transicion", [(3, 130, 0, 0), (3, 0, 0, 0), (3, 130, 0, 0), (3, 130, 0, 1.8), (3, 130, 0, 0)], deg, VIB)

    # ---- nivel EXTREMO ----
    X = lambda *a, **k: add(*a, **k)
    TODOX = dict(sigma=25, contraste=0.4, flicker=1.5, drift=0.5, blur=4, q=20, shift=10, glare=1.5)
    VIBX = dict(jitter_lat=0.8, jitter_ang=0.3, jitter_t=0.05)
    TAPA = dict(tapa=1, sigma=8)
    X("xn_ruido30", "normal", N(100), dict(sigma=30))
    X("xn_contraste25", "normal", N(100), dict(contraste=0.25, sigma=10))
    X("xn_defoco8_q15", "normal", N(100), dict(blur=8, q=15))
    X("xn_vibracion_fuerte", "normal", N(100), dict(shift=14), VIB)
    X("xn_flicker_fuerte", "normal", N(100), dict(flicker=2.0, drift=0.6))
    X("xn_glare_grande", "normal", N(100), dict(glare=2.2, sigma=10))
    X("xn_escala_125", "normal", N(100), dict(escala=1.25))
    X("xn_vel_fluct_80", "normal", fl(100, 6, amp=0.8, seed=2))
    X("xn_lento40_ruido", "normal", N(40), dict(sigma=25, glare=1.5))
    X("xn_linea_tapada", "normal", N(100), TAPA)
    X("xn_todo_extremo", "normal", N(100), TODOX, VIBX)
    X("xd_ruido30", "detenida", N(0), dict(sigma=30))
    X("xd_vibracion_fuerte", "detenida", N(0), dict(shift=14), VIB)
    X("xd_glare_grande", "detenida", N(0), dict(glare=2.2, sigma=20))
    X("xd_flicker_fuerte", "detenida", N(0), dict(flicker=2.0, drift=0.6))
    X("xd_escala_125", "detenida", N(0), dict(escala=1.25))
    X("xd_linea_tapada", "detenida", N(0), TAPA)
    X("xd_todo_extremo", "detenida", N(0), TODOX, VIBX)
    X("xa_ruido30_lat", "desalineada", N(100, 4), dict(sigma=30))
    X("xa_ruido30_ang", "desalineada", N(100, 0, 1.3), dict(sigma=30))
    X("xa_linea_tapada", "desalineada", N(100, 5), TAPA)
    X("xa_todo_extremo", "desalineada", N(100, 4.5, 1.2), TODOX, VIBX)
    fx = dict(sigma=15, shift=6)
    KX = dict(jitter_lat=0.6, jitter_ang=0.25)
    for la in (2.8, 3.2):
        X(f"xf_lat_{la}", "frontera", N(100, la), fx, KX)
    for an in (0.93, 1.07):
        X(f"xf_ang_{an}", "frontera", N(100, 0, an), fx, KX)
    dx = dict(sigma=20, flicker=1.5, drift=0.3, shift=8, q=25)
    X("xt_a", "transicion", [(3, 100, 0, 0), (4, 0, 0, 0), (3, 100, 0, 0), (4, 100, 5, 0), (3, 100, 0, 0)], dx, VIBX)
    X("xt_b", "transicion", [(3, 130, 0, 0), (3, 0, 0, 0), (3, 130, 0, 0), (3, 130, 0, 1.8), (3, 130, 0, 0)], dx, VIBX)
    return E


def perturbar(img, k, n, p, rng):
    h, w = img.shape[:2]
    f = img.astype(np.float32)
    if p.get("contraste", 1) != 1:
        f = 128 + (f - 128) * p["contraste"]
    if p.get("blur"):
        f = cv2.GaussianBlur(f, (0, 0), p["blur"])
    if p.get("escala", 1) != 1 or p.get("shift"):
        Mx = cv2.getRotationMatrix2D((w / 2, h / 2), 0, p.get("escala", 1))
        if p.get("shift"):
            Mx[:, 2] += rng.uniform(-p["shift"], p["shift"], 2)
        f = cv2.warpAffine(f, Mx, (w, h), borderMode=cv2.BORDER_REFLECT)
    if p.get("glare"):
        m = np.zeros((h, w), np.float32)
        gs = float(p["glare"]); cv2.ellipse(m, (w // 2 + 60, int(h * 0.4)), (int(130 * gs), int(85 * gs)), 20, 0, 360, 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), 25) * 0.9
        f = f * (1 - m[..., None]) + 250 * m[..., None]
    if p.get("tapa"):
        f[int(h * 0.05):int(h * 0.75), 270:345] = 120
    gain = 1.0
    if p.get("drift"):
        gain *= 1 + p["drift"] * ((k / max(1, n - 1)) - 0.5) * 2
    if p.get("flicker"):
        gain *= 1 + rng.uniform(-0.15, 0.15) * p["flicker"]
        bandas = 1 + 0.10 * p["flicker"] * np.sin(2 * np.pi * np.arange(h) / 200 + rng.uniform(0, 6.28))
        f = f * bandas[:, None, None].astype(np.float32)
    f = f * gain
    if p.get("sigma"):
        f = f + rng.normal(0, p["sigma"], f.shape[:2]).astype(np.float32)[..., None]
    return np.clip(f, 0, 255).astype(np.uint8)


_ESC = {}


def _gen(args):
    nombre, s, base = args
    ruta = os.path.join(base, nombre)
    os.makedirs(ruta, exist_ok=True)
    if s["esc"] not in _ESC:
        _ESC[s["esc"]] = S.Escena(seed=s["esc"])
    esc, kw, p = _ESC[s["esc"]], s["kw"], s["pert"]
    rng, prng = np.random.default_rng(s["seed"]), np.random.default_rng(s["seed"] + 7)
    total = sum(int(round(d * FPS)) for d, *_ in s["segs"])
    filas, ver, vel_r, lat_r, ang_r = [], [], [], [], []
    pos, i, dt = 0.0, 0, 1 / FPS
    for dur, vel, lat, ang in s["segs"]:
        for _ in range(int(round(dur * FPS))):
            la = lat + rng.normal(0, kw.get("jitter_lat", 0.15))
            an = ang + rng.normal(0, kw.get("jitter_ang", 0.05))
            jpg = esc.render(pos, la, an, vel, kw.get("exp_s", 0.03), rng, calidad=95)
            img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            img = perturbar(img, i, total, p, prng)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, p.get("q", 85)])
            nom = f"f_{i:06d}.jpg"
            open(os.path.join(ruta, nom), "wb").write(buf.tobytes())
            jt = kw.get("jitter_t", 0.0)
            filas.append((i, round(i * dt + (rng.uniform(-jt, jt) if jt else 0.0), 4), nom, len(buf)))
            ver.append(S.etiqueta_verdad(vel, lat, ang)); vel_r.append(vel); lat_r.append(lat); ang_r.append(ang)
            pos += vel * dt; i += 1
    with open(os.path.join(ruta, "indice.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["n", "t_s", "archivo", "bytes"]); w.writerows(filas)
    json.dump(dict(etiquetas_frame=ver, vel=vel_r, lat=lat_r, ang=ang_r, pert=p, kw=kw, simulado=True),
              open(os.path.join(ruta, "meta.json"), "w"))
    return nombre


def cmd_generar(a):
    E = especificaciones()
    pend = [(n, s, BASE) for n, s in E.items() if not os.path.exists(os.path.join(BASE, n, "meta.json"))]
    print(f"pendientes: {len(pend)} de {len(E)}")
    t0 = time.time()
    with Pool(2) as pool:
        while pend and time.time() - t0 < a.presupuesto:
            lote, pend = pend[:2], pend[2:]
            for n in pool.map(_gen, lote):
                print("ok", n, f"{time.time() - t0:.0f}s", flush=True)
    print("faltan:", len(pend))


def cmd_evaluar(a):
    E = especificaciones()
    falt = [n for n in E if not os.path.exists(os.path.join(BASE, n, "meta.json"))]
    if falt:
        sys.exit(f"faltan {len(falt)} escenarios; corre generar")
    cal = D.calibrar(A.medir_carpeta(os.path.join(CAL, "cal_normal")), A.medir_carpeta(os.path.join(CAL, "cal_detenida")))
    conf = {k_: {c: Counter() for c in CLASES} for k_ in ("todo", "sin_frontera", "moderado", "extremo")}
    grp, filas, ev, el, ea, lats = {}, [], [], [], [], {}
    for n, s in E.items():
        meta = json.load(open(os.path.join(BASE, n, "meta.json")))
        ms = A.medir_carpeta(os.path.join(BASE, n))
        clf = D.Clasificador(cal, persist=M.PERSIST)
        infos = [clf.actualizar(m) for m in ms]
        ver, pred = meta["etiquetas_frame"][:len(infos)], [MAPA.get(i["estado"], "otro") for i in infos]
        cam = [i for i in range(1, len(ver)) if ver[i] != ver[i - 1]]
        val = [i for i in range(SALTAR, len(ver)) if all(abs(i - c) > TOL for c in cam)]
        for i in val:
            conf["todo"][ver[i]][pred[i]] += 1
            conf[s["nivel"]][ver[i]][pred[i]] += 1
            if s["g"] != "frontera":
                conf["sin_frontera"][ver[i]][pred[i]] += 1
        err = Counter((ver[i], pred[i]) for i in val if pred[i] != ver[i])
        acc = 1 - sum(err.values()) / len(val)
        sin_lin = sum(not ms[i].lineas_ok for i in val)
        filas.append(dict(escenario=n, grupo=s["g"], nivel=s["nivel"], validos=len(val), exactitud=round(acc, 4),
                          frames_sin_lineas=sin_lin, errores={f'{a_}->{b_}': c_ for (a_, b_), c_ in err.items()}))
        grp.setdefault(s["g"], []).append(acc)
        v_est = D._vel_ventana(ms, cal.mm_por_px, 5)
        for i in val:
            if s["g"] != "frontera" and v_est[i] is not None and meta["vel"][i] > 0:
                vv = float(np.mean(meta["vel"][max(0, i - 4):i + 1]))
                if vv > 0 and ver[i] != "detenida":
                    ev.append(100 * (v_est[i] - vv) / vv)
            if ms[i].lineas_ok and s["g"] in ("normal", "desalineada"):
                el.append(ms[i].lateral_px * cal.mm_por_px - cal.lateral_ref_mm - meta["lat"][i])
                ea.append(ms[i].angulo_deg - cal.angulo_ref_deg - meta["ang"][i])
        if s["g"] == "transicion":
            for c in cam:
                j = next((j for j in range(c, len(pred)) if pred[j] == ver[c]), None)
                lats.setdefault(f"{ver[c-1]}->{ver[c]}", []).append(None if j is None else (j - c) / FPS)
    res = dict(calibracion=cal.__dict__)
    for nombre, cf in conf.items():
        m = M.prf(cf)
        tot = sum(sum(cf[c].values()) for c in CLASES)
        res[nombre] = dict(exactitud=sum(cf[c][c] for c in CLASES) / tot, frames=tot,
                           macro_f1=float(np.nanmean([m[c]["f1"] for c in CLASES])), clases=m,
                           confusion={c: {p: cf[c][p] for p in CLASES + ["otro"]} for c in CLASES})
    res["exactitud_por_grupo"] = {g: dict(media=float(np.mean(v)), minimo=float(np.min(v))) for g, v in grp.items()}
    st = lambda x: dict(sesgo=float(np.mean(x)), mae=float(np.mean(np.abs(x))), p95_abs=float(np.percentile(np.abs(x), 95)))
    res["error_velocidad_pct"], res["error_lateral_mm"], res["error_angulo_deg"] = st(ev), st(el), st(ea)
    res["latencia_s"] = {k: dict(valores=v, sin_confirmar=sum(x is None for x in v),
                                 media=(float(np.mean([x for x in v if x is not None])) if any(x is not None for x in v) else None))
                         for k, v in lats.items()}
    res["escenarios"] = filas
    out = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "metricas_dificil"))
    os.makedirs(out, exist_ok=True)
    json.dump(res, open(os.path.join(out, "metricas_dificil.json"), "w"), indent=1, default=float)
    with open(os.path.join(out, "escenarios_dificil.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0])); w.writeheader(); w.writerows(filas)
    figuras(res, out)
    for nombre in ("todo", "moderado", "extremo", "sin_frontera"):
        x = res[nombre]
        print(f"\n== {nombre}: exactitud {100*x['exactitud']:.2f}%  macro-F1 {x['macro_f1']:.3f}  ({x['frames']} frames)")
        for c in CLASES:
            q = x["clases"][c]; print(f"  {c:12s} P {q['precision']:.3f} R {q['recall']:.3f} F1 {q['f1']:.3f} n={q['soporte']}")
        print("  confusion:", x["confusion"])
    print("\npor grupo:", {g: (round(v["media"], 3), round(v["minimo"], 3)) for g, v in res["exactitud_por_grupo"].items()})
    for k in ("error_velocidad_pct", "error_lateral_mm", "error_angulo_deg"):
        print(k, {a_: round(b, 3) for a_, b in res[k].items()})
    print("latencia:", {k: (v["media"], v["sin_confirmar"]) for k, v in res["latencia_s"].items()})
    print("\npeores escenarios:")
    for r in sorted(filas, key=lambda r: r["exactitud"])[:24]:
        print(f"  {r['escenario']:20s} {r['grupo']:12s} {100*r['exactitud']:5.1f}%  sin_lineas={r['frames_sin_lineas']} {r['errores']}")


def figuras(r, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    x = r["todo"]
    Mx = np.array([[x["confusion"][c][p] for p in CLASES + ["otro"]] for c in CLASES], float)
    Mn = Mx / Mx.sum(1, keepdims=True)
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    ax.imshow(Mn, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(4)); ax.set_xticklabels(CLASES + ["otro"]); ax.set_yticks(range(3)); ax.set_yticklabels(CLASES)
    ax.set_xlabel("Estado predicho"); ax.set_ylabel("Estado real"); ax.spines[:].set_visible(False)
    for i in range(3):
        for j in range(4):
            ax.text(j, i, f"{int(Mx[i,j])}\n{100*Mn[i,j]:.1f}%", ha="center", va="center", color="white" if Mn[i, j] > .5 else "#222")
    ax.set_title("Matriz de confusion, set dificil")
    fig.tight_layout(); fig.savefig(os.path.join(out, "matriz_confusion_dificil.png"), dpi=200); plt.close(fig)
    fs = sorted(r["escenarios"], key=lambda q: q["exactitud"])
    fig, ax = plt.subplots(figsize=(7.5, 9))
    col = {"normal": "#2a6fb0", "detenida": "#d9822b", "desalineada": "#4d4d4d", "frontera": "#9a9a9a", "transicion": "#7a5aa6"}
    ax.barh([q["escenario"] for q in fs], [100 * q["exactitud"] for q in fs], color=[col[q["grupo"]] for q in fs])
    ax.set_xlim(0, 100); ax.set_xlabel("Exactitud por frame (%)"); ax.tick_params(axis="y", labelsize=8)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=c, label=g) for g, c in col.items()], frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.07), ncol=5, fontsize=9)
    ax.invert_yaxis()
    ax.set_title("Exactitud por escenario (peores arriba)")
    fig.tight_layout(); fig.savefig(os.path.join(out, "exactitud_por_escenario.png"), dpi=200); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("generar"); p.add_argument("--presupuesto", type=float, default=140); p.set_defaults(f=cmd_generar)
    p = sub.add_parser("evaluar"); p.set_defaults(f=cmd_evaluar)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
