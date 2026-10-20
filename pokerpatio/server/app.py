"""FastAPI backend: strategy metadata, batch simulation, live bot control, SSE."""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import json
import os
import threading
import time
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.cards import ALL_CLASSES, RANKS, class_combos
from core.mathx import MDF_TABLE
from core.strategies import STRATEGIES, strategy_meta, build
from core.ranges import pct as range_pct
from game.opponents import lineup_meta, DEFAULT_LINEUP
from game.simulator import run_session, run_comparison
from bot.runner import RUNNER
from bot.live_runner import LIVE, mask_email
from bot.lobby import SCOUT
from bot import adapter as adapter_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

app = FastAPI(title="Poker Patio Bot Control", version="1.0")

SIM = {"job": None, "status": "idle", "progress": 0.0, "results": None,
       "error": None, "started": None, "params": {}, "stage": ""}
SIM_LOCK = threading.Lock()


class SimRequest(BaseModel):
    hands: int = 500
    seed: int | None = None
    iters: int = 45
    strategies: list[str] | None = None
    bb: float = 1.0


class BotRequest(BaseModel):
    strategy: str | None = None
    hands_per_min: float | None = None
    seed: int | None = None
    reset: bool = False


class RateRequest(BaseModel):
    hands_per_min: float


class StrategyRequest(BaseModel):
    strategy: str


class LiveConnectRequest(BaseModel):
    email: str = ""
    password: str = ""
    mode: str = "singleplayer"        # singleplayer | public
    username: str = "bot"
    table: str = ""
    room_id: str = ""
    buyin: str = "avg"
    remember: bool = True
    difficulty: str = "easy"
    strategy: str = "optimal"
    dry_run: bool = True
    stop_loss: float = 0.0
    max_hands: int = 0
    opp_pct: float = 55.0
    action_delay: float = 0.7
    headless: bool = True


# --------------------------------------------------------------------- meta
@app.get("/api/meta")
def meta():
    cfg = adapter_mod.load_config()
    return {
        "strategies": strategy_meta(),
        "archetypes": lineup_meta(),
        "default_lineup": DEFAULT_LINEUP,
        "mdf_table": [{"bet_frac": k, "mdf": v} for k, v in MDF_TABLE.items()],
        "adapter": adapter_mod.adapter_report(cfg)["status"],
        "limits": {"max_hands": 5000, "min_hands": 50},
        "docs": {
            "pot_odds": "call / (pot + call + call)",
            "alpha": "bet / (pot + bet)",
            "mdf": "pot / (pot + bet) = 1 - alpha",
            "spr": "effective stack / pot",
            "ev_call": "equity*(pot+call) - call",
        },
    }


@app.get("/api/rangegrid")
def range_grid(strategy: str = "optimal", seat: str = "BTN", kind: str = "rfi"):
    if strategy not in STRATEGIES:
        raise HTTPException(404, "unknown strategy")
    pol = build(strategy, seed=1)
    labels = pol._rfi(seat) if kind == "rfi" else pol._defend(seat)
    grid = []
    for i, hi in enumerate(reversed(RANKS)):
        row = []
        for j, lo in enumerate(reversed(RANKS)):
            if i == j:
                lab = hi * 2
            elif i < j:
                lab = hi + lo + "s"
            else:
                lab = lo + hi + "o"
            row.append({"label": lab, "in": lab in labels,
                        "combos": class_combos(lab)})
        grid.append(row)
    return {"strategy": strategy, "seat": seat, "kind": kind,
            "width_pct": round(range_pct(labels), 1), "grid": grid}


# --------------------------------------------------------------- simulation
def _sim_worker(key: str, hands: int, seed: int, iters: int, bb: float):
    m = run_session(key, hands=hands, seed=seed, iters=iters, bb=bb)
    return key, m.summary()


def _run_sim_job(params: dict):
    try:
        keys = params.get("strategies") or ["safe", "optimal", "risky"]
        hands = int(params["hands"])
        seed = params.get("seed")
        seed = int(seed) if seed is not None else int(time.time()) % 100000
        iters = int(params.get("iters", 45))
        bb = float(params.get("bb", 1.0))
        with SIM_LOCK:
            SIM.update(status="running", progress=0.0, results={}, error=None,
                       started=time.time(), params=params, stage="dealing")
        workers = min(len(keys), os.cpu_count() or 2, 4)
        done = 0
        with cf.ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_sim_worker, k, hands, seed + i * 977, iters, bb): k
                    for i, k in enumerate(keys)}
            for fut in cf.as_completed(futs):
                key, summary = fut.result()
                done += 1
                with SIM_LOCK:
                    SIM["results"][key] = summary
                    SIM["progress"] = done / len(keys)
                    SIM["stage"] = f"finished {key}"
        with SIM_LOCK:
            SIM["status"] = "done"
            SIM["progress"] = 1.0
            SIM["stage"] = "complete"
            SIM["elapsed"] = round(time.time() - SIM["started"], 1)
    except Exception as e:
        with SIM_LOCK:
            SIM["status"] = "error"
            SIM["error"] = f"{type(e).__name__}: {e}"
            SIM["trace"] = traceback.format_exc()[-1200:]


@app.post("/api/sim/start")
def sim_start(req: SimRequest):
    with SIM_LOCK:
        if SIM["status"] == "running":
            raise HTTPException(409, "a simulation is already running")
    params = req.model_dump()
    params["hands"] = max(50, min(5000, int(req.hands)))
    t = threading.Thread(target=_run_sim_job, args=(params,), daemon=True)
    t.start()
    return {"ok": True, "params": params}


@app.get("/api/sim/status")
def sim_status():
    with SIM_LOCK:
        out = {k: SIM[k] for k in ("status", "progress", "results", "error",
                                   "started", "params", "stage")}
        if SIM["started"] and SIM["status"] == "running":
            out["elapsed"] = round(time.time() - SIM["started"], 1)
        out["elapsed"] = out.get("elapsed") or SIM.get("elapsed")
    return out


@app.post("/api/sim/stop")
def sim_stop():
    with SIM_LOCK:
        SIM["status"] = "idle"
        SIM["progress"] = 0.0
    return {"ok": True}


# -------------------------------------------------------------- bot control
@app.get("/api/bot/state")
def bot_state():
    return RUNNER.state()


@app.post("/api/bot/start")
def bot_start(req: BotRequest):
    return RUNNER.start(strategy=req.strategy, hpm=req.hands_per_min,
                        seed=req.seed, reset=req.reset)


@app.post("/api/bot/stop")
def bot_stop():
    return RUNNER.stop()


@app.post("/api/bot/pause")
def bot_pause():
    return RUNNER.pause()


@app.post("/api/bot/resume")
def bot_resume():
    return RUNNER.resume()


@app.post("/api/bot/strategy")
def bot_strategy(req: StrategyRequest):
    if req.strategy not in STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    return RUNNER.set_strategy(req.strategy)


@app.post("/api/bot/rate")
def bot_rate(req: RateRequest):
    return RUNNER.set_rate(req.hands_per_min)


@app.get("/api/stream")
async def stream(request: Request):
    async def gen():
        last = None
        while True:
            if await request.is_disconnected():
                break
            s = RUNNER.state()
            payload = json.dumps({"bot": s, "sim": sim_status(), "live": LIVE.state()},
                                 default=str)
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            await asyncio.sleep(0.6)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ live site bot
@app.post("/api/live/connect")
def live_connect(req: LiveConnectRequest):
    if not LIVE.state()["running"]:
        LIVE.start(
            email=req.email.strip(), password=req.password,
            mode=req.mode, username=req.username.strip() or "bot",
            table=req.table.strip(), room_id=req.room_id.strip(),
            difficulty=req.difficulty, strategy=req.strategy,
            dry_run=req.dry_run, stop_loss=req.stop_loss,
            max_hands=req.max_hands, opp_pct=req.opp_pct,
            action_delay=req.action_delay, remember=req.remember,
            buyin=req.buyin, headless=req.headless,
        )
    return LIVE.state()


@app.post("/api/live/disconnect")
def live_disconnect():
    return LIVE.stop()


@app.post("/api/live/pause")
def live_pause():
    return LIVE.pause()


@app.post("/api/live/resume")
def live_resume():
    return LIVE.resume()


@app.post("/api/live/strategy")
def live_strategy(req: StrategyRequest):
    if req.strategy not in STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    return LIVE.set_strategy(req.strategy)


@app.get("/api/live/state")
def live_state():
    return LIVE.state()


@app.get("/api/live/screenshot")
def live_screenshot():
    """Serve the freshest frame the runner captured.

    Playwright's sync API is bound to the thread that created it, so the server
    never touches the page: it asks the runner for a frame and serves the bytes.
    """
    if LIVE.site is None:
        raise HTTPException(409, "no live browser session")
    LIVE.request_shot()
    deadline = time.time() + 3.5
    while time.time() < deadline:
        if LIVE.shot and time.time() - LIVE.shot_at < 3.0:
            return Response(content=LIVE.shot, media_type="image/png",
                            headers={"Cache-Control": "no-store"})
        time.sleep(0.15)
    if LIVE.shot:
        return Response(content=LIVE.shot, media_type="image/png",
                        headers={"Cache-Control": "no-store"})
    raise HTTPException(504, "no frame captured yet")


@app.get("/api/live/lobbies")
def live_lobbies(refresh: int = 0):
    """The site's own lobby table, scraped by a background browser thread."""
    snap = SCOUT.snapshot(force=bool(refresh), wait=25.0 if refresh else 0.0)
    return snap


@app.get("/api/live/credentials")
def live_credentials():
    return LIVE.vault.status()


@app.post("/api/live/logout")
def live_logout():
    return LIVE.logout()


@app.post("/api/live/forget")
def live_forget():
    return {"vault": LIVE.vault.clear()}


# ----------------------------------------------------------------- adapter
@app.get("/api/adapter")
def adapter_get():
    cfg = adapter_mod.load_config()
    return adapter_mod.adapter_report(cfg)


@app.post("/api/adapter")
async def adapter_set(request: Request):
    body = await request.json()
    cfg = adapter_mod.save_config(body)
    return adapter_mod.adapter_report(cfg)


@app.post("/api/adapter/test")
def adapter_test():
    cfg = adapter_mod.load_config()
    a = adapter_mod.get_adapter(cfg)
    return {"connect": a.connect(), "status": a.status()}


# -------------------------------------------------------------------- static
if os.path.isdir(WEB):
    app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(WEB, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>web/index.html missing</h1>", status_code=500)


@app.get("/health")
def health():
    return {"ok": True, "sim": SIM["status"], "bot": RUNNER.state()["running"]}
