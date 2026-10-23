/* RockU: fuente de datos remota. Habla con servidor.py (ver docs/api.md) y expone la misma
   interfaz que el simulador del navegador (sim.js), así los dos frontends no cambian.
   R.pickSource() prueba el servidor y, si no responde, cae al simulador local. */
(function (g) {
  "use strict";
  var R = g.RockU, LIM = R.LIM, STEP_MS = 100;

  function Remote(base, snap) {
    this.remote = true;
    this.base = base;
    this.listeners = { event: [], state: [], eventEnd: [] };
    this.rocks = []; this.phase = 0; this.acc = 0;
    this.img = null; this.imgBusy = false; this.imgT = 0;
    this.tg = { vel: 0, lat: 0, ang: 0 };
    this.offline = false;
    this.applySnapshot(snap);
    this.connect();
  }
  Remote.prototype.on = function (n, fn) { this.listeners[n].push(fn); };
  Remote.prototype.emit = function (n, a, b) { var l = this.listeners[n]; for (var i = 0; i < l.length; i++) l[i](a, b); };

  Remote.prototype.fixEvent = function (e) {
    var sn = e.snap || {};
    var ev = { id: e.id, t: e.t, tipo: e.tipo, dur: e.dur_s === undefined ? e.dur : e.dur_s, detalle: e.detalle || "", valor: e.valor || "", foto: e.foto || null, snap: sn };
    if (sn.phase === undefined) sn.phase = (e.id * 97) % 434;
    if (!sn.rocks) {
      sn.rocks = e.tipo === "OBJETO_DETECTADO" ? [{ x: 170 + (e.id * 37) % 100, y: ((e.id * 13) % 50) - 25, w: 48, h: 40, ht: LIM.base - (sn.dist || 80), seed: e.id, hit: true }] : [];
    }
    return ev;
  };

  Remote.prototype.applyTick = function (d) {
    this.state = d.estado; this.since = d.desde;
    var c = d.cand || {};
    this.cand = { state: c.estado || d.estado, n: c.n || 0, need: c.need || 1 };
    var m = d.medida || {};
    var o = this.m || {};
    this.m = { vel: m.vel == null ? (o.vel || 0) : m.vel, lat: m.lat == null ? (o.lat || 0) : m.lat, ang: m.ang == null ? (o.ang || 0) : m.ang, dist: m.dist == null ? (o.dist || LIM.base) : m.dist };
    this.signal = d.senal; this.fps = d.fps || 0; this.lat = d.latencia_ms || 0;
    this.cpu = d.cpu || 0; this.temp = d.temp_c || 0; this.lastEventT = d.esp_ultimo_ms || 0;
    this.calibP = d.calibrando ? d.calibrando.progreso : null;
    this.muted = !!d.silenciada;
    this.tg = { vel: this.m.vel, lat: this.m.lat, ang: this.m.ang };
  };

  Remote.prototype.applySnapshot = function (s) {
    var self = this;
    this.fuente = s.fuente;
    if (s.limites) { LIM.velMin = s.limites.vel_min; LIM.latMax = s.limites.lat_max; LIM.angMax = s.limites.ang_max; LIM.base = s.limites.dist_base; LIM.objDrop = s.limites.obj_caida; }
    this.applyTick(s);
    this.samples = (s.muestras || []).map(function (x) { return { t: x.t, vel: x.vel, lat: x.lat, ang: x.ang, dist: x.dist, state: x.estado }; });
    this.segments = (s.segmentos || []).map(function (x) { return { state: x.estado, t0: x.t0, t1: x.t1 }; });
    this.events = (s.eventos || []).map(function (e) { return self.fixEvent(e); });
    this.openEvent = null;
    this.events.forEach(function (e) { if (e.dur === null || e.dur === undefined) self.openEvent = e; });
    this.phase = 0;
  };

  Remote.prototype.connect = function () {
    var self = this;
    var es = new EventSource(this.base + "/api/stream");
    this.es = es;
    function J(e) { try { return JSON.parse(e.data); } catch (x) { return null; } }
    es.addEventListener("snapshot", function (e) { var d = J(e); if (d) { var had = self.offline; self.offline = false; self.applySnapshot(d); } });
    es.addEventListener("tick", function (e) { var d = J(e); if (d) { self.offline = false; self.applyTick(d); } });
    es.addEventListener("muestra", function (e) {
      var d = J(e); if (!d) return;
      self.samples.push({ t: d.t, vel: d.vel, lat: d.lat, ang: d.ang, dist: d.dist, state: d.estado });
      if (self.samples.length > 900) self.samples.shift();
    });
    es.addEventListener("estado", function (e) {
      var d = J(e); if (!d) return;
      var last = self.segments[self.segments.length - 1];
      if (last && last.t1 === null) last.t1 = d.t;
      self.segments.push({ state: d.next, t0: d.t, t1: null });
      self.emit("state", d.prev, d.next);
    });
    es.addEventListener("evento", function (e) {
      var d = J(e); if (!d) return;
      var ev = self.fixEvent(d);
      self.events.unshift(ev); self.openEvent = ev;
      if (ev.tipo === "OBJETO_DETECTADO") self.rocks.push({ x: LIM.sensorX, y: ev.snap.rocks[0].y, w: 48, h: 40, ht: 40, seed: ev.id, hit: true });
      self.emit("event", ev);
    });
    es.addEventListener("evento_fin", function (e) {
      var d = J(e); if (!d) return;
      for (var i = 0; i < self.events.length; i++) if (self.events[i].id === d.id) { self.events[i].dur = d.dur_s; if (self.openEvent === self.events[i]) self.openEvent = null; self.emit("eventEnd", self.events[i]); break; }
    });
    es.onerror = function () { self.offline = true; self.signal = false; };
  };

  Remote.prototype.post = function (body) {
    try {
      fetch(this.base + "/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (e) {}
  };
  Remote.prototype.run = function (name) {
    if (name === "calibrar") this.post({ accion: "calibrar" });
    else this.post({ accion: "escenario", nombre: name });
  };
  Remote.prototype.setTargets = function (o) { var b = { accion: "objetivo" }; for (var k in o) b[k] = o[k]; this.post(b); };
  Remote.prototype.setMuted = function (v) { this.post({ accion: "silenciar", valor: !!v }); };
  Object.defineProperty(Remote.prototype, "auto", {
    get: function () { return this._auto !== false; },
    set: function (v) { this._auto = !!v; this.post({ accion: "auto", valor: !!v }); }
  });

  Remote.prototype.calibProgress = function () { return this.calibP === null || this.calibP === undefined ? null : this.calibP; };
  Remote.prototype.confirmInfo = function () {
    var c = this.cand;
    if (c.n > 0 && c.state !== this.state && c.state !== "CALIBRANDO") return { state: c.state, frac: Math.min(1, c.n / c.need), text: c.n + " de " + c.need + " lecturas" };
    return null;
  };

  /* avance visual: la escena sintética sigue la velocidad medida; en la fuente real se pide el frame anotado */
  Remote.prototype.update = function (dt) {
    var adv = (this.m.vel || 0) * 10 * Math.min(dt, 1);
    this.phase = (this.phase + adv) % 434;
    for (var i = this.rocks.length - 1; i >= 0; i--) { this.rocks[i].x += adv; if (this.rocks[i].x > LIM.fov + 80) this.rocks.splice(i, 1); }
    if (this.fuente === "real") this.pollFrame();
  };
  Remote.prototype.pollFrame = function () {
    var now = performance.now(), self = this;
    if (this.imgBusy || now - this.imgT < 180) return;
    this.imgBusy = true; this.imgT = now;
    var im = new Image();
    im.onload = function () { self.img = im; self.imgBusy = false; };
    im.onerror = function () { self.imgBusy = false; };
    im.src = this.base + "/api/frame.jpg?t=" + Date.now();
  };
  Remote.prototype.visual = function () {
    return {
      phase: this.phase, vel: this.m.vel, lat: this.m.lat, ang: this.m.ang, dist: this.m.dist,
      rocks: this.rocks, state: this.state, signal: this.signal, calib: this.calibProgress(), image: this.fuente === "real" ? this.img : null
    };
  };
  Remote.prototype.stats = R.Sim.prototype.stats;

  /* ---------- elección de la fuente ---------- */
  R.pickSource = function (params, cb) {
    function local() { var s = new R.Sim({ auto: params.get("auto") !== "0" }); s.remote = false; cb(s); }
    var base = (params.get("api") || "").replace(/\/$/, "");
    if (params.get("fuente") === "local" || (location.protocol === "file:" && !base)) return local();
    var done = false, ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 1500);
    fetch(base + "/api/snapshot", ctl ? { signal: ctl.signal } : undefined)
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (snap) { clearTimeout(timer); if (done) return; done = true; cb(new Remote(base, snap)); })
      .catch(function () { clearTimeout(timer); if (done) return; done = true; local(); });
  };
  R.Remote = Remote;
})(window);
