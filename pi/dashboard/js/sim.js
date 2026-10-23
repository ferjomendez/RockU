/* RockU: simulador de la correa.
   Genera las mismas medidas que entregará el detector real (velocidad, desvío,
   ángulo, distancia del HC-SR04) y aplica una máquina de estados con
   confirmación por persistencia, igual que pi/deteccion.py.
   Cuando llegue la correa, esta fuente se reemplaza por /api/stream. */
(function (g) {
  "use strict";

  var STATES = {
    CALIBRANDO:       { key: "CALIBRANDO",       label: "Calibrando",       tone: "idle", text: "Midiendo la referencia de bordes y de movimiento." },
    NORMAL:           { key: "NORMAL",           label: "Normal",           tone: "ok",   text: "La correa avanza y los bordes están dentro de los límites." },
    DETENIDA:         { key: "DETENIDA",         label: "Detenida",         tone: "stop", text: "No hay desplazamiento entre frames." },
    DESALINEADA:      { key: "DESALINEADA",      label: "Desalineada",      tone: "warn", text: "Las líneas de borde se salieron de la referencia." },
    OBJETO_DETECTADO: { key: "OBJETO_DETECTADO", label: "Objeto detectado", tone: "obj",  text: "El sensor midió una distancia menor a la de la correa vacía." },
    SIN_SENAL:        { key: "SIN_SENAL",        label: "Sin señal",        tone: "off",  text: "No llegan imágenes del teléfono." }
  };
  var ORDER = ["CALIBRANDO", "NORMAL", "DETENIDA", "DESALINEADA", "OBJETO_DETECTADO", "SIN_SENAL"];

  var LIM = {
    velNom: 10,      // cm/s
    velMin: 0.8,     // bajo esto se considera detenida
    latMax: 8,       // mm
    angMax: 2,       // grados
    base: 120,       // mm, distancia del sensor a la correa vacía
    objDrop: 25,     // mm de caída para confirmar objeto
    fov: 420,        // mm de campo visual
    sensorX: 70      // mm, posición del sensor dentro del campo
  };
  var NEED = { DETENIDA: 20, DESALINEADA: 15, OBJETO_DETECTADO: 3, SIN_SENAL: 20, NORMAL: 8 }; // ticks de 0.1 s
  var STEP = 0.1;

  function rnd(a, b) { return a + Math.random() * (b - a); }
  function gauss() { return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5; }
  function pick(a) { return a[Math.floor(Math.random() * a.length)]; }

  function Sim(opts) {
    opts = opts || {};
    this.a = { vel: LIM.velNom, lat: 0, ang: 0 };      // valores reales
    this.tg = { vel: LIM.velNom, lat: 0, ang: 0 };     // objetivos
    this.m = { vel: LIM.velNom, lat: 0, ang: 0, dist: LIM.base }; // medidas con ruido
    this.signal = true;
    this.phase = 0;
    this.rocks = [];
    this.acc = 0;
    this.ticks = 0;
    this.objHold = 0;
    this.calib = null;
    this.state = "NORMAL";
    this.since = Date.now();
    this.cand = { state: "NORMAL", n: 0 };
    this.samples = [];
    this.segments = [];
    this.events = [];
    this.evSeq = 0;
    this.openEvent = null;
    this.incidentUntil = 0;
    this.auto = opts.auto !== false;
    this.autoIn = rnd(8, 14);
    this.listeners = { event: [], state: [], eventEnd: [] };
    this.muted = false;
    this.fps = 14.6;
    this.lat = 72;
    this.cpu = 31;
    this.temp = 53;
    this.lastEventT = Date.now() - 420000;
    this.seed();
  }

  Sim.prototype.on = function (name, fn) { this.listeners[name].push(fn); };
  Sim.prototype.emit = function (name, a, b) {
    var l = this.listeners[name];
    for (var i = 0; i < l.length; i++) l[i](a, b);
  };

  /* ---------- historial inicial (última hora) para que el panel no parta vacío ---------- */
  Sim.prototype.seed = function () {
    var now = Date.now(), self = this;
    var plan = [
      { ago: 3480, dur: 38, tipo: "DESALINEADA", lat: 10.4, ang: 1.2 },
      { ago: 3120, dur: 4,  tipo: "OBJETO_DETECTADO", dist: 78 },
      { ago: 2760, dur: 71, tipo: "DETENIDA" },
      { ago: 2250, dur: 5,  tipo: "OBJETO_DETECTADO", dist: 69 },
      { ago: 1860, dur: 24, tipo: "DESALINEADA", lat: -9.1, ang: -2.6 },
      { ago: 1320, dur: 12, tipo: "SIN_SENAL" },
      { ago: 960,  dur: 48, tipo: "DETENIDA" },
      { ago: 420,  dur: 5,  tipo: "OBJETO_DETECTADO", dist: 74 }
    ];
    var t = now - 3600000;
    this.segments.push({ state: "CALIBRANDO", t0: t, t1: t + 30000 });
    t += 30000;
    plan.forEach(function (p) {
      var t0 = now - p.ago * 1000, t1 = t0 + p.dur * 1000;
      if (t0 > t) self.segments.push({ state: "NORMAL", t0: t, t1: t0 });
      self.segments.push({ state: p.tipo, t0: t0, t1: t1 });
      t = t1;
      var ev = self.makeEvent(p.tipo, t0, {
        vel: p.tipo === "DETENIDA" ? 0 : (p.tipo === "SIN_SENAL" ? 10 : 10.1),
        lat: p.lat || 0.4, ang: p.ang || 0.1, dist: p.dist || LIM.base,
        phase: Math.random() * 434,
        rocks: p.tipo === "OBJETO_DETECTADO" ? [{ x: rnd(150, 260), y: rnd(-25, 25), w: rnd(34, 48), h: rnd(28, 40), ht: rnd(36, 50), seed: Math.random() * 1000, hit: true }] : []
      });
      ev.dur = p.dur;
      self.events.unshift(ev);
    });
    this.segments.push({ state: "NORMAL", t0: t, t1: null });
    this.since = t;
    // últimos 5 minutos de muestras, en régimen normal
    for (var i = 300; i >= 1; i--) {
      this.samples.push({ t: now - i * 1000, vel: LIM.velNom + gauss() * 0.14, lat: gauss() * 0.7 + Math.sin(i / 23) * 0.9, ang: gauss() * 0.12, dist: LIM.base + gauss() * 0.9, state: "NORMAL" });
    }
  };

  Sim.prototype.makeEvent = function (tipo, t, d) {
    var detalle, valor;
    if (tipo === "DETENIDA") { detalle = "Velocidad bajo " + LIM.velMin.toFixed(1) + " cm/s"; valor = "0.0 cm/s"; }
    else if (tipo === "DESALINEADA") {
      var sg = d.lat >= 0 ? "+" : "";
      detalle = "Desvío " + sg + d.lat.toFixed(1) + " mm, ángulo " + (d.ang >= 0 ? "+" : "") + d.ang.toFixed(1) + "°";
      valor = sg + d.lat.toFixed(1) + " mm";
    } else if (tipo === "OBJETO_DETECTADO") {
      detalle = "Obstáculo a " + Math.round(d.dist) + " mm del sensor (correa vacía: " + LIM.base + " mm)";
      valor = Math.round(LIM.base - d.dist) + " mm de alto";
    } else if (tipo === "SIN_SENAL") { detalle = "Sin frames del teléfono"; valor = "Sin datos"; }
    else { detalle = ""; valor = ""; }
    return { id: ++this.evSeq, t: t, tipo: tipo, dur: null, detalle: detalle, valor: valor, snap: d };
  };

  /* ---------- escenarios ---------- */
  Sim.prototype.restore = function () {
    this.tg.vel = LIM.velNom; this.tg.lat = 0; this.tg.ang = 0;
    this.signal = true; this.incidentUntil = 0;
  };
  Sim.prototype.setTargets = function (o) {
    if (o.vel !== undefined) this.tg.vel = o.vel;
    if (o.lat !== undefined) this.tg.lat = o.lat;
    if (o.ang !== undefined) this.tg.ang = o.ang;
    this.incidentUntil = 0;
  };
  Sim.prototype.run = function (name) {
    var secs = this.ticks * STEP;
    switch (name) {
      case "normal": this.restore(); break;
      case "detener": this.tg.vel = 0; this.incidentUntil = secs + rnd(10, 15); break;
      case "izquierda": this.tg.lat = -rnd(10.5, 15); this.tg.ang = -rnd(0.8, 2.4); this.incidentUntil = secs + rnd(12, 17); break;
      case "derecha": this.tg.lat = rnd(10.5, 15); this.tg.ang = rnd(0.8, 2.4); this.incidentUntil = secs + rnd(12, 17); break;
      case "angulo": this.tg.ang = pick([-1, 1]) * rnd(3.2, 4.6); this.tg.lat = rnd(-4, 4); this.incidentUntil = secs + rnd(12, 17); break;
      case "objeto": this.spawnRock(); break;
      case "senal": this.signal = false; this.incidentUntil = secs + rnd(6, 9); break;
      case "calibrar": this.calibrate(); break;
    }
  };
  Sim.prototype.spawnRock = function () {
    var w = rnd(46, 68);
    this.rocks.push({ x: -70, y: rnd(-28, 28), w: w, h: w * rnd(0.7, 0.95), ht: rnd(34, 54), seed: Math.random() * 1000, hit: false, seen: 0 });
  };
  Sim.prototype.calibrate = function () {
    this.calib = { left: 60 }; // 6 s
  };

  /* ---------- un paso de 0.1 s ---------- */
  Sim.prototype.step = function () {
    var dt = STEP, a = this.a, tg = this.tg, now = Date.now();
    this.ticks++;
    var secs = this.ticks * STEP;

    var kv = 1 - Math.exp(-dt / (tg.vel < a.vel ? 0.35 : 0.9));
    var kl = 1 - Math.exp(-dt / 0.9);
    a.vel += (tg.vel - a.vel) * kv; if (a.vel < 0.01 && tg.vel === 0) a.vel = 0;
    a.lat += (tg.lat - a.lat) * kl;
    a.ang += (tg.ang - a.ang) * kl;

    var adv = a.vel * 10 * dt;
    this.phase = (this.phase + adv) % 434;

    // piedras
    var objSeen = false, d = LIM.base;
    for (var i = this.rocks.length - 1; i >= 0; i--) {
      var r = this.rocks[i];
      r.x += adv;
      if (Math.abs(r.x - LIM.sensorX) < r.w / 2 + 3) {
        r.seen = (r.seen || 0) + 1;
        objSeen = true;
        d = Math.min(d, LIM.base - r.ht);
        if (r.seen >= 2 && !r.hit) { r.hit = true; this.objHold = 45; this.lastEventT = now; }
      }
      if (r.x > LIM.fov + 80) this.rocks.splice(i, 1);
    }
    if (this.objHold > 0) this.objHold--;

    // incidentes con fin programado
    if (this.incidentUntil && secs >= this.incidentUntil) this.restore();

    // medidas
    if (this.signal) {
      this.m.vel = Math.max(0, a.vel + gauss() * (a.vel < 0.3 ? 0.03 : 0.14));
      this.m.lat = a.lat + gauss() * 0.35;
      this.m.ang = a.ang + gauss() * 0.07;
      this.m.dist = d + gauss() * (objSeen ? 1.2 : 0.7);
      this.fps = 14.3 + gauss() * 0.5;
      this.lat = 70 + gauss() * 6 + (a.vel === 0 ? -8 : 0);
    } else { this.fps = 0; }
    this.cpu = Math.max(18, Math.min(58, this.cpu + gauss() * 1.6 + (31 - this.cpu) * 0.05));
    this.temp = Math.max(48, Math.min(62, this.temp + gauss() * 0.1 + (53 - this.temp) * 0.01));

    // clasificador con persistencia
    var raw;
    if (this.calib) {
      this.calib.left--;
      raw = "CALIBRANDO";
      if (this.calib.left <= 0) { this.calib = null; raw = "NORMAL"; this.cand = { state: "NORMAL", n: NEED.NORMAL }; }
    } else if (!this.signal) raw = "SIN_SENAL";
    else if (this.objHold > 0) raw = "OBJETO_DETECTADO";
    else if (this.m.vel < LIM.velMin) raw = "DETENIDA";
    else if (Math.abs(this.m.lat) > LIM.latMax || Math.abs(this.m.ang) > LIM.angMax) raw = "DESALINEADA";
    else raw = "NORMAL";

    if (raw === this.state) { this.cand = { state: raw, n: 0 }; }
    else {
      if (this.cand.state === raw) this.cand.n++; else this.cand = { state: raw, n: 1 };
      var need = raw === "CALIBRANDO" ? 1 : (NEED[raw] || 5);
      if (this.cand.n >= need) this.setState(raw, now);
    }

    // muestras a 1 Hz
    if (this.ticks % 10 === 0) {
      this.samples.push({ t: now, vel: this.m.vel, lat: this.m.lat, ang: this.m.ang, dist: this.m.dist, state: this.state });
      if (this.samples.length > 900) this.samples.shift();
    }

    // director automático
    if (this.auto && !this.incidentUntil && this.state === "NORMAL" && !this.calib && this.rocks.length === 0) {
      this.autoIn -= dt;
      if (this.autoIn <= 0) {
        this.run(pick(["detener", "izquierda", "derecha", "objeto", "objeto", "angulo", "senal"]));
        this.autoIn = rnd(16, 30);
      }
    }
  };

  Sim.prototype.setState = function (next, now) {
    var prev = this.state;
    var seg = this.segments[this.segments.length - 1];
    if (seg && seg.t1 === null) seg.t1 = now;
    this.segments.push({ state: next, t0: now, t1: null });
    // cerrar evento abierto
    if (this.openEvent) {
      this.openEvent.dur = (now - this.openEvent.t) / 1000;
      var e = this.openEvent; this.openEvent = null; this.emit("eventEnd", e);
    }
    this.state = next; this.since = now;
    this.cand = { state: next, n: 0 };
    if (next !== "NORMAL" && next !== "CALIBRANDO") {
      var m = this.m;
      var ev = this.makeEvent(next, now, {
        vel: m.vel, lat: m.lat, ang: m.ang, dist: m.dist, phase: this.phase,
        rocks: this.rocks.map(function (r) { return { x: r.x, y: r.y, w: r.w, h: r.h, ht: r.ht, seed: r.seed, hit: r.hit }; })
      });
      this.events.unshift(ev);
      this.openEvent = ev;
      this.emit("event", ev);
    }
    this.emit("state", prev, next);
  };

  /* ---------- avance con paso fijo + interpolación visual ---------- */
  Sim.prototype.update = function (dt) {
    this.acc += Math.min(dt, 1);
    while (this.acc >= STEP) { this.acc -= STEP; this.step(); }
  };

  Sim.prototype.visual = function () {
    var ex = this.a.vel * 10 * this.acc, self = this;
    return {
      phase: (this.phase + ex) % 434,
      vel: this.m.vel, lat: this.a.lat, ang: this.a.ang, dist: this.m.dist,
      rocks: this.rocks.map(function (r) { return { x: r.x + ex, y: r.y, w: r.w, h: r.h, ht: r.ht, seed: r.seed, hit: r.hit }; }),
      state: this.state, signal: this.signal,
      calib: this.calib ? 1 - this.calib.left / 60 : null
    };
  };

  Sim.prototype.calibProgress = function () { return this.calib ? 1 - this.calib.left / 60 : null; };
  Sim.prototype.confirmInfo = function () {
    var c = this.cand;
    if (c.n > 0 && c.state !== this.state && c.state !== "CALIBRANDO") {
      var need = NEED[c.state] || 5;
      return { state: c.state, frac: Math.min(1, c.n / need), text: (c.n * 0.1).toFixed(1).replace(".", ",") + " s de " + (need * 0.1).toFixed(1).replace(".", ",") + " s" };
    }
    return null;
  };

  /* ---------- estadísticas de la última hora ---------- */
  Sim.prototype.stats = function (windowMs) {
    windowMs = windowMs || 3600000;
    var now = Date.now(), from = now - windowMs;
    var by = {}, ORD = ORDER;
    ORD.forEach(function (k) { by[k] = 0; });
    var detenciones = 0, objetos = 0, desal = 0;
    this.segments.forEach(function (s) {
      var a = Math.max(s.t0, from), b = Math.min(s.t1 === null ? now : s.t1, now);
      if (b > a) by[s.state] += b - a;
      if (s.t0 >= from) {
        if (s.state === "DETENIDA") detenciones++;
        if (s.state === "OBJETO_DETECTADO") objetos++;
        if (s.state === "DESALINEADA") desal++;
      }
    });
    var total = 0;
    ORD.forEach(function (k) { total += by[k]; });
    var avance = by.NORMAL + by.DESALINEADA + by.OBJETO_DETECTADO;
    var util = total - by.CALIBRANDO;
    return {
      by: by, total: total,
      disponibilidad: util > 0 ? avance / util : 1,
      detenciones: detenciones, objetos: objetos, desal: desal,
      detenidoMs: by.DETENIDA,
      mtbfMs: detenciones > 0 ? avance / detenciones : null
    };
  };

  g.RockU = g.RockU || {};
  g.RockU.Sim = Sim;
  g.RockU.STATES = STATES;
  g.RockU.ORDER = ORDER;
  g.RockU.LIM = LIM;
  g.RockU.NEED = NEED;
})(window);
