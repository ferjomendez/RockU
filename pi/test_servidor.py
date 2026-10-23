"""Pruebas del servidor RockU. Ejecutar:  python3 test_servidor.py   (o con pytest)

Usa el cliente de prueba de Flask con el simulador acelerado y una fuente real contra un
telefono falso que sirve frames generados por simulador.py.
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import servidor
from fuentes import FuenteReal, FuenteSim
from registro import Registro


def esperar(cond, limite=10.0, paso=0.05):
    t0 = time.time()
    while time.time() - t0 < limite:
        if cond():
            return True
        time.sleep(paso)
    return False


def leer_sse(resp, n):
    """Lee los primeros n bloques SSE (no comentarios) de una respuesta sin buffer."""
    it = iter(resp.response)
    out, buf = [], b""
    while len(out) < n:
        buf += next(it)
        while b"\n\n" in buf:
            bloque, buf = buf.split(b"\n\n", 1)
            if bloque.startswith(b":"):
                continue
            lineas = bloque.decode().split("\n")
            nombre = lineas[0].split(": ", 1)[1]
            datos = json.loads(lineas[1].split(": ", 1)[1])
            out.append((nombre, datos))
    return out


class TestSim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(cls.tmp, "panel", "css"))
        for n, txt in (("index.html", "<h1>panel</h1>"), ("mini.html", "<h1>mini</h1>"), ("css/x.css", "a{}")):
            with open(os.path.join(cls.tmp, "panel", n), "w") as f:
                f.write(txt)
        cls.reg = Registro(os.path.join(cls.tmp, "t.db"))
        cls.fuente = FuenteSim(cls.reg, os.path.join(cls.tmp, "fotos"), auto=False, escala=5.0, semilla=1)
        cls.fuente.iniciar()
        cls.app = servidor.crear_app(cls.fuente, cls.reg, os.path.join(cls.tmp, "panel"))
        cls.c = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.fuente.detener()
        cls.reg.cerrar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def estado(self):
        return self.c.get("/api/status").get_json()["estado"]

    def cmd(self, **d):
        r = self.c.post("/api/cmd", json=d)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(r.get_json()["ok"])

    def test_1_snapshot(self):
        s = self.c.get("/api/snapshot").get_json()
        for k in ("fuente", "t", "estado", "desde", "cand", "medida", "senal", "fps", "latencia_ms", "cpu", "temp_c",
                  "esp_ultimo_ms", "calibrando", "silenciada", "limites", "muestras", "segmentos", "eventos"):
            self.assertIn(k, s)
        self.assertEqual(s["fuente"], "sim")
        self.assertEqual(s["estado"], "NORMAL")
        self.assertGreaterEqual(len(s["muestras"]), 300)
        self.assertEqual(len(s["eventos"]), 8)
        self.assertEqual(set(s["medida"]), {"vel", "lat", "ang", "dist"})
        self.assertEqual(s["limites"]["vel_min"], 0.8)
        self.assertIsNone(s["segmentos"][-1]["t1"])
        ev = s["eventos"][0]
        self.assertEqual(set(ev), {"id", "t", "tipo", "dur_s", "detalle", "valor", "foto", "snap"})
        ts = [e["t"] for e in s["eventos"]]
        self.assertEqual(ts, sorted(ts, reverse=True))

    def test_2_stream(self):
        r = self.c.get("/api/stream", buffered=False)
        self.assertTrue(r.mimetype.startswith("text/event-stream"))
        bloques = leer_sse(r, 3)
        r.close()
        self.assertEqual(bloques[0][0], "snapshot")
        self.assertIn("tick", [b[0] for b in bloques[1:]])
        self.assertEqual(len(self.fuente._subs), 0)         # al cerrar se desuscribe

    def test_3_detener_lleva_a_detenida(self):
        self.cmd(accion="escenario", nombre="detener")
        self.assertTrue(esperar(lambda: self.estado() == "DETENIDA", 12), "no llego a DETENIDA")
        ev = self.c.get("/api/events?tipo=DETENIDA&limite=1").get_json()[0]
        self.assertIsNone(ev["dur_s"])                          # sigue en curso
        self.cmd(accion="escenario", nombre="normal")
        self.assertTrue(esperar(lambda: self.estado() == "NORMAL", 12), "no volvio a NORMAL")
        ev = self.c.get("/api/events?tipo=DETENIDA&limite=1").get_json()[0]
        self.assertIsNotNone(ev["dur_s"])

    def test_4_evento_esp_dispara_objeto(self):
        self.assertTrue(esperar(lambda: self.estado() == "NORMAL", 12))
        r = self.c.post("/event", json={"distancia_mm": 74, "n": 12})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(self.estado(), "OBJETO_DETECTADO")
        ev = self.c.get("/api/events?tipo=OBJETO_DETECTADO&limite=1").get_json()[0]
        self.assertIn("74", ev["detalle"])
        self.assertEqual(self.c.post("/event", json={}).status_code, 400)
        self.assertTrue(esperar(lambda: self.estado() == "NORMAL", 12))

    def test_5_cmd_invalidos_y_silenciar(self):
        self.assertEqual(self.c.post("/api/cmd", json={"accion": "nada"}).status_code, 400)
        self.assertEqual(self.c.post("/api/cmd", json={"accion": "escenario", "nombre": "xx"}).status_code, 400)
        self.cmd(accion="silenciar", valor=True)
        self.assertTrue(self.c.get("/api/status").get_json()["silenciada"])
        self.cmd(accion="objetivo", vel=10, lat=0, ang=0)
        self.cmd(accion="auto", valor=False)

    def test_6_calibrar(self):
        self.cmd(accion="calibrar")
        self.assertTrue(esperar(lambda: self.estado() == "CALIBRANDO", 5))
        self.assertIsNotNone(self.c.get("/api/status").get_json()["calibrando"])
        self.assertTrue(esperar(lambda: self.estado() == "NORMAL", 20))

    def test_7_csv_con_bom(self):
        time.sleep(1.2)                                         # al menos una muestra viva
        r = self.c.get("/export/eventos.csv")
        datos = r.get_data()
        self.assertTrue(datos.startswith(b"\xef\xbb\xbf"))
        self.assertIn("text/csv", r.mimetype)
        lineas = datos.decode("utf-8-sig").strip().split("\r\n")
        self.assertEqual(lineas[0], "id;fecha_hora;t_ms;tipo;duracion_s;medida;detalle;foto")
        self.assertGreaterEqual(len(lineas), 9)
        r = self.c.get("/export/eventos.csv?sep=,")
        self.assertTrue(r.get_data().decode("utf-8-sig").startswith("id,fecha_hora"))
        r = self.c.get("/export/muestras.csv?sep=tab")
        self.assertTrue(r.get_data().startswith(b"\xef\xbb\xbffecha_hora\tt_ms\tvel_cm_s"))
        ahora = int(time.time() * 1000)
        vacio = self.c.get("/export/eventos.csv?desde=%d" % (ahora + 10 ** 9)).get_data().decode("utf-8-sig").strip().split("\r\n")
        self.assertEqual(len(vacio), 1)

    def test_8_estaticos_y_cors(self):
        self.assertIn(b"panel", self.c.get("/").get_data())
        self.assertIn(b"mini", self.c.get("/mini").get_data())
        self.assertEqual(self.c.get("/css/x.css").status_code, 200)
        self.assertEqual(self.c.get("/api/frame.jpg").status_code, 404)
        self.assertEqual(self.c.get("/foto/999.jpg").status_code, 404)
        self.assertEqual(self.c.get("/api/snapshot").headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(self.c.open("/api/cmd", method="OPTIONS").status_code, 200)


class TestRegistro(unittest.TestCase):
    def test_persistencia(self):
        tmp = tempfile.mkdtemp()
        ruta = os.path.join(tmp, "r.db")
        r = Registro(ruta)
        self.assertTrue(r.vacia())
        eid = r.guardar_evento({"t": 1000, "tipo": "DETENIDA", "detalle": "x", "valor": "0.0 cm/s", "snap": {"vel": 0}})
        r.cerrar_evento(eid, 5.5)
        for i in range(12):
            r.guardar_muestra({"t": 2000 + i * 1000, "vel": 10.0, "lat": 0.1, "ang": 0.0, "dist": 120.0, "estado": "NORMAL"})
        r.cerrar()
        r = Registro(ruta)
        self.assertFalse(r.vacia())
        self.assertEqual(r.cargar_eventos()[0]["dur_s"], 5.5)
        self.assertEqual(len(r.cargar_muestras()), 12)
        r.cerrar()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Telefono falso
# ---------------------------------------------------------------------------
class TelefonoFalso:
    """Sirve /capture con frames de simulador.py. `vel_mm_s` se puede cambiar en caliente."""

    def __init__(self):
        import simulador
        self.esc = simulador.Escena(seed=1, mm_px=0.52, w=540, h=720)     # 0.585 mm/px tras reducir a 480 de ancho
        self.vel, self.lat, self.ang = 100.0, 0.0, 0.0
        self.s, self.t, self.n = 0.0, time.time(), 0
        self.lock = threading.Lock()
        self.vivo = True
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/capture") and outer.vivo:
                    jpg = outer.frame()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(jpg)))
                    self.end_headers()
                    self.wfile.write(jpg)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def frame(self):
        with self.lock:
            ahora = time.time()
            self.s += self.vel * (ahora - self.t)
            self.t = ahora
            self.n += 1
            return self.esc.render(self.s, self.lat, self.ang, self.vel, 0.03, np.random.default_rng(self.n))

    def cerrar(self):
        self.srv.shutdown()


class TestReal(unittest.TestCase):
    def test_flujo_real(self):
        tmp = tempfile.mkdtemp()
        tel = TelefonoFalso()
        reg = Registro(os.path.join(tmp, "r.db"))
        f = FuenteReal(tel.url, os.path.join(tmp, "calibracion.json"), reg, os.path.join(tmp, "fotos"), calib_s=3.0)
        f.iniciar()
        app = servidor.crear_app(f, reg, tmp)
        c = app.test_client()
        est = lambda: c.get("/api/status").get_json()["estado"]
        try:
            # sin calibracion parte en CALIBRANDO
            self.assertTrue(esperar(lambda: c.get("/api/status").get_json()["fps"] > 3, 15), "no llegan frames")
            self.assertEqual(est(), "CALIBRANDO")
            self.assertEqual(c.get("/api/snapshot").get_json()["fuente"], "real")
            # calibrar con la correa en marcha
            self.assertEqual(c.post("/api/cmd", json={"accion": "calibrar"}).status_code, 200)
            self.assertTrue(esperar(lambda: os.path.isfile(os.path.join(tmp, "calibracion.json")), 20),
                            "no se calibro: %s" % f.error_calibracion)
            self.assertTrue(esperar(lambda: est() == "NORMAL", 10), "no llego a NORMAL: %s" % est())
            s = c.get("/api/snapshot").get_json()
            self.assertAlmostEqual(s["medida"]["vel"], 10.0, delta=1.5)
            self.assertGreater(s["limites"]["vel_min"], 0)
            # frame anotado
            r = c.get("/api/frame.jpg")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.get_data().startswith(b"\xff\xd8"))
            # el ESP32 avisa de un objeto: estado, evento y foto
            r = c.post("/event", json={"distancia_mm": 70, "n": 1})
            eid = r.get_json()["id"]
            self.assertIsNotNone(eid)
            self.assertEqual(est(), "OBJETO_DETECTADO")
            self.assertTrue(esperar(lambda: c.get("/foto/%d.jpg" % eid).status_code == 200, 5), "sin foto")
            self.assertTrue(esperar(lambda: est() == "NORMAL", 10))
            # correa detenida
            tel.vel = 0.0
            self.assertTrue(esperar(lambda: est() == "DETENIDA", 15), "no detecto la detencion: %s" % est())
            tel.vel = 100.0
            self.assertTrue(esperar(lambda: est() == "NORMAL", 15), "no volvio a NORMAL: %s" % est())
            # el telefono deja de responder: SIN_SENAL a los 2 s
            tel.vivo = False
            self.assertTrue(esperar(lambda: est() == "SIN_SENAL", 8), "no paso a SIN_SENAL")
            tel.vivo = True
            self.assertTrue(esperar(lambda: est() == "NORMAL", 15), "no se recupero: %s" % est())
            tipos = {e["tipo"] for e in c.get("/api/events?limite=50").get_json()}
            self.assertTrue({"OBJETO_DETECTADO", "DETENIDA", "SIN_SENAL"} <= tipos, tipos)
        finally:
            f.detener()
            tel.cerrar()
            reg.cerrar()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
