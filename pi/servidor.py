"""Servidor web de RockU (Flask) para la Raspberry Pi.

Sirve el panel (pi/dashboard/), la API JSON, el stream SSE y las exportaciones CSV.
La fuente de datos puede ser el simulador o la correa real (telefono + ESP32).

    python3 servidor.py --fuente sim
    python3 servidor.py --fuente real --telefono http://192.168.1.84:8080 --calibracion calibracion.json

Contrato de la API: docs/api.md
"""
import argparse
import json
import logging
import os
import queue
import time

from flask import Flask, Response, abort, jsonify, request, send_file, send_from_directory, stream_with_context

from fuentes import FuenteReal, FuenteSim
from registro import Registro

AQUI = os.path.dirname(os.path.abspath(__file__))
PING_S = 15.0


def sse(nombre, datos):
    """Formatea un evento Server-Sent Events."""
    return "event: %s\ndata: %s\n\n" % (nombre, json.dumps(datos, ensure_ascii=False, separators=(",", ":")))


def generar_sse(fuente, ping_s=PING_S, parar=None):
    """Generador del stream: snapshot inicial, luego los eventos de la fuente, con ping periodico."""
    q = fuente.suscribir()                       # primero suscribir y luego tomar el snapshot: no se pierde nada
    try:
        yield sse("snapshot", fuente.snapshot())
        ultimo = time.monotonic()
        while not (parar and parar.is_set()):
            try:
                nombre, datos = q.get(timeout=1.0)
                yield sse(nombre, datos)
                ultimo = time.monotonic()
            except queue.Empty:
                pass
            if time.monotonic() - ultimo >= ping_s:
                yield ": ping\n\n"
                ultimo = time.monotonic()
    finally:
        fuente.desuscribir(q)


def _entero(valor, defecto=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def crear_app(fuente, registro=None, dir_panel=None):
    dir_panel = dir_panel or os.path.join(AQUI, "dashboard")
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    try:
        app.json.ensure_ascii = False
    except AttributeError:
        pass

    @app.after_request
    def cors(r):
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        if request.path.startswith("/api/") or request.path in ("/", "/mini"):
            r.headers.setdefault("Cache-Control", "no-cache")
        return r

    # ---------- API ----------
    @app.get("/api/snapshot")
    def snapshot():
        return jsonify(fuente.snapshot())

    @app.get("/api/status")
    def status():
        return jsonify(fuente.status())

    @app.get("/api/events")
    def eventos():
        return jsonify(fuente.lista_eventos(request.args.get("tipo") or None,
                                            _entero(request.args.get("desde")),
                                            _entero(request.args.get("limite"), 100)))

    @app.get("/api/stream")
    def stream():
        return Response(stream_with_context(generar_sse(fuente)), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    @app.get("/api/frame.jpg")
    def frame():
        jpg = fuente.frame_jpg()
        if jpg is None:
            abort(404)
        return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/foto/<int:eid>.jpg")
    def foto(eid):
        ruta = fuente.ruta_foto(eid)
        if not ruta:
            abort(404)
        return send_file(ruta, mimetype="image/jpeg")

    @app.post("/api/cmd")
    def cmd():
        d = request.get_json(silent=True) or {}
        if not d.get("accion"):
            return jsonify({"ok": False, "error": "falta 'accion'"}), 400
        ok, msg = fuente.cmd(d)
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        return jsonify({"ok": True})

    @app.post("/event")
    def evento_esp():
        d = request.get_json(silent=True) or request.form.to_dict() or {}
        try:
            dist = float(d.get("distancia_mm"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "falta 'distancia_mm'"}), 400
        eid = fuente.evento_esp(dist, _entero(d.get("n")))
        return jsonify({"ok": True, "id": eid})

    # ---------- exportaciones ----------
    def _csv(generador, nombre):
        return Response(generador, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % nombre})

    @app.get("/export/eventos.csv")
    def exp_eventos():
        if not registro:
            abort(404)
        return _csv(registro.exportar_eventos(_entero(request.args.get("desde")), _entero(request.args.get("hasta")),
                                              request.args.get("sep")), "eventos.csv")

    @app.get("/export/muestras.csv")
    def exp_muestras():
        if not registro:
            abort(404)
        return _csv(registro.exportar_muestras(_entero(request.args.get("desde")), _entero(request.args.get("hasta")),
                                               request.args.get("sep")), "muestras.csv")

    # ---------- panel estatico ----------
    @app.get("/")
    def raiz():
        return send_from_directory(dir_panel, "index.html")

    @app.get("/mini")
    def mini():
        return send_from_directory(dir_panel, "mini.html")

    @app.get("/<path:ruta>")
    def estaticos(ruta):
        return send_from_directory(dir_panel, ruta)

    return app


def main():
    ap = argparse.ArgumentParser(description="Servidor web de RockU")
    ap.add_argument("--fuente", choices=["sim", "real"], default="sim")
    ap.add_argument("--puerto", type=int, default=5000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--telefono", default="http://192.168.1.84:8080", help="URL de CorreaCam (fuente real)")
    ap.add_argument("--calibracion", default="calibracion.json")
    ap.add_argument("--db", default=None, help="archivo SQLite (por defecto rockU.db, o rockU_sim.db en sim)")
    ap.add_argument("--dir-fotos", default="fotos")
    ap.add_argument("--dias-muestras", type=int, default=30, help="dias de muestras que se conservan")
    ap.add_argument("--sin-auto", action="store_true", help="simulador sin fallas automaticas")
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = a.db or ("rockU_sim.db" if a.fuente == "sim" else "rockU.db")
    registro = Registro(db)
    registro.podar_muestras(a.dias_muestras)
    if a.fuente == "sim":
        fuente = FuenteSim(registro, a.dir_fotos, auto=not a.sin_auto)
    else:
        fuente = FuenteReal(a.telefono, a.calibracion, registro, a.dir_fotos)
    fuente.iniciar()
    app = crear_app(fuente, registro)
    logging.info("fuente %s, panel en http://%s:%d/ y pantalla en /mini", a.fuente, a.host, a.puerto)
    try:
        app.run(host=a.host, port=a.puerto, threaded=True, use_reloader=False)
    finally:
        fuente.detener()
        registro.cerrar()


if __name__ == "__main__":
    main()
