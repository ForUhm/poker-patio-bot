/* Poker Patio Bot Control — front-end controller.
   Talks to the FastAPI backend: /api/bot/*, /api/sim/*, /api/rangegrid, /api/stream. */

const $ = (id) => document.getElementById(id);
const SUITS = { s: "♠", h: "♥", d: "♦", c: "♣" };
const COLORS = { safe: "#3fb950", optimal: "#58a6ff", risky: "#f85149" };
let META = null;
let BOT = null;
let SIM = { status: "idle", results: null, progress: 0 };
let rangeSeat = "BTN";
let rangeKind = "rfi";
let LIVE = null;
let liveShotOn = false;
let lastShotAt = 0;

/* ------------------------------------------------------------------ utils */
const fmt = (v, d = 1) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  return (n >= 0 ? "" : "") + n.toLocaleString(undefined, {
    minimumFractionDigits: Math.abs(n) < 100 ? d : 0,
    maximumFractionDigits: Math.abs(n) < 100 ? d : 0,
  });
};
const signed = (v, d = 1) => (v > 0 ? "+" : "") + fmt(v, d);
const pct = (v) => (v === null || v === undefined) ? "—" : Number(v).toFixed(1) + "%";

function cardNode(code, cls = "") {
  const d = document.createElement("div");
  if (!code) { d.className = "card " + cls + " back"; return d; }
  const rank = code[0], suit = code[1].toLowerCase();
  d.className = "card " + cls + (suit === "h" || suit === "d" ? " red" : "");
  d.innerHTML = `<span class="rk">${rank === "T" ? "10" : rank}</span><span class="su">${SUITS[suit] || ""}</span>`;
  d.title = code;
  return d;
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}
const post = (url, body) => getJSON(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

/* ------------------------------------------------------------------- meta */
async function loadMeta() {
  META = await getJSON("/api/meta");
  renderStrategies();
  renderTheory();
  renderFormulas();
  renderAdapter(META.adapter);
  $("adapter-line").textContent =
    `adapter: ${META.adapter.mode} · ${META.adapter.selectors_configured ? "selectors set" : "no live site attached"}`;
}

function renderStrategies() {
  const wrap = $("strategy-grid");
  wrap.innerHTML = "";
  META.strategies.forEach((s) => {
    const div = document.createElement("div");
    div.className = "strategy" + (BOT && BOT.strategy === s.key ? " active" : "");
    div.style.setProperty("--accent", COLORS[s.key]);
    div.dataset.key = s.key;
    div.innerHTML = `
      <div class="srow">
        <div class="sname"><i class="swatch"></i>${s.label}</div>
        <span class="tagmini">${s.open_widths_pct.BTN ?? "—"}% BTN</span>
      </div>
      <div class="sdesc">${s.notes}</div>
      <div class="sparams">
        <span class="tagmini">range ${s.params.range_adjust_pp > 0 ? "+" : ""}${s.params.range_adjust_pp}pp</span>
        <span class="tagmini">bluff ${(s.params.bluff_freq * 100).toFixed(0)}%</span>
        <span class="tagmini">call margin ${(s.params.call_margin * 100).toFixed(0)}pp</span>
        <span class="tagmini">size ×${s.params.sizing_bias}</span>
      </div>`;
    div.onclick = async () => {
      BOT = await post("/api/bot/strategy", { strategy: s.key });
      renderStrategies();
      renderBot(BOT);
      loadRange();
    };
    wrap.appendChild(div);
  });
}

function renderTheory() {
  const t = $("theory-table");
  const rows = META.strategies.map((s) => `
    <tr>
      <td><b style="color:${COLORS[s.key]}">${s.label}</b></td>
      <td>${s.open_widths_pct.UTG}% / ${s.open_widths_pct.CO}% / ${s.open_widths_pct.BTN}%</td>
      <td>${s.defend_widths_pct.UTG}% / ${s.defend_widths_pct.CO}% / ${s.defend_widths_pct.BTN}%</td>
      <td>${(s.params.bluff_freq * 100).toFixed(0)}%</td>
      <td>${(s.params.call_margin * 100).toFixed(0)}pp</td>
      <td>${s.params.sizing_bias}×</td>
      <td>${(s.params.value_threshold * 100).toFixed(0)}%</td>
    </tr>`).join("");
  t.innerHTML = `<thead><tr>
      <th>Strategy</th><th class="num">Open % UTG / CO / BTN</th><th class="num">Defend % UTG / CO / BTN</th>
      <th class="num">Bluff freq</th><th class="num">Call margin</th><th class="num">Sizing</th>
      <th class="num">Value thresh.</th></tr></thead><tbody>${rows}</tbody>`;
}

function renderFormulas() {
  const d = META.docs;
  $("formulas").innerHTML = [
    ["Pot odds (required equity)", d.pot_odds],
    ["Alpha (bluff break-even)", d.alpha],
    ["MDF (defence floor)", d.mdf],
    ["SPR", d.spr],
    ["EV of a call", d.ev_call],
    ["Equity", "Monte-Carlo over live ranges, not vs random hands"],
  ].map(([k, v]) => `<div class="formula"><b>${k}</b><code>${v}</code></div>`).join("");
}

function renderAdapter(a) {
  $("adapter-detail").textContent = a.detail;
  const pill = $("conn-pill");
  pill.className = "pill " + (a.reachable ? "live" : "warn");
  pill.innerHTML = `<i class="dot"></i><span>${a.mode} · ${a.reachable ? "live" : "local engine"}</span>`;
  $("footer-adapter").textContent = `target: ${a.target || "—"}`;
}

/* -------------------------------------------------------------------- bot */
function renderBot(s) {
  BOT = s;
  $("k-hands").textContent = s.hands;
  $("k-net").textContent = signed(s.net, 0);
  $("k-net").className = s.net >= 0 ? "pos" : "neg";
  $("k-bb100").textContent = signed(s.bb_per_100, 1);
  $("k-bb100").className = s.bb_per_100 >= 0 ? "pos" : "neg";
  $("k-win").textContent = pct(s.win_rate_pct);
  $("k-sd").textContent = s.showdowns ? pct(s.showdown_win_pct) : "—";
  $("k-rebuy").textContent = s.rebuys;
  $("table-meta").textContent = `hand #${s.hands} · ${s.strategy_label} · ${s.hands_per_min} h/min`;
  $("live-net").textContent = signed(s.net, 0) + " chips";

  document.querySelectorAll(".strategy").forEach((n) => {
    n.classList.toggle("active", n.dataset.key === s.strategy);
  });

  // keep the pace control in sync with the runner (unless the user is dragging)
  const rateEl = $("rate");
  if (document.activeElement !== rateEl && Number(rateEl.value) !== Math.round(s.hands_per_min)) {
    rateEl.value = Math.round(s.hands_per_min);
  }
  $("rate-out").textContent = Math.round(s.hands_per_min) + " hands/min";

  const pill = $("sim-pill");
  pill.textContent = s.running ? `bot: running · ${s.hands} hands` : (s.paused ? "bot: paused" : "bot: stopped");
  pill.className = "pill " + (s.running ? "live" : "");

  renderTable(s.last);
  renderDecision(s.last);
  renderFeed(s.feed);
  drawLiveCharts(s);
}

function renderTable(last) {
  const seats = last?.table?.seats || [];
  const board = last?.table?.board?.length ? last.table.board : (last?.board || []);
  $("pot").textContent = "pot " + fmt(last?.table?.pot ?? 0, 1);
  $("street-badge").textContent =
    last ? (board.length === 0 ? "preflop" : board.length === 3 ? "flop" : board.length === 4 ? "turn" : "river") : "—";

  const bWrap = $("board");
  bWrap.innerHTML = "";
  if (!board.length) {
    for (let i = 0; i < 5; i++) {
      const ph = document.createElement("div");
      ph.className = "card big back";
      ph.style.opacity = 0.18;
      bWrap.appendChild(ph);
    }
  } else {
    board.forEach((c) => bWrap.appendChild(cardNode(c, "big")));
  }

  for (let i = 0; i < 6; i++) {
    const node = $("seat" + i);
    const p = seats[i];
    if (!p) { node.style.display = "none"; continue; }
    node.style.display = "grid";
    node.className = "seat" + (p.hero ? " hero" : "");
    const cards = document.createElement("div");
    cards.className = "scards";
    if (p.hero) {
      const hc = last?.hero_cards || [];
      if (hc.length) hc.forEach((c) => cards.appendChild(cardNode(c, "mini")));
      else for (let k = 0; k < 2; k++) cards.appendChild(cardNode("", "mini back"));
    } else if (p.in_hand) {
      for (let k = 0; k < 2; k++) cards.appendChild(cardNode("", "mini back"));
    }
    node.innerHTML = `
      <div class="sname"><span>${p.hero ? "HERO" : p.name}</span>
        <span class="muted">${p.last_action || ""}</span></div>
      <div class="sstack">${fmt(p.stack, 1)}</div>`;
    node.appendChild(cards);
  }
}

function renderDecision(last) {
  const d = last?.decision;
  if (!d) return;
  $("dec-rationale").textContent = d.rationale || "—";
  const tags = $("dec-tags");
  tags.innerHTML = "";
  (d.tags || []).forEach((t) => {
    const s = document.createElement("span");
    s.className = "tag" + (["bluff", "bluff-raise", "speculative", "loose-call"].includes(t) ? " warn" : t === "value" ? "gold" : "");
    s.textContent = t;
    tags.appendChild(s);
  });
  const eq = (d.equity || 0) * 100, req = (d.required_equity || 0) * 100, mdfv = (d.mdf || 0) * 100;
  $("m-eq").style.width = Math.min(100, eq) + "%";
  $("m-req").style.width = Math.min(100, req) + "%";
  $("m-mdf").style.width = Math.min(100, mdfv) + "%";
  $("m-eq-v").textContent = eq.toFixed(1) + "%";
  $("m-req-v").textContent = req.toFixed(1) + "%";
  $("m-mdf-v").textContent = mdfv.toFixed(0) + "%";
}

function renderFeed(feed) {
  const wrap = $("feed");
  if (!feed || !feed.length) { wrap.innerHTML = `<div class="muted small">no hands yet</div>`; return; }
  wrap.innerHTML = "";
  feed.forEach((h) => {
    const row = document.createElement("div");
    row.className = "feed-row";
    row.innerHTML = `<span class="h">#${h.hand_id}</span>
      <span>${h.pos}</span>
      <span class="h">${h.cards || "—"} ${h.board ? "· " + h.board : ""} ${h.showdown ? "· SD" : ""}</span>
      <span class="d ${h.delta >= 0 ? "pos" : "neg"}">${signed(h.delta, 1)}</span>`;
    wrap.appendChild(row);
  });
}

function drawLiveCharts(s) {
  const br = s.bankroll && s.bankroll.length ? s.bankroll : [0, 0];
  Charts.line($("chart-live"), [{ name: s.strategy_label || "hero", color: COLORS[s.strategy] || "#58a6ff", values: br }]);
  Charts.grouped($("chart-wonlost"), ["Won", "Lost"], [
    { name: "won", color: "#3fb950", values: [s.won, 0] },
    { name: "lost", color: "#f85149", values: [0, -s.lost] },
  ]);
  const acts = s.actions || {};
  const keys = ["fold", "check", "call", "bet", "raise"];
  Charts.grouped($("chart-live-actions"), keys.map((k) => k.slice(0, 5)), [
    { name: "actions", color: "#58a6ff", values: keys.map((k) => acts[k] || 0) },
  ], { b: 24 });
  $("live-af").textContent = "AF " + (s.aggression_factor ?? "—");
}

/* ------------------------------------------------------------------- sim */
async function runSim() {
  const hands = Math.max(50, Math.min(5000, Number($("sim-hands").value) || 400));
  const iters = Math.max(20, Math.min(220, Number($("sim-iters").value) || 45));
  const seedRaw = $("sim-seed").value.trim();
  const body = { hands, iters };
  if (seedRaw) body.seed = Number(seedRaw);
  $("btn-sim").disabled = true;
  $("sim-status").textContent = "starting…";
  try {
    await post("/api/sim/start", body);
  } catch (e) {
    $("sim-status").textContent = String(e.message);
    $("btn-sim").disabled = false;
    return;
  }
  pollSim();
}

async function pollSim() {
  const s = await getJSON("/api/sim/status");
  SIM = s;
  $("sim-progress").style.width = Math.round((s.progress || 0) * 100) + "%";
  $("sim-pill").textContent = s.status === "running"
    ? `sim: ${Math.round((s.progress || 0) * 100)}%`
    : `sim: ${s.status}`;
  if (s.status === "running") {
    $("sim-status").textContent = `${s.stage || ""} · ${s.elapsed || 0}s · ${s.params?.hands || 0} hands/strategy`;
    setTimeout(pollSim, 900);
    return;
  }
  $("btn-sim").disabled = false;
  if (s.status === "error") { $("sim-status").textContent = "error: " + s.error; return; }
  if (s.status === "done" && s.results) {
    $("sim-status").textContent =
      `done · ${s.params?.hands} hands/strategy · ${s.elapsed}s · seed ${s.params?.seed}`;
    renderSim(s.results);
  }
}

function renderSim(res) {
  const keys = ["safe", "optimal", "risky"].filter((k) => res[k]);
  const labels = { safe: "Safe", optimal: "Optimal", risky: "Risky" };

  Charts.line($("chart-cmp"), keys.map((k) => ({
    name: labels[k], color: COLORS[k], values: res[k].bankroll || [0],
  })));
  Charts.legend($("legend-cmp"), keys.map((k) => ({
    name: `${labels[k]} · ${signed(res[k].net_bb, 1)}bb · ${signed(res[k].bb_per_100, 1)}±${res[k].ci95_bb100} bb/100`,
    color: COLORS[k] })));

  Charts.grouped($("chart-net"), keys.map((k) => labels[k]), [
    { name: "won", color: "#3fb950", values: keys.map((k) => res[k].won) },
    { name: "lost", color: "#f85149", values: keys.map((k) => -res[k].lost) },
    { name: "net", color: "#58a6ff", values: keys.map((k) => res[k].net) },
  ]);

  Charts.grouped($("chart-rates"), keys.map((k) => labels[k]), [
    { name: "win %", color: "#58a6ff", values: keys.map((k) => res[k].win_rate_pct) },
    { name: "showdown %", color: "#d9a441", values: keys.map((k) => res[k].showdown_win_pct) },
    { name: "fold-win %", color: "#a371f7", values: keys.map((k) => res[k].fold_win_pct) },
  ]);

  Charts.grouped($("chart-dd"), keys.map((k) => labels[k]), [
    { name: "max drawdown", color: "#f85149", values: keys.map((k) => -res[k].max_drawdown) },
  ]);

  const acts = ["fold", "check", "call", "bet", "raise"];
  Charts.stacked($("chart-actions"), keys.map((k) => labels[k]),
    acts.map((a, i) => ({
      name: a,
      color: ["#39485c", "#5a6b82", "#58a6ff", "#d9a441", "#f85149"][i],
      values: keys.map((k) => res[k].actions[a] || 0),
    })));

  const positions = ["UTG", "HJ", "CO", "BTN", "SB", "BB"];
  Charts.grouped($("chart-pos"), positions,
    keys.map((k) => ({ name: labels[k], color: COLORS[k], values: positions.map((p) => res[k].by_position[p] || 0) })));
  Charts.legend($("legend-pos"), keys.map((k) => ({ name: labels[k], color: COLORS[k] })));

  const rows = keys.map((k) => {
    const r = res[k];
    const cls = (v) => (v >= 0 ? "pos" : "neg");
    return `<tr>
      <td><b style="color:${COLORS[k]}">${labels[k]}</b></td>
      <td class="num">${r.hands}</td>
      <td class="num ${cls(r.net)}">${signed(r.net, 1)}</td>
      <td class="num ${cls(r.net_bb)}">${signed(r.net_bb, 1)}</td>
      <td class="num ${cls(r.bb_per_100)}">${signed(r.bb_per_100, 1)} <span class="muted">±${r.ci95_bb100 ?? 0}</span>${Math.abs(r.bb_per_100) < (r.ci95_bb100 || 0) ? ' <span class="tagmini" title="95% CI includes zero — not statistically distinguishable from break-even at this sample size">n.s.</span>' : ''}</td>
      <td class="num">${pct(r.win_rate_pct)}</td>
      <td class="num">${pct(r.showdown_win_pct)}</td>
      <td class="num neg">${signed(-r.max_drawdown, 1)}</td>
      <td class="num">${r.aggression_factor}</td>
      <td class="num">${r.biggest_win}</td>
      <td class="num">${r.biggest_loss}</td>
      <td class="num">${r.profit_factor ?? "—"}</td>
      <td class="num">${r.rebuys}</td>
      <td class="num">${r.hands_per_s}</td>
    </tr>`;
  }).join("");
  $("sim-table").innerHTML = `<thead><tr>
      <th>Strategy</th><th class="num">Hands</th><th class="num">Net</th><th class="num">Net bb</th>
      <th class="num">bb/100</th><th class="num">Win %</th><th class="num">SD win %</th>
      <th class="num">Drawdown</th><th class="num">AF</th><th class="num">Big win</th>
      <th class="num">Big loss</th><th class="num">PF</th><th class="num">Rebuys</th><th class="num">h/s</th>
    </tr></thead><tbody>${rows}</tbody>`;
}

/* ------------------------------------------------------------- range grid */
async function loadRange() {
  const strat = BOT ? BOT.strategy : "optimal";
  const data = await getJSON(`/api/rangegrid?strategy=${strat}&seat=${rangeSeat}&kind=${rangeKind}`);
  const g = $("range-grid");
  g.innerHTML = "";
  data.grid.forEach((row, i) => row.forEach((cell, j) => {
    const d = document.createElement("div");
    const isPair = cell.label.length === 2;
    d.className = "range-cell" + (cell.in ? " in" : "") + (isPair ? " pair" : "");
    d.textContent = cell.label;
    d.title = `${cell.label} · ${cell.combos} combos · ${cell.in ? "in range" : "fold"}`;
    g.appendChild(d);
  }));
  $("range-meta").textContent =
    `${strat} · ${rangeKind === "rfi" ? "open-raise" : "defend"} from ${rangeSeat} · ${data.width_pct}% of hands`;
  document.querySelectorAll(".seg button[data-seat]").forEach((b) =>
    b.classList.toggle("on", b.dataset.seat === rangeSeat));
  document.querySelectorAll(".seg button[data-kind]").forEach((b) =>
    b.classList.toggle("on", b.dataset.kind === rangeKind));
}

function buildRangeControls() {
  const seg = $("range-seg");
  seg.innerHTML = "";
  ["UTG", "HJ", "CO", "BTN", "SB", "BB"].forEach((s) => {
    const b = document.createElement("button");
    b.textContent = s; b.dataset.seat = s; b.className = s === rangeSeat ? "on" : "";
    b.onclick = () => { rangeSeat = s; loadRange(); };
    seg.appendChild(b);
  });
  const kindSeg = document.createElement("div");
  kindSeg.className = "seg";
  [["rfi", "open"], ["defend", "defend"]].forEach(([k, label]) => {
    const b = document.createElement("button");
    b.textContent = label; b.dataset.kind = k; b.className = k === rangeKind ? "on" : "";
    b.onclick = () => { rangeKind = k; loadRange(); };
    kindSeg.appendChild(b);
  });
  seg.appendChild(kindSeg);
}


/* --------------------------------------------------------------- live site */
function liveModeUI() {
  const mode = $("lv-mode").value;
  document.querySelectorAll(".login-only").forEach(e => e.style.display = mode === "public" ? "grid" : "none");
  document.querySelectorAll(".pub-only").forEach(e => e.style.display = mode === "public" ? "grid" : "none");
  document.querySelectorAll(".sp-only").forEach(e => e.style.display = mode === "singleplayer" ? "grid" : "none");
  $("live-mode-label").textContent = mode === "public"
    ? "pokerpatio.com · public tables"
    : "pokerpatio.com · singleplayer vs site bots";
}

async function liveConnect() {
  const btn = $("lv-connect");
  btn.disabled = true;
  btn.textContent = "Connecting…";
  const sel = $("lv-table");
  const opt = sel.options[sel.selectedIndex];
  const payload = {
    mode: $("lv-mode").value,
    email: $("lv-email").value.trim(),
    password: $("lv-password").value,
    username: $("lv-username").value.trim() || "patiobot",
    difficulty: $("lv-difficulty").value,
    room_id: sel.value || "",
    buyin: $("lv-buyin") ? $("lv-buyin").value : "avg",
    table: (opt && opt.dataset && opt.dataset.name) || "",
    strategy: BOT ? BOT.strategy : "optimal",
    dry_run: $("lv-dry").checked,
    remember: $("lv-remember").checked,
    stop_loss: Number($("lv-stop").value) || 0,
    opp_pct: Number($("lv-opp").value) || 55,
    action_delay: 0.6,
    headless: true,
  };
  try {
    LIVE = await post("/api/live/connect", payload);
  } catch (e) {
    $("lv-messages").textContent = "connect failed: " + e.message;
  } finally {
    // the password never stays in the DOM longer than the request
    $("lv-password").value = "";
    btn.disabled = false;
    btn.textContent = "Connect & play";
  }
  renderLive(LIVE);
}

async function liveDisconnect() {
  LIVE = await post("/api/live/disconnect", {});
  liveShotOn = false;
  renderLive(LIVE);
}

function renderLive(lv) {
  if (!lv) return;
  LIVE = lv;
  const pill = $("live-pill");
  const label = {
    idle: "not connected", connecting: "connecting…", playing: "playing",
    paused: "paused", stopped: "stopped", error: "error",
  }[lv.status] || lv.status;
  pill.className = "pill " + (lv.status === "playing" ? "live" : lv.status === "error" ? "warn" : "");
  pill.innerHTML = `<i class="dot"></i><span>${label}${lv.dry_run ? " · dry run" : ""}</span>`;

  $("lv-dec").textContent = lv.decisions;
  $("lv-hands").textContent = lv.hands_est;
  $("lv-net").textContent = signed(lv.net, 0);
  $("lv-net").className = lv.net >= 0 ? "pos" : "neg";
  $("lv-stack").textContent = lv.stack == null ? "—" : fmt(lv.stack, 0);
  $("lv-resets").textContent = lv.table_resets ?? 0;
  $("lv-elapsed").textContent = Math.round(lv.elapsed_s || 0) + "s";

  const feed = $("lv-feed");
  if (lv.feed && lv.feed.length) {
    feed.innerHTML = "";
    lv.feed.slice(0, 12).forEach(f => {
      const row = document.createElement("div");
      row.className = "lv-row";
      const ok = f.result && f.result.ok !== false;
      row.innerHTML = `
        <span class="muted">${f.street.slice(0, 5)}</span>
        <span class="mono">${f.hole}</span>
        <span class="mono muted">${f.board}</span>
        <span class="act ${f.action}">${f.action.toUpperCase()}${f.amount ? " " + Math.round(f.amount) : ""}
          ${ok ? "" : '<span class="tag warn" style="margin-left:4px">fail</span>'}</span>
        <span class="eq">${(f.equity * 100).toFixed(0)}%</span>`;
      row.title = f.rationale || "";
      feed.appendChild(row);
    });
  }
  $("lv-messages").textContent = (lv.messages || []).slice(0, 2).join("  ·  ");

  const connected = lv.status !== "idle" && lv.status !== "stopped" && lv.status !== "error";
  document.querySelector(".live-kpis").classList.toggle("stale", lv.status === "stopped" && lv.decisions > 0);
  if (connected) $("lv-dry").checked = !!lv.dry_run;
  ["lv-mode", "lv-email", "lv-password", "lv-username", "lv-difficulty",
   "lv-table", "lv-stop", "lv-opp", "lv-dry", "lv-remember", "lv-refresh", "lv-buyin"].forEach(id => {
    const el = $(id);
    if (el) el.disabled = connected;
  });
  $("lv-connect").disabled = connected;
  $("lv-disconnect").disabled = !connected;
  $("lv-logout").disabled = connected && lv.mode === "singleplayer";
  if (lv.vault && lv.vault.saved && !connected) {
    $("lv-vault").className = "vault-line on";
    $("lv-vault").innerHTML = `<i class="dot"></i>signed in as ${lv.vault.email_masked} · login stored`;
  }

  // live table panel takes over when a real session is running
  if (lv.obs && lv.status !== "idle" && lv.status !== "stopped") {
    renderLiveTable(lv);
    $("table-meta").textContent = `pokerpatio.com · ${lv.strategy_label} · ${lv.dry_run ? "dry run" : "live"}`;
  }
  if (lv.last_decision) {
    const d = lv.last_decision;
    $("dec-rationale").textContent = `[${lv.mode}] ${d.rationale}`;
    $("dec-tags").innerHTML = `<span class="tag gold">${d.action}</span>`;
    $("m-eq").style.width = Math.min(100, (d.equity || 0) * 100) + "%";
    $("m-req").style.width = Math.min(100, (d.required || 0) * 100) + "%";
    $("m-eq-v").textContent = ((d.equity || 0) * 100).toFixed(1) + "%";
    $("m-req-v").textContent = ((d.required || 0) * 100).toFixed(1) + "%";
  }

  const wantsShot = lv.status === "playing" || lv.status === "paused";
  if (wantsShot && Date.now() - lastShotAt > 5000) {
    lastShotAt = Date.now();
    refreshShot();
  }
  if (!wantsShot && liveShotOn) {
    liveShotOn = false;
    $("lv-shot").classList.remove("on");
    $("lv-shot-empty").style.display = "grid";
    $("lv-shot-empty").textContent = "no browser session";
  }
}

function refreshShot() {
  const img = $("lv-shot");
  const url = "/api/live/screenshot?t=" + Date.now();
  const probe = new Image();
  probe.onload = () => {
    img.src = url;
    img.classList.add("on");
    $("lv-shot-empty").style.display = "none";
    liveShotOn = true;
  };
  probe.onerror = () => {
    img.classList.remove("on");
    $("lv-shot-empty").style.display = "grid";
    $("lv-shot-empty").textContent = "screenshot unavailable";
  };
  probe.src = url;
}

function renderLiveTable(lv) {
  const o = lv.obs;
  const seats = o.seats || [];
  const heroIdx = seats.findIndex(s => s.hero);
  const rot = heroIdx > 0 ? seats.slice(heroIdx).concat(seats.slice(0, heroIdx)) : seats.slice();
  const board = o.board || [];
  $("pot").textContent = "pot " + fmt(o.pot || 0, 0);
  $("street-badge").textContent = (o.street || "").toUpperCase() + (o.my_turn ? " · YOUR TURN" : "");

  const bWrap = $("board");
  bWrap.innerHTML = "";
  if (!board.length) {
    for (let i = 0; i < 5; i++) {
      const ph = document.createElement("div");
      ph.className = "card big back";
      ph.style.opacity = 0.18;
      bWrap.appendChild(ph);
    }
  } else {
    board.forEach(c => bWrap.appendChild(cardNode(c, "big")));
  }

  for (let i = 0; i < 6; i++) {
    const node = $("seat" + i);
    const p = rot[i];
    if (!p) { node.style.display = "none"; continue; }
    node.style.display = "grid";
    node.className = "seat" + (p.hero ? " hero" : "") + (p.turn ? " acting" : "");
    const cards = document.createElement("div");
    cards.className = "scards";
    if (p.hero && (o.hole || []).length) {
      o.hole.forEach(c => cards.appendChild(cardNode(c, "mini")));
    } else if (p.in_hand) {
      for (let k = 0; k < 2; k++) cards.appendChild(cardNode("", "mini back"));
    }
    node.innerHTML = `
      <div class="sname"><span>${p.hero ? "HERO" : p.name}</span>
        <span class="muted">${p.dealer ? "D" : ""}${p.bet ? " " + Math.round(p.bet) : ""}</span></div>
      <div class="sstack">${fmt(p.stack, 0)}</div>`;
    node.appendChild(cards);
  }
}


const LOBBY_CACHE = { tables: [], at: 0 };

function fmtNum(n) {
  if (n === null || n === undefined) return "—";
  return Number(n).toLocaleString();
}

async function loadLobbies(force) {
  const sel = $("lv-table");
  const age = $("lv-table-age");
  const btn = $("lv-refresh");
  if (force) { btn.disabled = true; btn.textContent = "…"; age.textContent = "loading lobby…"; }
  try {
    const data = await getJSON("/api/live/lobbies" + (force ? "?refresh=1" : ""));
    LOBBY_CACHE.tables = data.tables || [];
    LOBBY_CACHE.at = Date.now();
    const prev = sel.value;
    sel.innerHTML = "";
    if (!LOBBY_CACHE.tables.length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = data.error ? "lobby unavailable: " + data.error : "no tables listed";
      sel.appendChild(o);
    } else {
      LOBBY_CACHE.tables.forEach(t => {
        const o = document.createElement("option");
        o.value = t.room_id || "";
        o.dataset.name = t.name || "";
        const seats = t.seats ? `${t.players}/${t.seats}` : (t.players_text || "—");
        o.textContent = `${t.name} — ${seats} players · ${t.stakes} · pot ${fmtNum(t.avg_pot)}`;
        sel.appendChild(o);
      });
      if (prev && LOBBY_CACHE.tables.some(t => t.room_id === prev)) sel.value = prev;
    }
    const ageS = data.age_s == null ? null : Math.round(data.age_s);
    age.textContent = data.error
      ? "error: " + data.error
      : `${LOBBY_CACHE.tables.length} tables${ageS != null ? " · " + ageS + "s ago" : ""}`;
    updateTableInfo();
    // the scout opens a browser on first use; keep polling until rows land
    if (!LOBBY_CACHE.tables.length) {
      loadLobbies._tries = (loadLobbies._tries || 0) + 1;
      if (loadLobbies._tries < 10) {
        age.textContent = data.error ? "retrying…" : "opening the lobby…";
        clearTimeout(loadLobbies._t);
        loadLobbies._t = setTimeout(() => loadLobbies(false), 2000);
      }
    } else {
      loadLobbies._tries = 0;
    }
  } catch (e) {
    age.textContent = "lobby unavailable";
  } finally {
    btn.disabled = false; btn.textContent = "↻";
  }
}

function updateTableInfo() {
  const sel = $("lv-table");
  const t = LOBBY_CACHE.tables.find(x => x.room_id === sel.value);
  const box = $("lv-table-info");
  if (!t) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <span class="pill-mini">players <b>${t.players ?? "—"}/${t.seats ?? "—"}</b></span>
    <span class="pill-mini">stakes <b>${t.stakes || "—"}</b></span>
    <span class="pill-mini">avg pot <b>${fmtNum(t.avg_pot)}</b></span>
    <span class="pill-mini">avg stack <b>${fmtNum(t.avg_stack)}</b></span>
    ${t.members_only ? '<span class="pill-mini">members only</span>' : ""}`;
}

async function loadVault() {
  try {
    const v = await getJSON("/api/live/credentials");
    const line = $("lv-vault");
    if (v.saved) {
      const bits = [`signed in as ${v.email_masked || "saved account"}`];
      if (v.has_session) bits.push("session cookie stored");
      if (v.has_password) bits.push("password stored (encrypted)");
      if (v.saved_ago) bits.push(v.saved_ago);
      line.className = "vault-line on";
      line.innerHTML = `<i class="dot"></i>${bits.join(" · ")}`;
      $("lv-password").placeholder = "saved — leave blank to reuse";
      $("lv-email").placeholder = v.email_masked || "you@example.com";
    } else {
      line.className = "vault-line";
      line.textContent = "no saved login — the first connect will store it";
      $("lv-password").placeholder = "••••••••";
      $("lv-email").placeholder = "you@example.com";
    }
    $("lv-remember").checked = v.saved ? !!v.remember_password : true;
    return v;
  } catch (e) { return null; }
}

async function doLogout() {
  LIVE = await post("/api/live/logout", {});
  renderLive(LIVE);
  $("lv-password").value = "";
  await loadVault();
  loadLobbies(false);
}

function wireLive() {
  $("lv-mode").onchange = () => {
    liveModeUI();
    if ($("lv-mode").value === "public") loadLobbies(false);
  };
  $("lv-connect").onclick = liveConnect;
  $("lv-disconnect").onclick = liveDisconnect;
  $("lv-logout").onclick = doLogout;
  $("lv-refresh").onclick = () => loadLobbies(true);
  $("lv-table").onchange = updateTableInfo;
  liveModeUI();
  loadVault();
  loadLobbies(false);
  getJSON("/api/live/state").then(renderLive).catch(() => {});
}

/* ---------------------------------------------------------------- wiring */
function wire() {
  $("btn-start").onclick = async () => {
    BOT = await post("/api/bot/start", {
      strategy: BOT?.strategy || "optimal",
      hands_per_min: Number($("rate").value),
      reset: false,
    });
    renderBot(BOT);
  };
  $("btn-pause").onclick = async () => {
    BOT = await post(BOT?.paused ? "/api/bot/resume" : "/api/bot/pause", {});
    renderBot(BOT);
  };
  $("btn-stop").onclick = async () => { BOT = await post("/api/bot/stop", {}); renderBot(BOT); };
  $("btn-reset").onclick = async () => {
    BOT = await post("/api/bot/start", {
      strategy: BOT?.strategy || "optimal",
      hands_per_min: Number($("rate").value),
      reset: true,
    });
    await post("/api/bot/stop", {});
    renderBot(BOT);
  };
  $("rate").oninput = (e) => {
    $("rate-out").textContent = e.target.value + " hands/min";
    if (BOT) post("/api/bot/rate", { hands_per_min: Number(e.target.value) }).then(renderBot);
  };
  $("btn-sim").onclick = runSim;
  $("btn-probe").onclick = async () => {
    const r = await getJSON("/api/adapter");
    await navigator.clipboard.writeText(r.probe_script);
    $("btn-probe").textContent = "Copied ✓";
    setTimeout(() => ($("btn-probe").textContent = "Copy DOM probe script"), 1800);
  };
}

function connectStream() {
  const es = new EventSource("/api/stream");
  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.bot) renderBot(data.bot);
      if (data.live) renderLive(data.live);
      if (data.sim) {
        $("sim-pill").textContent = data.sim.status === "running"
          ? `sim: ${Math.round((data.sim.progress || 0) * 100)}%` : `sim: ${data.sim.status}`;
      }
    } catch (e) { /* ignore malformed frame */ }
  };
  es.onerror = () => {
    const pill = $("conn-pill");
    pill.className = "pill warn";
    pill.innerHTML = `<i class="dot"></i><span>stream reconnecting</span>`;
  };
}

(async function init() {
  wire();
  wireLive();
  buildRangeControls();
  await loadMeta();
  try {
    BOT = await getJSON("/api/bot/state");
    renderBot(BOT);
    $("rate").value = BOT.hands_per_min;
    $("rate-out").textContent = BOT.hands_per_min + " hands/min";
  } catch (e) { console.error(e); }
  await loadRange();
  connectStream();
  pollSim();
})();
