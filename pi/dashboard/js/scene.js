/* RockU: dibujo de la correa vista desde arriba (cámara cenital).
   Mismo dibujo para la vista en vivo y para las miniaturas de evidencia.
   Unidades de la escena en mm; el campo visual mide 420 mm de ancho. */
(function (g) {
  "use strict";
  var LIM = g.RockU.LIM;
  var GAPS = [35, 62, 48, 85, 41, 70, 55, 38];      // separación entre barras (mm), periodo 434
  var BARS = [], acc = 0;
  GAPS.forEach(function (gp) { BARS.push(acc); acc += gp; });
  var DOTS = [[22, -24], [71, 30], [118, -14], [160, 28], [205, -30], [262, 12], [318, -20], [372, 24]]; // mm dentro del periodo

  var BLUE = "#0072EF", BLUE_HI = "#4C9AF7";

  function rng(seed) { var s = seed || 1; return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; }; }

  /* piedra facetada como en el logo: anillo exterior, anillo interior y centro */
  function rockPath(seed, w, h) {
    var r = rng(Math.floor(seed * 1000) + 7), out = [], inn = [], n = 8;
    for (var i = 0; i < n; i++) {
      var an = (i / n) * Math.PI * 2 + r() * 0.3;
      var k = 0.74 + r() * 0.3;
      out.push([Math.cos(an) * w / 2 * k, Math.sin(an) * h / 2 * k]);
      var an2 = ((i + 0.5) / n) * Math.PI * 2 + r() * 0.3;
      var k2 = 0.34 + r() * 0.2;
      inn.push([Math.cos(an2) * w / 2 * k2, Math.sin(an2) * h / 2 * k2]);
    }
    return { out: out, inn: inn, c: [(r() - 0.5) * w * 0.1, (r() - 0.5) * h * 0.1], r: r };
  }

  function facet(ctx, pts, hit, L, w) {
    var col;
    if (hit) { col = "rgb(" + Math.round(8 + L * 74) + "," + Math.round(64 + L * 118) + "," + Math.round(176 + L * 76) + ")"; }
    else { var gg = Math.round(30 + L * 66); col = "rgb(" + gg + "," + (gg + 8) + "," + (gg + 22) + ")"; }
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
    for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.closePath(); ctx.fill();
    ctx.strokeStyle = hit ? "rgba(200,225,255,.16)" : "rgba(255,255,255,.06)"; ctx.lineWidth = 1; ctx.stroke();
  }

  function drawRock(ctx, s, rock, hit) {
    var p = rockPath(rock.seed, rock.w * s, rock.h * s), n = p.out.length, half = rock.w * s * 0.5;
    ctx.save();
    ctx.translate(rock.x * s, rock.y * s);
    ctx.fillStyle = "rgba(14,26,37,.22)";
    ctx.beginPath(); ctx.ellipse(1.5 * s, 2.5 * s, rock.w * s * 0.5, rock.h * s * 0.46, 0, 0, 7); ctx.fill();
    function lum(pt, jit) { var v = (-pt[0] * 0.6 - pt[1] * 0.8) / half; return Math.max(0, Math.min(1, 0.5 + v * 0.5 + jit)); }
    for (var i = 0; i < n; i++) {
      var o1 = p.out[i], o2 = p.out[(i + 1) % n], i0 = p.inn[i], ip = p.inn[(i + n - 1) % n];
      var j1 = (p.r() - 0.5) * 0.28, j2 = (p.r() - 0.5) * 0.28, j3 = (p.r() - 0.5) * 0.2;
      facet(ctx, [o1, o2, i0], hit, lum([(o1[0] + o2[0] + i0[0]) / 3, (o1[1] + o2[1] + i0[1]) / 3], j1), half);
      facet(ctx, [o1, i0, ip], hit, lum([(o1[0] + i0[0] + ip[0]) / 3, (o1[1] + i0[1] + ip[1]) / 3], j2), half);
      facet(ctx, [ip, i0, p.c], hit, lum([(ip[0] + i0[0]) / 2, (ip[1] + i0[1]) / 2], j3 + 0.08), half);
    }
    ctx.restore();
  }

  function corners(ctx, x, y, w, h, len, lw, color) {
    ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(x, y + len); ctx.lineTo(x, y); ctx.lineTo(x + len, y);
    ctx.moveTo(x + w - len, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + len);
    ctx.moveTo(x + w, y + h - len); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - len, y + h);
    ctx.moveTo(x + len, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - len);
    ctx.stroke();
  }

  /* st: {phase, vel, lat, ang, dist, rocks[], state, signal, calib}
     o:  {ui:boolean, t:ms, tone:{...}} */
  function drawScene(ctx, W, H, st, o) {
    o = o || {};
    var ui = o.ui !== false, ov = !!o.overlayOnly;
    var s = W / LIM.fov;
    var cx = W / 2, cy = H / 2 - (ui ? 6 : 0);
    var T = o.t || 0;

    // fondo de la cámara
    if (!ov) {
    var bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#0A131C"); bg.addColorStop(1, "#0F1B28");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

    // belt
    ctx.save();
    ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.clip();
    ctx.translate(cx, cy + st.lat * s);
    ctx.rotate(st.ang * Math.PI / 180);
    var hw = 75 * s, xr = W * 1.2;

    // sombra bajo la correa
    ctx.fillStyle = "rgba(0,0,0,.35)";
    ctx.fillRect(-xr, -hw + 4 * s, xr * 2, hw * 2);
    // cuerpo
    var bgrad = ctx.createLinearGradient(0, -hw, 0, hw);
    bgrad.addColorStop(0, "#F7F9FC"); bgrad.addColorStop(0.5, "#EEF2F7"); bgrad.addColorStop(1, "#E2E8F0");
    ctx.fillStyle = bgrad; ctx.fillRect(-xr, -hw, xr * 2, hw * 2);
    ctx.fillStyle = "rgba(14,26,37,.22)";
    ctx.fillRect(-xr, -hw, xr * 2, Math.max(1, 1.2 * s));
    ctx.fillRect(-xr, hw - Math.max(1, 1.2 * s), xr * 2, Math.max(1, 1.2 * s));

    // líneas longitudinales (8 mm, a 10 mm del borde, centros a 61 mm)
    ctx.fillStyle = "#0E1A25";
    ctx.fillRect(-xr, -61 * s - 4 * s, xr * 2, 8 * s);
    ctx.fillRect(-xr, 61 * s - 4 * s, xr * 2, 8 * s);

    // marcas transversales y puntos (periodo 434 mm); x en campo visual -> centro en 0
    var off = st.phase - LIM.fov / 2;
    for (var n = -1; n <= 1; n++) {
      for (var i = 0; i < BARS.length; i++) {
        var xm = BARS[i] + 434 * n + off;
        if (xm < -LIM.fov / 2 - 20 || xm > LIM.fov / 2 + 20) continue;
        ctx.fillRect(xm * s - 3 * s, -57 * s, 6 * s, 114 * s);
      }
      for (var j = 0; j < DOTS.length; j++) {
        var dx = DOTS[j][0] + 434 * n + off;
        if (dx < -LIM.fov / 2 - 20 || dx > LIM.fov / 2 + 20) continue;
        ctx.beginPath(); ctx.arc(dx * s, DOTS[j][1] * s, 2.6 * s, 0, 7); ctx.fill();
      }
    }

    // piedras (en coordenadas de la correa)
    var rocks = st.rocks || [];
    ctx.save(); ctx.translate(-LIM.fov / 2 * s, 0);
    rocks.forEach(function (r) { drawRock(ctx, s, r, r.hit); });
    // visor del logo sobre la piedra detectada
    rocks.forEach(function (r) {
      if (!r.hit || r.x > LIM.fov + 40) return;
      var pad = 9 * s, bw = r.w * s + pad * 2, bh = r.h * s + pad * 2;
      var pulse = ui ? 0.75 + 0.25 * Math.sin(T / 260) : 1;
      ctx.globalAlpha = pulse;
      corners(ctx, r.x * s - bw / 2, r.y * s - bh / 2, bw, bh, Math.max(5, 11 * s), Math.max(2, 3.2 * s * (ui ? 0.8 : 1)), BLUE_HI);
      ctx.globalAlpha = 1;
    });
    ctx.restore();
    ctx.restore();
    }

    if (!ui) {
      if (st.state === "DETENIDA") { ctx.fillStyle = "rgba(214,52,42,.16)"; ctx.fillRect(0, 0, W, H); }
      return;
    }

    if (!ov) {
    // referencia calibrada (posición nominal de las líneas)
    ctx.save();
    ctx.setLineDash([6, 5]); ctx.lineWidth = 1.2; ctx.strokeStyle = "rgba(76,154,247,.85)";
    [-61, 61].forEach(function (y) { ctx.beginPath(); ctx.moveTo(0, cy + y * s); ctx.lineTo(W, cy + y * s); ctx.stroke(); });
    ctx.restore();

    // cota del desvío
    if (Math.abs(st.lat) > 2.5 && st.signal) {
      var xx = W - 92, y0 = cy - 61 * s, y1 = cy + st.lat * s - 61 * s;
      var col = Math.abs(st.lat) > LIM.latMax ? "#F5B031" : "#93A3B8";
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1.6; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(xx, y0); ctx.lineTo(xx, y1); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(xx - 5, y0); ctx.lineTo(xx + 5, y0); ctx.moveTo(xx - 5, y1); ctx.lineTo(xx + 5, y1); ctx.stroke();
      ctx.font = "600 12px Archivo, system-ui, sans-serif"; ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText((st.lat > 0 ? "+" : "") + st.lat.toFixed(1) + " mm", xx - 10, (y0 + y1) / 2);
    }

    // sensor HC-SR04 y su cono
    var sx = LIM.sensorX * s;
    var hit = rocks.some(function (r) { return r.hit && Math.abs(r.x - LIM.sensorX) < r.w / 2 + 6; });
    var seen = rocks.some(function (r) { return Math.abs(r.x - LIM.sensorX) < r.w / 2 + 3; });
    var top = 12, bot = cy + 75 * s + 6;
    if (seen && st.signal) {
      var cg = ctx.createLinearGradient(0, top + 16, 0, bot);
      cg.addColorStop(0, "rgba(61,145,245,.34)"); cg.addColorStop(1, "rgba(61,145,245,.05)");
      ctx.fillStyle = cg;
      ctx.beginPath(); ctx.moveTo(sx - 5, top + 16); ctx.lineTo(sx + 5, top + 16); ctx.lineTo(sx + 34 * s, bot); ctx.lineTo(sx - 34 * s, bot); ctx.closePath(); ctx.fill();
    }
    ctx.setLineDash([3, 4]); ctx.strokeStyle = "rgba(147,163,184,.55)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(sx, top + 16); ctx.lineTo(sx, bot); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = seen ? "#4C9AF7" : "#2B3C52";
    roundRect(ctx, sx - 15, top, 30, 16, 4); ctx.fill();
    ctx.fillStyle = "#0A131C";
    ctx.beginPath(); ctx.arc(sx - 7, top + 8, 4, 0, 7); ctx.arc(sx + 7, top + 8, 4, 0, 7); ctx.fill();
    ctx.fillStyle = "#93A3B8"; ctx.font = "500 11px Archivo, system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(st.signal ? "Sensor " + Math.round(st.dist) + " mm" : "Sensor sin datos", sx + 22, top + 8);

    // regla en mm
    var ry = H - 20;
    ctx.strokeStyle = "rgba(147,163,184,.5)"; ctx.fillStyle = "rgba(147,163,184,.8)"; ctx.lineWidth = 1;
    ctx.font = "500 10.5px Archivo, system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.beginPath(); ctx.moveTo(0, ry); ctx.lineTo(W, ry);
    for (var mm = 0; mm <= LIM.fov; mm += 10) {
      var long = mm % 50 === 0, x = mm * s;
      ctx.moveTo(x, ry); ctx.lineTo(x, ry - (long ? 8 : 4));
    }
    ctx.stroke();
    for (var m2 = 100; m2 <= 400; m2 += 100) ctx.fillText(m2 + " mm", m2 * s, ry + 12);

    }

    // esquinas de visor del campo de cámara
    corners(ctx, 12, 12, W - 24, H - 24, 18, 1.6, "rgba(232,238,246,.28)");

    // velo según estado
    if (st.state === "DETENIDA") {
      ctx.fillStyle = "rgba(214,52,42,.10)"; ctx.fillRect(0, 0, W, H);
    }
    if (st.state === "CALIBRANDO" && st.calib !== null) {
      var px = 12 + (W - 24) * st.calib;
      var lg = ctx.createLinearGradient(px - 60, 0, px, 0);
      lg.addColorStop(0, "rgba(76,154,247,0)"); lg.addColorStop(1, "rgba(76,154,247,.35)");
      ctx.fillStyle = lg; ctx.fillRect(px - 60, 12, 60, H - 24);
      ctx.fillStyle = BLUE_HI; ctx.fillRect(px - 1, 12, 2, H - 24);
    }
    if (!st.signal) {
      ctx.fillStyle = "rgba(10,19,28,.88)"; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "rgba(147,163,184,.10)"; ctx.lineWidth = 6;
      for (var k = -H; k < W; k += 22) { ctx.beginPath(); ctx.moveTo(k, H); ctx.lineTo(k + H, 0); ctx.stroke(); }
      ctx.fillStyle = "#E8EEF6"; ctx.font = "700 20px Archivo, system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("Sin imagen del teléfono", W / 2, H / 2 - 8);
      ctx.fillStyle = "#93A3B8"; ctx.font = "500 13px Archivo, system-ui, sans-serif";
      ctx.fillText("Reintentando conexión con CorreaCam", W / 2, H / 2 + 16);
    }
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  function drawCover(ctx, img, W, H) {
    var iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    var k = Math.max(W / iw, H / ih), w = iw * k, h = ih * k;
    ctx.drawImage(img, (W - w) / 2, (H - h) / 2, w, h);
  }

  g.RockU.drawScene = drawScene;
  g.RockU.drawCover = drawCover;
})(window);
