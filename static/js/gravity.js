/* Spacetime grid that curves around the cursor like a gravity well. See design/DESIGN.md §3.
   Line colours come from the CSS variables --grid and --grid-well, so it follows the theme. */
(function () {
  var c = document.getElementById("spacetime");
  if (!c || !c.getContext) return;
  var ctx = c.getContext("2d"),
    S = 40, R = 120, A = 0.6,            // grid spacing, softening radius, strength
    still = matchMedia("(prefers-reduced-motion: reduce)").matches,
    touch = matchMedia("(pointer: coarse)").matches,
    W, H, cols, rows, dpr, grid, well,
    tx = -1e4, ty = -1e4, mx = -1e4, my = -1e4,   // target / smoothed mass position
    amp = 0, ampT = 0,                            // current / target strength
    raf = 0, timer;

  function colors() {
    var s = getComputedStyle(document.documentElement);
    grid = s.getPropertyValue("--grid").trim() || "rgba(120,130,150,.15)";
    well = s.getPropertyValue("--grid-well").trim() || grid;
  }

  function size() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    c.width = W * dpr; c.height = H * dpr;
    cols = Math.ceil(W / S) + 2; rows = Math.ceil(H / S) + 2;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  // Pull grid point (x, y) toward the mass: p' = p - A R^2 / (r^2 + R^2) (p - m)
  function warp(x, y) {
    if (amp < 1e-3) return [x, y];
    var dx = x - mx, dy = y - my, R2 = R * R,
      pull = amp * R2 / (dx * dx + dy * dy + R2);
    return [x - pull * dx, y - pull * dy];
  }

  function line(x0, y0, sx, sy, n) {
    ctx.beginPath();
    for (var i = 0; i < n; i++) {
      var p = warp(x0 + sx * i, y0 + sy * i);
      i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
    }
    ctx.stroke();
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    var o = -S / 2, i, k = amp / A;
    if (k > 1e-3) {                       // lines darken slightly inside the well
      var g = ctx.createRadialGradient(mx, my, 0, mx, my, R * 2.5 * k);
      g.addColorStop(0, well); g.addColorStop(1, grid);
      ctx.strokeStyle = g;
    } else ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (i = 0; i < rows; i++) line(o, o + i * S, S / 2, 0, cols * 2);
    for (i = 0; i < cols; i++) line(o + i * S, o, 0, S / 2, rows * 2);
  }

  function frame() {
    var dx = (tx - mx) * 0.15, dy = (ty - my) * 0.15, da;
    if (touch) { ampT *= 0.97; da = ampT - amp; amp = ampT; }   // tap well slowly fades
    else { da = (ampT - amp) * 0.08; amp += da; }
    mx += dx; my += dy;
    draw();
    // idle: displacement change < 0.1px -> stop the loop (no CPU while reading)
    if (Math.abs(dx) + Math.abs(dy) < 0.1 && Math.abs(da) * R < 0.1) {
      raf = 0;
      if (ampT < 0.03) { amp = ampT = 0; draw(); }   // well fully gone: back to flat grid
    } else raf = requestAnimationFrame(frame);
  }
  function wake() { if (!raf && !document.hidden) raf = requestAnimationFrame(frame); }

  colors(); size();
  addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(size, 150); });
  addEventListener("themechange", function () { colors(); draw(); });
  if (still) return;                       // reduced motion: static flat grid only

  if (touch) {
    addEventListener("pointerdown", function (e) {
      tx = mx = e.clientX; ty = my = e.clientY; ampT = A; wake();
    }, { passive: true });
  } else {
    addEventListener("pointermove", function (e) {
      if (amp < 1e-3) { mx = e.clientX; my = e.clientY; }  // appear where the cursor enters
      tx = e.clientX; ty = e.clientY; ampT = A; wake();
    }, { passive: true });
    document.documentElement.addEventListener("mouseleave", function () { ampT = 0; wake(); });
  }
  document.addEventListener("visibilitychange", function () {
    if (document.hidden && raf) { cancelAnimationFrame(raf); raf = 0; } else wake();
  });
})();
