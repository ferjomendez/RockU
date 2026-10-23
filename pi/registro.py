"""Registro en SQLite de muestras y eventos, con exportacion a CSV.

- Hilo seguro: todas las operaciones toman el mismo candado.
- Las muestras (1 por segundo) se acumulan en memoria y se escriben por lotes para
  no desgastar la tarjeta microSD. Los eventos se escriben al instante.
- Exportacion: UTF-8 con BOM (Excel en espanol lo abre bien), separador configurable
  y decimales con punto.
"""
import csv
import io
import json
import sqlite3
import threading
from datetime import datetime

LOTE_MUESTRAS = 10          # filas por escritura
SEPARADORES = {",": ",", ";": ";", "tab": "\t", "\\t": "\t"}


def _iso(t_ms):
    """Fecha y hora local con zona horaria, a partir de milisegundos desde epoch."""
    return datetime.fromtimestamp(t_ms / 1000).astimezone().isoformat(timespec="seconds")


def separador(valor):
    """Valida el separador pedido; cae en ';' si no es uno conocido."""
    return SEPARADORES.get(valor or ";", ";")


class Registro:
    def __init__(self, ruta="rockU.db"):
        self.ruta = ruta
        self._lock = threading.RLock()
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            if ruta != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS muestras (
                    t INTEGER NOT NULL, vel REAL, lat REAL, ang REAL, dist REAL, estado TEXT);
                CREATE INDEX IF NOT EXISTS ix_muestras_t ON muestras(t);
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER NOT NULL, tipo TEXT NOT NULL,
                    dur_s REAL, detalle TEXT, valor TEXT, foto TEXT, snap TEXT);
                CREATE INDEX IF NOT EXISTS ix_eventos_t ON eventos(t);
            """)
            self._db.commit()
        self._buf = []

    # ---------- escritura ----------
    def guardar_muestra(self, m):
        with self._lock:
            self._buf.append((m["t"], m["vel"], m["lat"], m["ang"], m["dist"], m["estado"]))
            if len(self._buf) >= LOTE_MUESTRAS:
                self._flush()

    def _flush(self):
        if self._buf:
            self._db.executemany("INSERT INTO muestras VALUES (?,?,?,?,?,?)", self._buf)
            self._db.commit()
            self._buf = []

    def flush(self):
        with self._lock:
            self._flush()

    def guardar_evento(self, ev):
        """Inserta un evento y devuelve su id."""
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO eventos (t, tipo, dur_s, detalle, valor, foto, snap) VALUES (?,?,?,?,?,?,?)",
                (ev["t"], ev["tipo"], ev.get("dur_s"), ev.get("detalle"), ev.get("valor"),
                 ev.get("foto"), json.dumps(ev.get("snap") or {})))
            self._db.commit()
            return cur.lastrowid

    def cerrar_evento(self, eid, dur_s):
        with self._lock:
            self._db.execute("UPDATE eventos SET dur_s=? WHERE id=?", (dur_s, eid))
            self._db.commit()

    def actualizar_foto(self, eid, foto):
        with self._lock:
            self._db.execute("UPDATE eventos SET foto=? WHERE id=?", (foto, eid))
            self._db.commit()

    def podar_muestras(self, dias=30):
        """Borra muestras mas antiguas que `dias` (las de 1 Hz crecen rapido)."""
        from time import time
        corte = int((time() - dias * 86400) * 1000)
        with self._lock:
            self._flush()
            self._db.execute("DELETE FROM muestras WHERE t < ?", (corte,))
            self._db.commit()

    # ---------- lectura ----------
    @staticmethod
    def _evento(r):
        try:
            snap = json.loads(r["snap"] or "{}")
        except ValueError:
            snap = {}
        return {"id": r["id"], "t": r["t"], "tipo": r["tipo"], "dur_s": r["dur_s"],
                "detalle": r["detalle"] or "", "valor": r["valor"] or "", "foto": r["foto"], "snap": snap}

    def vacia(self):
        with self._lock:
            self._flush()
            n = self._db.execute("SELECT (SELECT COUNT(*) FROM eventos) + (SELECT COUNT(*) FROM muestras)").fetchone()[0]
            return n == 0

    def cargar_muestras(self, limite=900):
        """Ultimas `limite` muestras, en orden cronologico."""
        with self._lock:
            self._flush()
            filas = self._db.execute(
                "SELECT t, vel, lat, ang, dist, estado FROM muestras ORDER BY t DESC LIMIT ?", (limite,)).fetchall()
        return [dict(r) for r in reversed(filas)]

    def cargar_eventos(self, limite=200, tipo=None, desde=None):
        """Eventos mas recientes primero."""
        sql, args = "SELECT * FROM eventos WHERE 1=1", []
        if tipo:
            sql += " AND tipo=?"; args.append(tipo)
        if desde is not None:
            sql += " AND t>=?"; args.append(int(desde))
        sql += " ORDER BY t DESC, id DESC LIMIT ?"; args.append(int(limite))
        with self._lock:
            return [self._evento(r) for r in self._db.execute(sql, args).fetchall()]

    def ultima_muestra_t(self):
        with self._lock:
            self._flush()
            r = self._db.execute("SELECT MAX(t) FROM muestras").fetchone()[0]
        return r

    # ---------- exportacion CSV ----------
    def _csv(self, cabecera, filas, sep):
        """Generador de bloques bytes: BOM, cabecera y filas."""
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=sep, lineterminator="\r\n")
        w.writerow(cabecera)
        yield b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
        buf.seek(0); buf.truncate()
        n = 0
        for f in filas:
            w.writerow(f)
            n += 1
            if n % 500 == 0:
                yield buf.getvalue().encode("utf-8")
                buf.seek(0); buf.truncate()
        if buf.getvalue():
            yield buf.getvalue().encode("utf-8")

    @staticmethod
    def _rango(desde, hasta):
        sql, args = "", []
        if desde is not None:
            sql += " AND t>=?"; args.append(int(desde))
        if hasta is not None:
            sql += " AND t<=?"; args.append(int(hasta))
        return sql, args

    def exportar_eventos(self, desde=None, hasta=None, sep=";"):
        sep = separador(sep)
        extra, args = self._rango(desde, hasta)
        with self._lock:
            self._flush()
            filas = self._db.execute("SELECT * FROM eventos WHERE 1=1" + extra + " ORDER BY t, id", args).fetchall()
        datos = [[r["id"], _iso(r["t"]), r["t"], r["tipo"],
                  "" if r["dur_s"] is None else round(r["dur_s"], 1), r["valor"] or "", r["detalle"] or "",
                  r["foto"] or ""] for r in filas]
        cab = ["id", "fecha_hora", "t_ms", "tipo", "duracion_s", "medida", "detalle", "foto"]
        return self._csv(cab, datos, sep)

    def exportar_muestras(self, desde=None, hasta=None, sep=";"):
        sep = separador(sep)
        extra, args = self._rango(desde, hasta)
        with self._lock:
            self._flush()
            filas = self._db.execute(
                "SELECT t, vel, lat, ang, dist, estado FROM muestras WHERE 1=1" + extra + " ORDER BY t", args).fetchall()
        datos = ([_iso(r["t"]), r["t"], _num(r["vel"]), _num(r["lat"]), _num(r["ang"]), _num(r["dist"]), r["estado"]]
                 for r in filas)
        cab = ["fecha_hora", "t_ms", "vel_cm_s", "desvio_mm", "angulo_deg", "distancia_mm", "estado"]
        return self._csv(cab, datos, sep)

    def cerrar(self):
        with self._lock:
            self._flush()
            self._db.close()


def _num(v):
    return "" if v is None else round(v, 2)
