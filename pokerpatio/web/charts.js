/* Tiny dependency-free SVG chart library — everything is drawn from real data
   returned by the API. No CDN, no build step. */
(function (global) {
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = {
    safe: "#3fb950", optimal: "#58a6ff", risky: "#f85149",
    gold: "#d9a441", violet: "#a371f7", muted: "#8493a8",
    won: "#3fb950", lost: "#f85149",
  };

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function clear(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }
  function nice(v) {
    const a = Math.abs(v);
    if (a >= 10000) return (v / 1000).toFixed(1) + "k";
    if (a >= 1000) return (v / 1000).toFixed(2) + "k";
    if (a >= 100) return Math.round(v).toString();
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }
  function niceNum(range) {
    const exp = Math.floor(Math.log10(Math.max(range, 1e-9)));
    const f = range / Math.pow(10, exp);
    const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
    return nf * Math.pow(10, exp);
  }
  function bounds(series, ticks) {
    let lo = 0, hi = 0;
    series.forEach(s => s.values.forEach(v => {
      if (v == null || Number.isNaN(v)) return;
      lo = Math.min(lo, v); hi = Math.max(hi, v);
    }));
    if (lo === hi) { hi = lo + 1; lo = Math.min(0, lo); }
    const t = ticks || 4;
    const step = niceNum((hi - lo) / t);
    return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step];
  }
  function axes(svg, box, lo, hi, opts) {
    const { l, r, t, b } = box;
    const w = svg.viewBox.baseVal.width, h = svg.viewBox.baseVal.height;
    const plotW = w - l - r, plotH = h - t - b;
    const ticks = opts.ticks || 4;
    for (let i = 0; i <= ticks; i++) {
      const y = t + (plotH * i) / ticks;
      const val = hi - ((hi - lo) * i) / ticks;
      el("line", { x1: l, y1: y, x2: w - r, y2: y, stroke: "#1b2432", "stroke-width": 1 }, svg);
      const tx = el("text", { x: l - 6, y: y + 3, "text-anchor": "end", fill: "#64748b",
        "font-size": 9, "font-family": "ui-monospace, monospace" }, svg);
      tx.textContent = nice(val);
    }
    if (lo < 0 && hi > 0) {
      const zeroY = t + plotH * (hi / (hi - lo));
      el("line", { x1: l, y1: zeroY, x2: w - r, y2: zeroY, stroke: "#3b4a5f",
        "stroke-width": 1, "stroke-dasharray": "4 3" }, svg);
    }
    return { plotW, plotH, l, r, t, b, w, h };
  }

  /* series: [{name, color, values:[y...]}], xValues optional */
  function line(svg, series, opts = {}) {
    clear(svg);
    const box = { l: 44, r: 12, t: 10, b: 20 };
    const [lo, hi] = bounds(series, opts.ticks || 5);
    const a = axes(svg, box, lo, hi, { ...opts, ticks: opts.ticks || 5 });
    const n = Math.max(...series.map(s => s.values.length), 2);
    const x = i => a.l + (a.plotW * i) / Math.max(1, n - 1);
    const y = v => a.t + a.plotH * (1 - (v - lo) / (hi - lo));
    series.forEach(s => {
      if (!s.values.length) return;
      const pts = s.values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ");
      const grad = el("linearGradient", {
        id: "g-" + s.name.replace(/\W/g, ""), x1: 0, y1: 0, x2: 0, y2: 1 }, svg);
      el("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": .14 }, grad);
      el("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": 0 }, grad);
      const area = `M ${x(0)},${y(Math.max(lo, 0))} ` +
        s.values.map((v, i) => `L ${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(" ") +
        ` L ${x(s.values.length - 1)},${y(Math.max(lo, 0))} Z`;
      el("path", { d: area, fill: `url(#g-${s.name.replace(/\W/g, "")})`, stroke: "none" }, svg);
      el("polyline", { points: pts, fill: "none", stroke: s.color, "stroke-width": 1.8,
        "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      const lastX = x(s.values.length - 1), lastY = y(s.values[s.values.length - 1]);
      el("circle", { cx: lastX, cy: lastY, r: 2.6, fill: s.color }, svg);
    });
    return a;
  }

  /* categories: [label], series: [{name,color,values}] -> grouped bars (may go negative) */
  function grouped(svg, categories, series, opts = {}) {
    clear(svg);
    const box = { l: 40, r: 10, t: 8, b: opts.b || 26 };
    const [lo, hi] = bounds(series, opts.ticks || 4);
    const a = axes(svg, box, lo, hi, { ...opts, ticks: opts.ticks || 4 });
    const y = v => a.t + a.plotH * (1 - (v - lo) / (hi - lo));
    const zero = y(0);
    const gw = a.plotW / Math.max(1, categories.length);
    const bw = Math.min(26, (gw * 0.72) / series.length);
    categories.forEach((cat, ci) => {
      const gx = a.l + gw * ci + gw / 2 - (bw * series.length) / 2;
      series.forEach((s, si) => {
        const v = s.values[ci] ?? 0;
        const bx = gx + si * bw;
        const top = y(Math.max(0, v)), hgt = Math.abs(y(v) - zero);
        const rect = el("rect", {
          x: bx, y: Math.min(top, zero), width: Math.max(1.5, bw - 2), height: Math.max(1, hgt),
          rx: 2, fill: s.color, "fill-opacity": .88 }, svg);
        const ttl = el("title", {}, rect);
        ttl.textContent = `${cat} · ${s.name}: ${nice(v)}`;
        if (Math.abs(v) > 0 && bw > 16) {
          const lb = el("text", { x: bx + (bw - 2) / 2, y: v >= 0 ? Math.min(top, zero) - 3 : Math.min(top, zero) + hgt + 9,
            "text-anchor": "middle", fill: "#8b98a9", "font-size": 8.5 }, svg);
          lb.textContent = nice(v);
        }
      });
      const t = el("text", { x: a.l + gw * ci + gw / 2, y: a.h - 8, "text-anchor": "middle",
        fill: "#8493a8", "font-size": 9.5 }, svg);
      t.textContent = cat;
    });
    return a;
  }

  /* stacked percentage bars */
  function stacked(svg, categories, series, opts = {}) {
    clear(svg);
    const box = { l: 34, r: 8, t: 8, b: 24 };
    const a = { l: box.l, t: box.t, plotW: svg.viewBox.baseVal.width - box.l - box.r,
                plotH: svg.viewBox.baseVal.height - box.t - box.b,
                h: svg.viewBox.baseVal.height };
    const gw = a.plotW / Math.max(1, categories.length);
    const bw = Math.min(46, gw * 0.6);
    for (let i = 0; i <= 4; i++) {
      const y = a.t + (a.plotH * i) / 4;
      el("line", { x1: a.l, y1: y, x2: a.l + a.plotW, y2: y, stroke: "#1b2432" }, svg);
      const t = el("text", { x: a.l - 5, y: y + 3, "text-anchor": "end", fill: "#64748b", "font-size": 8.5 }, svg);
      t.textContent = (100 - i * 25) + "%";
    }
    categories.forEach((cat, ci) => {
      const total = series.reduce((s, k) => s + (k.values[ci] || 0), 0) || 1;
      let acc = 0;
      const x = a.l + gw * ci + (gw - bw) / 2;
      series.forEach(s => {
        const v = s.values[ci] || 0;
        const hgt = (v / total) * a.plotH;
        const rect = el("rect", { x, y: a.t + a.plotH - acc - hgt, width: bw, height: Math.max(0.5, hgt),
          fill: s.color, "fill-opacity": .9 }, svg);
        const ttl = el("title", {}, rect);
        ttl.textContent = `${cat} · ${s.name}: ${v} (${(v / total * 100).toFixed(1)}%)`;
        acc += hgt;
      });
      const t = el("text", { x: x + bw / 2, y: a.h - 7, "text-anchor": "middle", fill: "#8493a8", "font-size": 9.5 }, svg);
      t.textContent = cat;
    });
  }

  function legend(node, series) {
    node.innerHTML = series.map(s =>
      `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  }

  global.Charts = { line, grouped, stacked, legend, clear, COLORS, nice };
})(window);
