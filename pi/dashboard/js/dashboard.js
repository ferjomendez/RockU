/* RockU: lógica del panel web. Usa el simulador (sim.js) y dibuja la escena (scene.js). */
(function () {
  "use strict";
  var R = window.RockU, ST = R.STATES, ORDER = R.ORDER, LIM = R.LIM, NEED = R.NEED;
  var root = document.documentElement;
  function $(id) { return document.getElementById(id); }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function f(v, d) { return v.toFixed(d).replace(".", ","); }
  function sf(v, d) { var r = Math.round(Math.abs(v) * Math.pow(10, d)) / Math.pow(10, d); return (v < 0 && r !== 0 ? "-" : "+") + f(r, d); }
  function mmss(sec) { sec = Math.max(0, Math.round(sec)); var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return (h ? h + ":" + pad(m) : pad(m)) + ":" + pad(s); }
  function hms(t) { var d = new Date(t); return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()); }
  function hm(t) { var d = new Date(t); return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function setText(el, v) { if (el.textContent !== v) el.textContent = v; }
  function ago(t) {
    var s = Math.round((Date.now() - t) / 1000);
    if (s < 45) return "hace instantes";
    var m = Math.round(s / 60);
    if (m < 60) return "hace " + m + " min";
    return "hace " + Math.floor(m / 60) + " h " + pad(m % 60) + " min";
  }

  R.pickSource(new URLSearchParams(location.search), function (sim) {

  /* ---------- tema ---------- */
  var colors = {};
  function readColors() {
    var cs = getComputedStyle(root);
    ["--fg", "--fg-2", "--fg-3", "--chart-grid", "--chart-line", "--chart-fill", "--stop", "--warn", "--obj", "--off", "--accent", "--panel", "--ok", "--idle"].forEach(function (k) { colors[k] = cs.getPropertyValue(k).trim(); });
  }
  function isDark() {
    var a = root.getAttribute("data-theme");
    return a ? a === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  function syncThemeIcon() { $("btnTheme").querySelector("use").setAttribute("href", isDark() ? "#i-sun" : "#i-moon"); }
  try { var saved = localStorage.getItem("rockuTheme"); if (saved) root.setAttribute("data-theme", saved); } catch (e) {}
  $("btnTheme").addEventListener("click", function () {
    var next = isDark() ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("rockuTheme", next); } catch (e) {}
    readColors(); syncThemeIcon(); drawChart();
  });
  try { window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { readColors(); syncThemeIcon(); drawChart(); }); } catch (e) {}
  readColors(); syncThemeIcon();
  try { new MutationObserver(function () { readColors(); syncThemeIcon(); drawChart(); }).observe(root, { attributes: true, attributeFilter: ["data-theme"] }); } catch (e) {}

  /* ---------- simulador ---------- */
  R.sim = sim;
  $("swAuto").checked = sim.auto;
  if (sim.remote) {
    var live = sim.fuente === "real";
    document.querySelector(".mode").lastChild.textContent = live ? "En vivo" : "Simulador";
    document.querySelector(".mode").title = live ? "Datos de la correa real" : "Datos generados por el simulador de la Pi";
    if (live) { $("btnSim").hidden = true; document.querySelector(".foot").textContent = "RockU, Taller de Innovación UAI."; }
  }

  /* ---------- escena principal ---------- */
  var cam = document.querySelector(".cam"), scene = $("scene"), sctx = scene.getContext("2d"), sW = 0, sH = 0;
  function sizeScene() {
    var r = cam.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    sW = Math.max(200, r.width); sH = Math.max(160, r.height);
    scene.width = Math.round(sW * dpr); scene.height = Math.round(sH * dpr);
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  new ResizeObserver(sizeScene).observe(cam); sizeScene();

  var last = performance.now();
  function frame(now) {
    var dt = (now - last) / 1000; last = now;
    sim.update(dt);
    var v = sim.visual();
    if (v.image) { R.drawCover(sctx, v.image, sW, sH); R.drawScene(sctx, sW, sH, v, { ui: true, overlayOnly: true, t: now }); }
    else R.drawScene(sctx, sW, sH, v, { ui: true, t: now });
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ---------- máquina de estados (lista) ---------- */
  var machine = $("machine"), mEls = {};
  ORDER.forEach(function (k) {
    var li = document.createElement("li");
    li.setAttribute("data-tone", ST[k].tone);
    li.innerHTML = "<i></i><span>" + ST[k].label + "</span><small></small>";
    machine.appendChild(li); mEls[k] = li;
  });

  /* ---------- toasts ---------- */
  var TCOL = { ok: "#2FC47A", stop: "#FF6256", warn: "#F5B031", obj: "#4C9AF7", off: "#93A3B8", idle: "#93A3B8" };
  function toast(msg, tone) {
    var box = $("toasts");
    while (box.children.length >= 3) box.removeChild(box.firstChild);
    var t = document.createElement("div"); t.className = "toast";
    t.style.setProperty("--tc", TCOL[tone || "obj"]);
    t.innerHTML = "<i></i><span></span>"; t.lastChild.textContent = msg;
    box.appendChild(t);
    setTimeout(function () { t.classList.add("out"); setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 320); }, 4200);
  }

  sim.on("event", function (ev) {
    var m = ev.snap, msg;
    if (ev.tipo === "DETENIDA") msg = "La correa se detuvo";
    else if (ev.tipo === "DESALINEADA") msg = "Correa desalineada, desvío " + sf(m.lat, 1) + " mm";
    else if (ev.tipo === "OBJETO_DETECTADO") msg = "Objeto detectado a " + Math.round(m.dist) + " mm del sensor";
    else msg = "Se perdió la señal del teléfono";
    toast(msg, ST[ev.tipo].tone);
    renderEvents(ev.id);
  });
  sim.on("eventEnd", function () { renderEvents(); });
  sim.on("state", function (prev, next) {
    if (next === "NORMAL" && prev === "CALIBRANDO") toast("Calibración lista", "ok");
    else if (next === "NORMAL") toast("Volvió a la normalidad", "ok");
    else if (next === "CALIBRANDO") toast("Calibrando, la correa debe estar en condición normal", "idle");
    if (next === "NORMAL") { muted = false; }
  });

  /* ---------- indicadores ---------- */
  var muted = false;
  function kpi(id, tone, chip, text) {
    $(id).setAttribute("data-tone", tone);
    setText($(id + "Chip"), text);
  }
  function updateUI() {
    var now = Date.now(), s = sim.state, def = ST[s], m = sim.m, sig = sim.signal;

    // reloj
    setText($("clock"), hms(now));

    // estado
    $("state").setAttribute("data-tone", def.tone);
    $("camState").setAttribute("data-tone", def.tone);
    setText($("stName"), def.label); setText($("camStateTxt"), def.label);
    var txt = def.text;
    if (s === "NORMAL") txt = "Avanza a " + f(m.vel, 1) + " cm/s con los bordes dentro de los límites.";
    else if (s === "DESALINEADA") txt = "Desvío " + sf(m.lat, 1) + " mm y ángulo " + sf(m.ang, 1) + "°. El límite es " + LIM.latMax + " mm y " + LIM.angMax + "°.";
    else if (s === "DETENIDA") txt = "Sin desplazamiento entre frames. Velocidad medida: " + f(m.vel, 1) + " cm/s.";
    else if (s === "OBJETO_DETECTADO") txt = "El sensor midió " + Math.round(m.dist) + " mm. Con la correa vacía mide " + LIM.base + " mm.";
    setText($("stText"), txt);
    setText($("stSince"), mmss((now - sim.since) / 1000));

    // confirmación
    var conf = $("confirm"), cp = sim.calibProgress(), ci = sim.confirmInfo();
    if (s === "CALIBRANDO" && cp !== null) {
      conf.setAttribute("data-tone", "idle");
      setText($("confirmTxt"), "Calibrando referencia"); setText($("confirmN"), Math.round(cp * 100) + "%");
      $("confirmFill").style.width = (cp * 100) + "%";
    } else if (ci) {
      conf.setAttribute("data-tone", ST[ci.state].tone);
      setText($("confirmTxt"), "Confirmando " + ST[ci.state].label.toLowerCase());
      setText($("confirmN"), ci.text);
      $("confirmFill").style.width = (ci.frac * 100) + "%";
    } else {
      conf.setAttribute("data-tone", def.tone);
      setText($("confirmTxt"), "Estado confirmado"); setText($("confirmN"), "");
      $("confirmFill").style.width = "100%";
    }

    // lista de estados
    ORDER.forEach(function (k) { mEls[k].classList.toggle("on", k === s); });

    // velocidad
    var vT = !sig ? "off" : m.vel < LIM.velMin ? "stop" : "ok";
    $("kVel").setAttribute("data-tone", vT);
    setText($("kVelChip"), !sig ? "Sin datos" : vT === "stop" ? "Detenida" : "En rango");
    setText($("vVel"), f(m.vel, 1)); $("mVel").style.left = clamp(m.vel / 15 * 100, 0, 100) + "%";
    // desvío
    var lT = !sig ? "off" : Math.abs(m.lat) > LIM.latMax ? "warn" : "ok";
    $("kLat").setAttribute("data-tone", lT);
    setText($("kLatChip"), !sig ? "Sin datos" : lT === "warn" ? "Fuera del límite" : "En rango");
    setText($("vLat"), sf(m.lat, 1)); $("mLat").style.left = clamp((m.lat + 16) / 32 * 100, 0, 100) + "%";
    // ángulo
    var aT = !sig ? "off" : Math.abs(m.ang) > LIM.angMax ? "warn" : "ok";
    $("kAng").setAttribute("data-tone", aT);
    setText($("kAngChip"), !sig ? "Sin datos" : aT === "warn" ? "Fuera del límite" : "En rango");
    setText($("vAng"), sf(m.ang, 1));
    $("needle").style.transform = "rotate(" + clamp(m.ang * 18, -90, 90) + "deg)";
    // distancia
    var dT = !sig ? "off" : m.dist < LIM.base - LIM.objDrop ? "obj" : "ok";
    $("kDist").setAttribute("data-tone", dT);
    setText($("kDistChip"), !sig ? "Sin datos" : dT === "obj" ? "Objeto bajo el sensor" : "Correa vacía");
    setText($("vDist"), Math.round(m.dist)); $("mDist").style.left = clamp((m.dist - 40) / 100 * 100, 0, 100) + "%";

    // cámara
    setText($("camFps"), sig ? f(sim.fps, 1) + " fps" : "sin señal");
    setText($("camLat"), sig ? Math.round(sim.lat) + " ms de latencia" : "");

    // alarma
    var active = s === "DETENIDA" || s === "DESALINEADA" || s === "SIN_SENAL" || s === "OBJETO_DETECTADO";
    var al = $("alarm");
    al.hidden = !active;
    al.classList.toggle("muted", muted);
    setText($("alarmText"), muted ? "Alarma silenciada" : "Alarma activa");
    var mb = $("btnMute"); mb.setAttribute("aria-pressed", muted ? "true" : "false");
    mb.disabled = false;

    // conexiones
    var hp = $("hPhone"); hp.setAttribute("data-tone", sig ? "ok" : "stop");
    setText($("hPhoneChip"), sig ? "En línea" : "Sin conexión");
    setText($("hPhoneTxt"), sig ? "192.168.1.84, " + f(sim.fps, 1) + " fps, 1080x1440" : "192.168.1.84, no responde");
    var mins = Math.floor((now - sim.lastEventT) / 60000);
    setText($("hEspTxt"), "192.168.1.86, último evento " + (mins < 1 ? "hace instantes" : "hace " + mins + " min"));
    setText($("hCpu"), "CPU " + Math.round(sim.cpu) + "%"); setText($("hTemp"), Math.round(sim.temp) + " °C");
    $("hPi").setAttribute("data-tone", sim.temp > 60 ? "warn" : "ok");
    setText($("hPiChip"), sim.temp > 60 ? "Caliente" : "En línea");

    // sliders siguen al objetivo
    syncSliders();
  }
  setInterval(updateUI, 200);
  updateUI();

  /* ---------- gráfico ---------- */
  var chart = $("chart"), cctx = chart.getContext("2d"), cW = 0, cH = 0, hoverT = null;
  var LANES = [
    { key: "vel", title: "Velocidad", unit: "cm/s", min: 0, max: 15, ticks: [0, 5, 10, 15], limits: [LIM.velMin], d: 1 },
    { key: "lat", title: "Desvío lateral", unit: "mm", min: -16, max: 16, ticks: [-16, 0, 16], limits: [LIM.latMax, -LIM.latMax], d: 1, signed: true },
    { key: "dist", title: "Distancia del sensor", unit: "mm", min: 40, max: 140, ticks: [40, 90, 140], limits: [LIM.base - LIM.objDrop], d: 0, base: LIM.base }
  ];
  var WIN = 300000, PR = 40, PT = 4, AX = 24, GAP = 14;
  function sizeChart() {
    var r = chart.parentNode.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    var cs = getComputedStyle(chart.parentNode);
    cW = Math.max(240, r.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
    cH = Math.max(300, r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom));
    chart.width = Math.round(cW * dpr); chart.height = Math.round(cH * dpr);
    chart.style.width = cW + "px"; chart.style.height = cH + "px";
    cctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawChart();
  }
  new ResizeObserver(sizeChart).observe(chart.parentNode);

  function toneColor(t) { return { stop: colors["--stop"], warn: colors["--warn"], obj: colors["--obj"], off: colors["--off"], idle: colors["--idle"], ok: colors["--ok"] }[t]; }
  function hexA(col, a) {
    var cvs = hexA.c || (hexA.c = document.createElement("canvas").getContext("2d"));
    cvs.fillStyle = "#000"; cvs.fillStyle = col; var v = cvs.fillStyle;
    if (v.charAt(0) === "#") { var n = parseInt(v.slice(1), 16); return "rgba(" + (n >> 16) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")"; }
    return v;
  }

  function drawChart() {
    if (!cW) return;
    var ctx = cctx, now = Date.now(), t0 = now - WIN, pw = cW - PR;
    var laneH = (cH - AX - PT - GAP * (LANES.length - 1)) / LANES.length;
    ctx.clearRect(0, 0, cW, cH);
    function X(t) { return (t - t0) / WIN * pw; }

    // bandas de estado fuera de lo normal
    sim.segments.forEach(function (sg) {
      if (sg.state === "NORMAL" || sg.state === "CALIBRANDO") return;
      var a = Math.max(sg.t0, t0), b = Math.min(sg.t1 === null ? now : sg.t1, now);
      if (b <= a) return;
      ctx.fillStyle = hexA(toneColor(ST[sg.state].tone), 0.13);
      ctx.fillRect(X(a), PT, Math.max(2, X(b) - X(a)), cH - AX - PT);
    });

    var samples = sim.samples, i0 = samples.length;
    while (i0 > 0 && samples[i0 - 1].t >= t0 - 2000) i0--;

    LANES.forEach(function (L, li) {
      var top = PT + li * (laneH + GAP), bot = top + laneH, inner = laneH - 26, y0 = top + 26;
      function Y(v) { return y0 + inner - (clamp(v, L.min, L.max) - L.min) / (L.max - L.min) * inner; }
      // rejilla y eje
      ctx.font = "500 11px Archivo, system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      L.ticks.forEach(function (tv) {
        var y = Y(tv);
        ctx.strokeStyle = colors["--chart-grid"]; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(0, y + .5); ctx.lineTo(pw, y + .5); ctx.stroke();
        ctx.fillStyle = colors["--fg-3"]; ctx.fillText(String(tv), pw + 8, y);
      });
      // límites
      ctx.save(); ctx.setLineDash([5, 4]); ctx.lineWidth = 1.4;
      L.limits.forEach(function (lv) { ctx.strokeStyle = colors["--stop"]; ctx.beginPath(); ctx.moveTo(0, Y(lv) + .5); ctx.lineTo(pw, Y(lv) + .5); ctx.stroke(); });
      if (L.base) { ctx.strokeStyle = colors["--accent"]; ctx.globalAlpha = .7; ctx.beginPath(); ctx.moveTo(0, Y(L.base) + .5); ctx.lineTo(pw, Y(L.base) + .5); ctx.stroke(); }
      ctx.restore();

      // título y valor actual
      var cur = samples.length ? samples[samples.length - 1][L.key] : 0;
      ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
      ctx.font = "650 12.5px Archivo, system-ui, sans-serif"; ctx.fillStyle = colors["--fg-2"]; ctx.fillText(L.title, 0, top + 14);
      var tw = ctx.measureText(L.title).width;
      ctx.font = "750 14px Archivo, system-ui, sans-serif"; ctx.fillStyle = colors["--fg"];
      var vs = (L.signed ? sf(cur, L.d) : f(cur, L.d)) + " " + L.unit;
      ctx.fillText(vs, tw + 12, top + 14);

      // línea y área
      if (i0 < samples.length) {
        ctx.beginPath();
        var first = true, lx = 0, ly = 0;
        for (var i = i0; i < samples.length; i++) {
          var x = X(samples[i].t), y = Y(samples[i][L.key]);
          if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
          lx = x; ly = y;
        }
        ctx.lineJoin = "round"; ctx.strokeStyle = colors["--chart-line"]; ctx.lineWidth = 2; ctx.stroke();
        ctx.lineTo(lx, y0 + inner); ctx.lineTo(X(samples[i0].t), y0 + inner); ctx.closePath();
        ctx.fillStyle = hexA(colors["--chart-line"], 0.07); ctx.fill();
        // punto final
        ctx.fillStyle = colors["--panel"]; ctx.beginPath(); ctx.arc(lx, ly, 5, 0, 7); ctx.fill();
        ctx.fillStyle = colors["--chart-line"]; ctx.beginPath(); ctx.arc(lx, ly, 3.2, 0, 7); ctx.fill();
      }
    });

    // eje de tiempo
    ctx.font = "500 11px Archivo, system-ui, sans-serif"; ctx.fillStyle = colors["--fg-3"]; ctx.textBaseline = "alphabetic";
    for (var k = 0; k <= 5; k++) {
      var tt = t0 + k * 60000, xx = X(tt);
      ctx.textAlign = k === 0 ? "left" : k === 5 ? "right" : "center";
      ctx.fillText(k === 5 ? "ahora" : hm(tt), xx, cH - 6);
    }

    // cursor
    if (hoverT !== null && samples.length) {
      var best = null, bd = 1e12;
      for (var j = samples.length - 1; j >= i0; j--) { var dd = Math.abs(samples[j].t - hoverT); if (dd < bd) { bd = dd; best = samples[j]; } }
      if (best) {
        var hx = X(best.t);
        ctx.strokeStyle = colors["--fg-3"]; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
        ctx.beginPath(); ctx.moveTo(hx + .5, PT); ctx.lineTo(hx + .5, cH - AX); ctx.stroke(); ctx.setLineDash([]);
        LANES.forEach(function (L, li) {
          var top = PT + li * (laneH + GAP), inner = laneH - 26, y0 = top + 26;
          var y = y0 + inner - (clamp(best[L.key], L.min, L.max) - L.min) / (L.max - L.min) * inner;
          ctx.fillStyle = colors["--panel"]; ctx.beginPath(); ctx.arc(hx, y, 5, 0, 7); ctx.fill();
          ctx.fillStyle = colors["--fg"]; ctx.beginPath(); ctx.arc(hx, y, 3.2, 0, 7); ctx.fill();
        });
        showTip(best, hx);
      }
    } else $("tip").hidden = true;
  }

  function showTip(s, hx) {
    var tip = $("tip"); tip.hidden = false;
    tip.innerHTML = "<div><b>" + hms(s.t) + "</b><small>" + ST[s.state].label + "</small></div>" +
      "<div><span>Velocidad</span><b>" + f(s.vel, 1) + " cm/s</b></div>" +
      "<div><span>Desvío</span><b>" + sf(s.lat, 1) + " mm</b></div>" +
      "<div><span>Distancia</span><b>" + Math.round(s.dist) + " mm</b></div>";
    var left = hx + 14 + 14; if (left + 170 > cW) left = hx - 14 - 170 + 14;
    tip.style.left = Math.max(6, left) + "px"; tip.style.top = "30px";
  }
  chart.addEventListener("pointermove", function (e) {
    var r = chart.getBoundingClientRect(), x = e.clientX - r.left;
    if (x > cW - PR) { hoverT = null; } else hoverT = Date.now() - WIN + x / (cW - PR) * WIN;
    drawChart();
  });
  chart.addEventListener("pointerleave", function () { hoverT = null; drawChart(); });
  setInterval(drawChart, 1000);

  /* ---------- disponibilidad, línea de tiempo ---------- */
  function updateStats() {
    var S = sim.stats(3600000), now = Date.now(), from = now - 3600000;
    setText($("avPct"), f(S.disponibilidad * 100, 1));
    setText($("avDet"), String(S.detenciones));
    setText($("avStop"), mmss(S.detenidoMs / 1000));
    setText($("avMtbf"), S.mtbfMs === null ? "sin detenciones" : mmss(S.mtbfMs / 1000));
    setText($("avObj"), String(S.objetos));

    // contadores por estado en la lista
    var cnt = { DETENIDA: S.detenciones, DESALINEADA: S.desal, OBJETO_DETECTADO: S.objetos, SIN_SENAL: 0 };
    sim.segments.forEach(function (sg) { if (sg.state === "SIN_SENAL" && sg.t0 >= from) cnt.SIN_SENAL++; });
    Object.keys(cnt).forEach(function (k) { setText(mEls[k].querySelector("small"), cnt[k] + (cnt[k] === 1 ? " vez" : " veces")); });

    // porcentajes
    var sh = "";
    ORDER.forEach(function (k) {
      if (S.by[k] <= 0) return;
      sh += '<span data-tone="' + ST[k].tone + '"><i></i>' + ST[k].label + " <b>" + f(S.by[k] / S.total * 100, 1) + "%</b></span>";
    });
    if ($("shares").innerHTML !== sh) $("shares").innerHTML = sh;

    // barra
    var h = "";
    sim.segments.forEach(function (sg) {
      var a = Math.max(sg.t0, from), b = Math.min(sg.t1 === null ? now : sg.t1, now);
      if (b <= a) return;
      var l = (a - from) / 3600000 * 100, w = (b - a) / 3600000 * 100;
      var dur = Math.round((b - a) / 1000);
      h += '<i class="seg" data-tone="' + ST[sg.state].tone + '" style="left:' + l.toFixed(3) + "%;width:" + w.toFixed(3) + '%" title="' + ST[sg.state].label + ", " + hm(sg.t0) + ", " + mmss(dur) + '"></i>';
    });
    h += '<i class="now"></i>';
    $("tlBar").innerHTML = h;
    var ax = "";
    for (var k = 0; k <= 6; k++) ax += '<span style="left:' + (k / 6 * 100) + '%">' + (k === 6 ? "ahora" : hm(from + k * 600000)) + "</span>";
    if ($("tlAxis").innerHTML !== ax) $("tlAxis").innerHTML = ax;

    // eventos: tiempos relativos y duración en curso
    document.querySelectorAll("#evBody .rel").forEach(function (el) { setText(el, ago(+el.getAttribute("data-t"))); });
    document.querySelectorAll("#evBody .open").forEach(function (el) { setText(el, "En curso, " + mmss((Date.now() - +el.getAttribute("data-t")) / 1000)); });
  }
  setInterval(updateStats, 1000);

  /* ---------- eventos ---------- */
  var filter = "ALL";
  function renderEvents(freshId) {
    var tb = $("evBody"), html = "", n = 0;
    var counts = { ALL: 0, DETENIDA: 0, DESALINEADA: 0, OBJETO_DETECTADO: 0, SIN_SENAL: 0 };
    sim.events.forEach(function (ev) { counts.ALL++; counts[ev.tipo]++; });
    setText($("cAll"), counts.ALL); setText($("cDET"), counts.DETENIDA); setText($("cDES"), counts.DESALINEADA); setText($("cOBJ"), counts.OBJETO_DETECTADO); setText($("cOFF"), counts.SIN_SENAL);

    sim.events.forEach(function (ev) {
      if (filter !== "ALL" && ev.tipo !== filter) return;
      if (n++ >= 40) return;
      var open = ev === sim.openEvent;
      html += '<tr data-id="' + ev.id + '"' + (ev.id === freshId ? ' class="fresh"' : "") + ">" +
        '<td><canvas class="thumb" width="192" height="112" data-id="' + ev.id + '" aria-label="Imagen del evento"></canvas></td>' +
        '<td class="when"><b>' + hms(ev.t) + '</b><small class="rel" data-t="' + ev.t + '">' + ago(ev.t) + "</small></td>" +
        '<td><span class="pill" data-tone="' + ST[ev.tipo].tone + '"><i></i>' + ST[ev.tipo].label + "</span></td>" +
        '<td class="detail">' + ev.detalle + "</td>" +
        '<td class="r mono">' + ev.valor.replace(/\./g, ",") + "</td>" +
        '<td class="r">' + (open ? '<span class="live open" data-t="' + ev.t + '">En curso</span>' : mmss(ev.dur)) + "</td></tr>";
    });
    if (!html) html = '<tr><td colspan="6"><div class="empty">No hay eventos de este tipo en la última hora.</div></td></tr>';
    tb.innerHTML = html;
    var byId = {}; sim.events.forEach(function (e) { byId[e.id] = e; });
    tb.querySelectorAll("canvas.thumb").forEach(function (cv) {
      var ev = byId[cv.getAttribute("data-id")], c = cv.getContext("2d"), sn = ev.snap;
      if (ev.foto) {
        var im = new Image(); im.onload = function () { R.drawCover(c, im, 192, 112); }; im.src = sim.base + ev.foto; return;
      }
      if (ev.tipo === "SIN_SENAL") {
        c.fillStyle = "#0A131C"; c.fillRect(0, 0, 192, 112);
        c.strokeStyle = "rgba(147,163,184,.18)"; c.lineWidth = 5;
        for (var k = -112; k < 192; k += 16) { c.beginPath(); c.moveTo(k, 112); c.lineTo(k + 112, 0); c.stroke(); }
        return;
      }
      R.drawScene(c, 192, 112, { phase: sn.phase, vel: sn.vel, lat: sn.lat, ang: sn.ang, dist: sn.dist, rocks: sn.rocks, state: ev.tipo, signal: true, calib: null }, { ui: false });
    });
    updateStats();
  }
  $("filters").addEventListener("click", function (e) {
    var b = e.target.closest("button.f"); if (!b) return;
    filter = b.getAttribute("data-f");
    document.querySelectorAll("#filters .f").forEach(function (x) { x.classList.toggle("on", x === b); });
    renderEvents();
  });
  renderEvents();

  /* ---------- acciones ---------- */
  $("btnCal").addEventListener("click", function () { sim.run("calibrar"); });
  $("btnMute").addEventListener("click", function () { muted = !muted; if (sim.setMuted) sim.setMuted(muted); updateUI(); toast(muted ? "Alarma silenciada hasta que la correa vuelva a la normalidad" : "Alarma activada", "idle"); });
  $("btnCsv").addEventListener("click", function () {
    var rows = [["fecha_hora", "evento", "duracion_s", "medida", "detalle"]];
    sim.events.slice().reverse().forEach(function (ev) {
      rows.push([new Date(ev.t).toISOString(), ST[ev.tipo].label, ev.dur === null ? "" : ev.dur.toFixed(0), ev.valor, ev.detalle]);
    });
    var csv = "﻿" + rows.map(function (r) { return r.map(function (c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(";"); }).join("\r\n");
    try {
      var url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      var a = document.createElement("a"); a.href = url; a.download = "eventos.csv"; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    } catch (e) {}
    toast("CSV de eventos listo, " + (rows.length - 1) + " filas", "ok");
  });

  /* ---------- panel del simulador ---------- */
  var drawer = $("drawer"), scrim = $("scrim");
  function openDrawer() {
    drawer.hidden = false; scrim.hidden = false;
    requestAnimationFrame(function () { drawer.classList.add("open"); });
    $("btnSim").setAttribute("aria-expanded", "true"); $("drClose").focus();
  }
  function closeDrawer() {
    drawer.classList.remove("open"); $("btnSim").setAttribute("aria-expanded", "false");
    setTimeout(function () { if (!drawer.classList.contains("open")) { drawer.hidden = true; scrim.hidden = true; } }, 260);
    $("btnSim").focus();
  }
  $("btnSim").addEventListener("click", function () { drawer.classList.contains("open") ? closeDrawer() : openDrawer(); });
  $("drClose").addEventListener("click", closeDrawer);
  scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && drawer.classList.contains("open")) closeDrawer(); });
  $("swAuto").addEventListener("change", function (e) { sim.auto = e.target.checked; });
  document.querySelectorAll(".scn button").forEach(function (b) {
    b.addEventListener("click", function () { sim.run(b.getAttribute("data-s")); });
  });
  function bindSlider(id, key, d, unit) {
    var el = $(id);
    el.addEventListener("input", function () {
      var o = {}; o[key] = parseFloat(el.value); sim.setTargets(o);
      sim.auto = false; $("swAuto").checked = false;
      setText($(id + "V"), f(parseFloat(el.value), d) + unit);
    });
  }
  bindSlider("slVel", "vel", 1, " cm/s"); bindSlider("slLat", "lat", 1, " mm"); bindSlider("slAng", "ang", 1, "°");
  function syncSliders() {
    if (!drawer || drawer.hidden) return;
    [["slVel", sim.tg.vel, 1, " cm/s"], ["slLat", sim.tg.lat, 1, " mm"], ["slAng", sim.tg.ang, 1, "°"]].forEach(function (a) {
      var el = $(a[0]); if (document.activeElement === el) return;
      el.value = a[1]; setText($(a[0] + "V"), f(a[1], a[2]) + a[3]);
    });
  }
});
})();
