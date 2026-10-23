/* RockU: pantalla de 3.5" (480x320). Misma fuente de datos que el panel web.
   Atajos para la demo con teclado: 1 normal, 2 detener, 3 desalinear izq., 4 desalinear der., 5 piedra, 6 cortar señal, 7 calibrar. */
(function () {
  "use strict";
  var R = window.RockU, ST = R.STATES, LIM = R.LIM;
  function $(id) { return document.getElementById(id); }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function f(v, d) { return v.toFixed(d).replace(".", ","); }
  function sf(v, d) { var r = Math.round(Math.abs(v) * Math.pow(10, d)) / Math.pow(10, d); return (v < 0 && r !== 0 ? "-" : "+") + f(r, d); }
  function mmss(sec) { sec = Math.max(0, Math.round(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(s); }
  function hm(t) { var d = new Date(t); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function setText(el, v) { if (el.textContent !== v) el.textContent = v; }

  R.pickSource(new URLSearchParams(location.search), function (sim) {
  R.sim = sim;
  var muted = false;

  /* escala del escenario de 480x320 a la ventana (en la Pi vale 1) */
  var stage = $("stage");
  function fit() {
    var k = Math.min(window.innerWidth / 480, window.innerHeight / 320);
    stage.style.transform = "translate(" + (-240 * k) + "px," + (-160 * k) + "px) scale(" + k + ")";
    stage.style.boxShadow = k > 1.02 ? "0 0 0 1px #223348, 0 20px 60px rgba(0,0,0,.6)" : "none";
  }
  window.addEventListener("resize", fit); fit();

  /* línea de velocidad del último minuto */
  var cv = $("spark"), cx = cv.getContext("2d"), W = 460, H = 52;
  (function () { var dpr = window.devicePixelRatio || 1; cv.width = W * dpr; cv.height = H * dpr; cx.setTransform(dpr, 0, 0, dpr, 0, 0); })();
  var BAND = { DETENIDA: "255,98,86", DESALINEADA: "245,176,49", OBJETO_DETECTADO: "76,154,247", SIN_SENAL: "141,155,176" };
  function drawSpark() {
    var now = Date.now(), t0 = now - 60000, S = sim.samples, i0 = S.length;
    while (i0 > 0 && S[i0 - 1].t >= t0 - 1500) i0--;
    var top = 20, bot = H - 6, h = bot - top;
    function X(t) { return (t - t0) / 60000 * (W - 8) + 0; }
    function Y(v) { return bot - Math.max(0, Math.min(15, v)) / 15 * h; }
    cx.clearRect(0, 0, W, H);
    sim.segments.forEach(function (sg) {
      if (!BAND[sg.state]) return;
      var a = Math.max(sg.t0, t0), b = Math.min(sg.t1 === null ? now : sg.t1, now);
      if (b > a) { cx.fillStyle = "rgba(" + BAND[sg.state] + ",.18)"; cx.fillRect(X(a), 0, Math.max(2, X(b) - X(a)), H); }
    });
    cx.setLineDash([4, 4]); cx.strokeStyle = "rgba(255,98,86,.7)"; cx.lineWidth = 1;
    cx.beginPath(); cx.moveTo(0, Y(LIM.velMin) + .5); cx.lineTo(W, Y(LIM.velMin) + .5); cx.stroke(); cx.setLineDash([]);
    if (i0 >= S.length) return;
    cx.beginPath();
    var lx = 0, ly = 0;
    for (var i = i0; i < S.length; i++) { var x = X(S[i].t), y = Y(S[i].vel); if (i === i0) cx.moveTo(x, y); else cx.lineTo(x, y); lx = x; ly = y; }
    cx.lineJoin = "round"; cx.strokeStyle = "#4C9AF7"; cx.lineWidth = 2.2; cx.stroke();
    cx.lineTo(lx, bot); cx.lineTo(X(S[i0].t), bot); cx.closePath(); cx.fillStyle = "rgba(76,154,247,.14)"; cx.fill();
    cx.fillStyle = "#0E1A25"; cx.beginPath(); cx.arc(lx, ly, 4.5, 0, 7); cx.fill();
    cx.fillStyle = "#4C9AF7"; cx.beginPath(); cx.arc(lx, ly, 3, 0, 7); cx.fill();
  }

  /* botones */
  $("bCal").addEventListener("click", function () { sim.run("calibrar"); });
  $("bMute").addEventListener("click", function () { muted = !muted; if (sim.setMuted) sim.setMuted(muted); ui(); });
  var noteT = null;
  function note(msg) {
    var n = $("note"); n.textContent = msg; n.hidden = false;
    clearTimeout(noteT); noteT = setTimeout(function () { n.hidden = true; }, 2600);
  }
  $("bUsb").addEventListener("click", function () { note("Exportado al pendrive: " + sim.events.length + " eventos y sus fotos"); });
  var keys = { "1": "normal", "2": "detener", "3": "izquierda", "4": "derecha", "5": "objeto", "6": "senal", "7": "calibrar" };
  document.addEventListener("keydown", function (e) { if (keys[e.key]) sim.run(keys[e.key]); });

  sim.on("state", function (p, n) { if (n === "NORMAL") muted = false; });

  var lastDur = 0;
  function ui() {
    var now = Date.now(), s = sim.state, def = ST[s], m = sim.m, sig = sim.signal;
    setText($("clock"), hm(now));
    $("status").setAttribute("data-tone", def.tone);
    setText($("stName"), def.label); $("stName").classList.toggle("long", def.label.length > 12);
    var sub;
    if (s === "NORMAL") sub = "Avanza a " + f(m.vel, 1) + " cm/s";
    else if (s === "DETENIDA") sub = "Sin movimiento en la imagen";
    else if (s === "DESALINEADA") sub = "Desvío " + sf(m.lat, 1) + " mm, " + sf(m.ang, 1) + "°";
    else if (s === "OBJETO_DETECTADO") sub = "Sensor a " + Math.round(m.dist) + " mm";
    else if (s === "SIN_SENAL") sub = "No llegan imágenes del teléfono";
    else sub = "Midiendo la referencia";
    setText($("stSub"), sub);
    setText($("stSince"), mmss((now - sim.since) / 1000));

    // cinta de avance: sigue la velocidad y se detiene con la correa
    var moving = sig && m.vel >= LIM.velMin;
    var belt = $("belt");
    belt.style.setProperty("--play", moving ? "running" : "paused");
    if (moving) { var dur = Math.max(0.25, Math.min(3, 30 / (m.vel * 18))); if (Math.abs(dur - lastDur) > 0.05) { belt.style.setProperty("--dur", dur.toFixed(2) + "s"); lastDur = dur; } }
    var cal = $("calib"), cpv = sim.calibProgress(); cal.hidden = cpv === null;
    if (cpv !== null) $("calibFill").style.width = (cpv * 100) + "%";

    setText($("vVel"), f(m.vel, 1)); setText($("vLat"), sf(m.lat, 1)); setText($("vAng"), sf(m.ang, 1));
    $("nVel").className = "num" + (sig && m.vel < LIM.velMin ? " stop" : "");
    $("nLat").className = "num" + (sig && Math.abs(m.lat) > LIM.latMax ? " warn" : "");
    $("nAng").className = "num" + (sig && Math.abs(m.ang) > LIM.angMax ? " warn" : "");

    $("lkPhone").setAttribute("data-ok", sig ? "1" : "0");
    $("lkEsp").setAttribute("data-ok", sig ? "1" : "0");

    var ev = sim.events[0];
    setText($("lastEv"), ev ? "Último: " + ST[ev.tipo].label.toLowerCase() + ", " + hm(ev.t) : "Sin eventos");

    var active = s === "DETENIDA" || s === "DESALINEADA" || s === "SIN_SENAL" || s === "OBJETO_DETECTADO";
    var b = $("bMute"); b.className = muted ? "on" : (active ? "hot" : "");
    b.querySelector("use").setAttribute("href", muted ? "#i-bell-off" : "#i-bell");
    setText($("bMuteTxt"), muted ? "Silenciada" : "Silenciar");
  }

  var last = performance.now(), n = 0;
  setInterval(function () {
    var t = performance.now(); sim.update((t - last) / 1000); last = t;
    if (++n % 2 === 0) ui();
    if (n % 10 === 0) drawSpark();
  }, 100);
  ui(); drawSpark();
});
})();
