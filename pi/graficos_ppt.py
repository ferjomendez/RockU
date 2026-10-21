#!/usr/bin/env python3
"""Graficos 16:9 para presentacion, a partir de docs/metricas*/ (JSON generados por los evaluadores).

    python3 graficos_ppt.py     ->  docs/graficos_ppt/*.png
"""
import json, os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.normpath(os.path.join(AQUI, "..", "docs"))
OUT = os.path.join(DOCS, "graficos_ppt")
os.makedirs(OUT, exist_ok=True)
B = json.load(open(os.path.join(DOCS, "metricas", "metricas.json")))
Dj = json.load(open(os.path.join(DOCS, "metricas_dificil", "metricas_dificil.json")))

C_LIMPIO, C_MOD, C_EXT, GRIS, TXT = "#a9c4e0", "#2a6fb0", "#d9822b", "#8a8a8a", "#222222"
CLASES = ["normal", "detenida", "desalineada"]
CL_ES = {"normal": "Normal", "detenida": "Detenida", "desalineada": "Desalineada", "otro": "Sin líneas"}
plt.rcParams.update({"font.size": 17, "axes.spines.top": False, "axes.spines.right": False,
                     "text.color": TXT, "axes.labelcolor": TXT, "xtick.color": TXT, "ytick.color": TXT,
                     "axes.titlesize": 24, "axes.titleweight": "bold", "axes.titlelocation": "left"})
NOTA = "Datos simulados (simulador.py). Calibración con imágenes limpias."


def nueva(titulo, sub=None, size=(13.33, 7.5)):
    fig, ax = plt.subplots(figsize=size)
    fig.text(0.01, 0.955, titulo, fontsize=26, fontweight="bold", va="center")
    if sub:
        fig.text(0.01, 0.895, sub, fontsize=16, color=GRIS, va="center")
    return fig, ax


def guardar(fig, nombre, nota=NOTA):
    fig.text(0.01, 0.01, nota, fontsize=11, color=GRIS)
    fig.tight_layout(rect=(0, 0.025, 1, 0.86))
    fig.savefig(os.path.join(OUT, nombre), dpi=150, facecolor="white")
    plt.close(fig)
    print("ok", nombre)


def etiquetas(ax, barras, fmt="{:.1f}%", dy=1.0):
    for b in barras:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + dy, fmt.format(b.get_height()),
                ha="center", va="bottom", fontsize=16, fontweight="bold")


esc = Dj["escenarios"]
nivel_acc = {"limpio": 100 * B["filtrado"]["exactitud"], "moderado": 100 * Dj["moderado"]["exactitud"],
             "extremo": 100 * Dj["extremo"]["exactitud"]}
f1 = {"limpio": B["filtrado"], "moderado": Dj["moderado"], "extremo": Dj["extremo"]}

# 01 resumen
fig, ax = nueva("Exactitud del detector según dificultad", "Porcentaje de frames clasificados correctamente")
k = ["limpio", "moderado", "extremo"]
b = ax.bar([x.capitalize() for x in k], [nivel_acc[x] for x in k], color=[C_LIMPIO, C_MOD, C_EXT], width=0.55)
etiquetas(ax, b); ax.set_ylim(0, 112); ax.set_ylabel("Exactitud (%)")
guardar(fig, "01_resumen_exactitud.png")

# 02 F1 por clase y nivel
fig, ax = nueva("F1 por clase y nivel de dificultad", "1.0 = clasificación perfecta")
w = 0.26
for j, (n, col) in enumerate(zip(k, [C_LIMPIO, C_MOD, C_EXT])):
    v = [f1[n]["clases"][c]["f1"] for c in CLASES]
    bb = ax.bar(np.arange(3) + (j - 1) * w, v, w - 0.03, color=col, label=n.capitalize())
    for r, val in zip(bb, v):
        ax.text(r.get_x() + r.get_width() / 2, val + 0.01, f"{val:.2f}", ha="center", fontsize=14, fontweight="bold")
ax.set_xticks(range(3)); ax.set_xticklabels([CL_ES[c] for c in CLASES]); ax.set_ylim(0, 1.15); ax.set_ylabel("F1")
ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.0))
guardar(fig, "02_f1_por_clase_niveles.png")

# 03 precision/recall/F1 extremo
fig, ax = nueva("Precisión, recall y F1 en el nivel extremo", f"{Dj['extremo']['frames']} frames evaluados")
for j, (met, col) in enumerate([("precision", C_MOD), ("recall", C_EXT), ("f1", GRIS)]):
    v = [Dj["extremo"]["clases"][c][met] for c in CLASES]
    bb = ax.bar(np.arange(3) + (j - 1) * w, v, w - 0.03, color=col, label={"precision": "Precisión", "recall": "Recall", "f1": "F1"}[met])
    for r, val in zip(bb, v):
        ax.text(r.get_x() + r.get_width() / 2, val + 0.01, f"{val:.2f}", ha="center", fontsize=14, fontweight="bold")
ax.set_xticks(range(3)); ax.set_xticklabels([CL_ES[c] for c in CLASES]); ax.set_ylim(0, 1.15)
ax.legend(frameon=False, ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.0))
guardar(fig, "03_precision_recall_extremo.png")

# 04 matriz de confusion extremo
x = Dj["extremo"]
M = np.array([[x["confusion"][c][p] for p in CLASES + ["otro"]] for c in CLASES], float)
Mn = M / M.sum(1, keepdims=True)
fig, ax = nueva("Matriz de confusión, nivel extremo", "Fila: estado real. Columna: estado predicho", size=(11, 7.5))
ax.imshow(Mn, cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(4)); ax.set_xticklabels([CL_ES[c] for c in CLASES + ["otro"]])
ax.set_yticks(range(3)); ax.set_yticklabels([CL_ES[c] for c in CLASES]); ax.spines[:].set_visible(False)
for i in range(3):
    for j in range(4):
        ax.text(j, i, f"{int(M[i, j])}\n{100 * Mn[i, j]:.1f}%", ha="center", va="center", fontsize=18,
                color="white" if Mn[i, j] > 0.5 else TXT)
ax.set_xticks(np.arange(-.5, 4), minor=True); ax.set_yticks(np.arange(-.5, 3), minor=True)
ax.grid(which="minor", color="white", lw=3); ax.tick_params(which="minor", length=0)
guardar(fig, "04_matriz_confusion_extremo.png")

# 05 exactitud por grupo y nivel
grupos = ["normal", "detenida", "desalineada", "frontera", "transicion"]
G_ES = {"normal": "Normal", "detenida": "Detenida", "desalineada": "Desalineada", "frontera": "Frontera\n(cerca del umbral)", "transicion": "Transiciones"}
acc = defaultdict(list)
for e in esc:
    acc[(e["grupo"], e["nivel"])].append(100 * e["exactitud"])
fig, ax = nueva("Exactitud por tipo de escenario", "Promedio de los escenarios de cada grupo")
for j, (n, col) in enumerate([("moderado", C_MOD), ("extremo", C_EXT)]):
    v = [np.mean(acc[(g, n)]) if acc[(g, n)] else 0 for g in grupos]
    bb = ax.bar(np.arange(len(grupos)) + (j - .5) * 0.38, v, 0.35, color=col, label=n.capitalize())
    for r, val, g in zip(bb, v, grupos):
        if acc[(g, n)]:
            ax.text(r.get_x() + r.get_width() / 2, val + 1, f"{val:.0f}%", ha="center", fontsize=15, fontweight="bold")
ax.set_xticks(range(len(grupos))); ax.set_xticklabels([G_ES[g] for g in grupos], fontsize=15)
ax.set_ylim(0, 118); ax.set_ylabel("Exactitud (%)"); ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.0))
guardar(fig, "05_exactitud_por_grupo.png")

# 06 modos de falla (nivel extremo)
cnt = Counter()
for e in esc:
    if e["nivel"] == "extremo":
        for kx, vx in e["errores"].items():
            a_, p_ = kx.split("->")
            cnt[(a_, p_)] += vx
items = sorted(cnt.items(), key=lambda t: t[1])
lab = [f"{CL_ES[a_]} detectada como {CL_ES[p_].lower() if p_ != 'otro' else 'sin líneas'}" if p_ != "otro"
       else f"{CL_ES[a_]}: no se encontraron las líneas" for (a_, p_), _ in items]
fig, ax = nueva("Cómo falla el detector (nivel extremo)", "Frames mal clasificados por tipo de error")
bb = ax.barh(lab, [v for _, v in items], color=[C_EXT if p_ == "otro" else C_MOD for (_, p_), _ in items])
for r in bb:
    ax.text(r.get_width() + 1, r.get_y() + r.get_height() / 2, f"{int(r.get_width())}", va="center", fontsize=16, fontweight="bold")
ax.set_xlabel("Frames"); ax.set_xlim(0, max(v for _, v in items) * 1.15)
guardar(fig, "06_modos_de_falla.png")

# 07 a 09 sensibilidad
cal = B["calibracion"]
for nombre, g, clave, xl, umb, txt, tit in [
    ("07_sensibilidad_lateral.png", "barrido_lat", "desalineada", "Desplazamiento lateral inyectado (mm)", cal["umbral_lateral_mm"], "Umbral {:.0f} mm", "Detección de desalineación lateral"),
    ("08_sensibilidad_angulo.png", "barrido_ang", "desalineada", "Ángulo inyectado (grados)", cal["umbral_angulo_deg"], "Umbral {:.0f}°", "Detección de desalineación angular"),
    ("09_sensibilidad_velocidad.png", "barrido_vel", "detenida", "Velocidad de la correa (mm/s)", cal["umbral_vel_mm_s"], "Umbral {:.0f} mm/s", "Detección de correa detenida")]:
    d = B["barridos"][g]
    fig, ax = nueva(tit, "Porcentaje de frames clasificados " + ("DESALINEADA" if clave == "desalineada" else "DETENIDA"))
    ax.plot([e["x"] for e in d], [100 * e[clave] for e in d], "o-", color=C_MOD, lw=3.5, ms=11)
    ax.axvline(umb, color=C_EXT, ls="--", lw=2.5)
    ax.text(umb, 52, "  " + txt.format(umb), color=C_EXT, fontsize=17, fontweight="bold")
    ax.set_xlabel(xl); ax.set_ylabel("% de frames"); ax.set_ylim(-4, 106)
    guardar(fig, nombre)

# 10 errores de medicion
fig, axs = plt.subplots(1, 3, figsize=(13.33, 7.0))
fig.suptitle("Error de medición: limpio vs difícil", x=0.01, ha="left", fontsize=24, fontweight="bold")
for ax, (clv, titu, unid, fm) in zip(axs, [("error_velocidad_pct", "Velocidad", "%", "{:.1f}"),
                                           ("error_lateral_mm", "Posición lateral", "mm", "{:.2f}"),
                                           ("error_angulo_deg", "Ángulo", "grados", "{:.2f}")]):
    v1, v2 = B[clv], Dj[clv]
    xs = np.arange(2)
    for j, (src, col, n) in enumerate([(v1, C_LIMPIO, "Limpio"), (v2, C_EXT, "Difícil")]):
        bb = ax.bar(xs + (j - .5) * 0.38, [src["mae"], src["p95_abs"]], 0.35, color=col, label=n)
        for r in bb:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height(), fm.format(r.get_height()), ha="center", va="bottom", fontsize=13, fontweight="bold")
    ax.set_xticks(xs); ax.set_xticklabels(["Medio", "Percentil 95"], fontsize=14)
    ax.set_title(f"{titu} ({unid})", fontsize=18, loc="center"); ax.set_ylim(0, max(v2["p95_abs"], v1["p95_abs"]) * 1.2)
axs[0].legend(frameon=False, fontsize=14, loc="upper left")
fig.text(0.01, 0.01, NOTA, fontsize=11, color=GRIS)
fig.tight_layout(rect=(0, 0.03, 1, 0.93)); fig.savefig(os.path.join(OUT, "10_errores_medicion.png"), dpi=150, facecolor="white"); plt.close(fig); print("ok 10")

# 11 latencia
trs = [("normal->detenida", "Normal → detenida"), ("detenida->normal", "Detenida → normal"),
       ("normal->desalineada", "Normal → desalineada"), ("desalineada->normal", "Desalineada → normal")]
fig, ax = nueva("Tiempo de confirmación de un cambio de estado", "Segundos desde el cambio real hasta que el sistema lo confirma (persistencia de 3 frames, 10 fps)")
for j, (src, col, n) in enumerate([(B, C_LIMPIO, "Limpio"), (Dj, C_EXT, "Difícil")]):
    v = [src["latencia_s"][t]["media"] for t, _ in trs]
    bb = ax.bar(np.arange(4) + (j - .5) * 0.38, v, 0.35, color=col, label=n)
    for r in bb:
        ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.01, f"{r.get_height():.2f} s", ha="center", fontsize=15, fontweight="bold")
ax.set_xticks(range(4)); ax.set_xticklabels([t for _, t in trs], fontsize=15); ax.set_ylabel("Segundos")
ax.set_ylim(0, 0.85); ax.legend(frameon=False, ncol=2, loc="upper right")
guardar(fig, "11_latencia_confirmacion.png")

# 12 peores escenarios
NOM = {"xn_contraste25": "Normal, contraste al 25%", "xa_linea_tapada": "Desalineada, línea tapada",
       "xf_lat_3.2": "Frontera: 3.2 mm lateral", "xf_ang_1.07": "Frontera: 1.07° de ángulo",
       "xf_lat_2.8": "Frontera: 2.8 mm lateral", "xd_vibracion_fuerte": "Detenida, vibración fuerte",
       "xf_ang_0.93": "Frontera: 0.93° de ángulo", "xd_todo_extremo": "Detenida, todo extremo",
       "xa_todo_extremo": "Desalineada, todo extremo"}
peores = sorted(esc, key=lambda e: e["exactitud"])[:9]
fig, ax = nueva("Los 9 escenarios más difíciles", "Exactitud por frame")
nombres = [NOM.get(e["escenario"], e["escenario"]) for e in peores][::-1]
vals = [100 * e["exactitud"] for e in peores][::-1]
bb = ax.barh(nombres, vals, color=[C_EXT if v < 70 else C_MOD for v in vals])
for r, v in zip(bb, vals):
    ax.text(v + 1, r.get_y() + r.get_height() / 2, f"{v:.0f}%", va="center", fontsize=16, fontweight="bold")
ax.set_xlim(0, 112); ax.set_xlabel("Exactitud (%)")
guardar(fig, "12_peores_escenarios.png")

# 13 tabla de condiciones
def media(nombres):
    v = [100 * e["exactitud"] for e in esc if e["escenario"] in nombres]
    return np.mean(v) if v else None
filas = [("Ruido", "σ 12", "σ 30", ["n_ruido", "d_ruido", "a_ruido_lat", "a_ruido_ang"], ["xn_ruido30", "xd_ruido30", "xa_ruido30_lat", "xa_ruido30_ang"]),
         ("Contraste bajo", "50%", "25%", ["n_contraste", "d_contraste", "a_contraste_lat"], ["xn_contraste25"]),
         ("Parpadeo de luz", "±15%", "±30%", ["n_flicker_deriva", "d_flicker_deriva", "a_flicker_lat"], ["xn_flicker_fuerte", "xd_flicker_fuerte"]),
         ("Desenfoque + JPEG", "σ 2.5, q30", "σ 8, q15", ["n_defoco_jpeg", "d_defoco_jpeg", "a_defoco_ang"], ["xn_defoco8_q15"]),
         ("Vibración de cámara", "±4 a 8 px", "±14 px", ["n_vibracion", "d_vibracion", "a_vibracion_lat", "a_vibracion_ang"], ["xn_vibracion_fuerte", "xd_vibracion_fuerte"]),
         ("Cambio de altura", "+8% / -8%", "+25%", ["n_escala_108", "d_escala_108", "a_escala_092"], ["xn_escala_125", "xd_escala_125"]),
         ("Reflejo fijo", "normal", "grande", ["n_glare_fijo", "n_glare_lento", "d_glare_fijo", "a_glare_lat"], ["xn_glare_grande", "xd_glare_grande"]),
         ("Línea tapada", "no probado", "sí", [], ["xn_linea_tapada", "xd_linea_tapada", "xa_linea_tapada"]),
         ("Todo junto", "combinado", "combinado", ["n_todo_junto", "d_todo_junto", "a_todo_junto"], ["xn_todo_extremo", "xd_todo_extremo", "xa_todo_extremo"])]
fig, ax = plt.subplots(figsize=(13.33, 7.5)); ax.axis("off")
fig.text(0.01, 0.955, "Condiciones probadas y resultado", fontsize=26, fontweight="bold", va="center")
cols = ["Condición", "Moderado", "Exactitud", "Extremo", "Exactitud"]
xs = [0.0, 0.34, 0.50, 0.64, 0.82]
for x_, c in zip(xs, cols):
    ax.text(x_, 0.93, c, fontsize=17, fontweight="bold", transform=ax.transAxes)
ax.plot([0, 1], [0.905, 0.905], color=TXT, lw=1.5, transform=ax.transAxes)
for i, (nom, pm, pe, nm, ne) in enumerate(filas):
    y = 0.84 - i * 0.092
    am, ae = media(nm), media(ne)
    ax.text(xs[0], y, nom, fontsize=17, transform=ax.transAxes, va="center")
    ax.text(xs[1], y, pm, fontsize=15, color=GRIS, transform=ax.transAxes, va="center")
    ax.text(xs[3], y, pe, fontsize=15, color=GRIS, transform=ax.transAxes, va="center")
    for x_, a_ in ((xs[2], am), (xs[4], ae)):
        if a_ is None:
            ax.text(x_, y, "n/a", fontsize=17, color=GRIS, transform=ax.transAxes, va="center"); continue
        col = "#1a7f4b" if a_ >= 95 else ("#b8860b" if a_ >= 80 else "#c0392b")
        ax.text(x_, y, f"{a_:.0f}%", fontsize=18, fontweight="bold", color=col, transform=ax.transAxes, va="center")
guardar(fig, "13_tabla_condiciones.png", NOTA + " Verde 95% o más, ámbar 80 a 95%, rojo menos de 80%.")
