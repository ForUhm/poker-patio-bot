"""Live bot runner: plays hands continuously on the local table, thread-safe state.

This is the object the dashboard controls: start/stop/pause, switch strategy,
change pace. It is deliberately decoupled from the transport — the server only
reads `state()` and pushes it over HTTP/SSE, and a real site adapter can replace
the table underneath without the UI changing.
"""
from __future__ import annotations

import random
import threading
import time

from core.cards import card_str
from core.strategies import STRATEGIES, build
from core.evaluator import evaluate, category, CAT_NAMES
from game.opponents import DEFAULT_LINEUP, make_policy, ARCHETYPES
from game.table import Table, Player

MAX_FEED = 60


class BotRunner:
    def __init__(self, bb: float = 1.0, stack_bb: float = 100.0, seats: int = 6):
        self.bb = bb
        self.stack_bb = stack_bb
        self.seats = seats
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._reset("optimal", 60, seed=None)

    # ------------------------------------------------------------------ setup
    def _reset(self, strategy: str, hpm: float, seed=None):
        self.strategy = strategy
        self.hpm = hpm
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.rng = random.Random(self.seed)
        self.table = self._build_table()
        self.hands = 0
        self.net = 0.0
        self.won = 0.0
        self.lost = 0.0
        self.wins = 0
        self.showdowns = 0
        self.showdown_wins = 0
        self.bankroll: list[float] = [0.0]
        self.actions = {"fold": 0, "check": 0, "call": 0, "bet": 0, "raise": 0, "allin": 0}
        self.feed: list[dict] = []
        self.last: dict | None = None
        self.started_at = None
        self.rebuys = 0
        self.errors = 0

    def _build_table(self) -> Table:
        hp = build(self.strategy, seed=self.seed + 5)
        hp.iters = 220
        players = [Player(0, "Hero", self.stack_bb * self.bb, self.strategy, True, hp)]
        for i in range(1, self.seats):
            arch = DEFAULT_LINEUP[(i - 1) % len(DEFAULT_LINEUP)]
            pol = make_policy(arch, seed=self.seed + 50 + i)
            pol.iters = 140
            players.append(Player(i, ARCHETYPES[arch]["label"].split(" ")[0],
                                  self.stack_bb * self.bb, arch, False, pol))
        return Table(players, big_blind=self.bb,
                     button=self.rng.randrange(self.seats), rng=self.rng)

    # ----------------------------------------------------------------- control
    def start(self, strategy: str | None = None, hpm: float | None = None,
              seed: int | None = None, reset: bool = False):
        with self._lock:
            if strategy and strategy != self.strategy:
                self._reset(strategy, hpm or self.hpm, seed=seed)
            elif reset or self._thread is None or not self._thread.is_alive():
                if self.hands == 0 or reset:
                    self._reset(strategy or self.strategy, hpm or self.hpm, seed=seed)
            if hpm:
                self.hpm = hpm
            self._stop.clear()
            self._pause.clear()
            if self.started_at is None:
                self.started_at = time.time()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, daemon=True,
                                                name="bot-runner")
                self._thread.start()
        return self.state()

    def pause(self):
        self._pause.set()
        return self.state()

    def resume(self):
        self._pause.clear()
        return self.state()

    def stop(self, keep_table: bool = True):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3.0)
        self._thread = None
        return self.state()

    def set_strategy(self, strategy: str):
        with self._lock:
            if strategy not in STRATEGIES:
                raise ValueError(f"unknown strategy {strategy}")
            was_running = self._thread is not None and self._thread.is_alive() \
                and not self._stop.is_set()
            self._reset(strategy, self.hpm, seed=None)
            if was_running:
                self.start()
        return self.state()

    def set_rate(self, hpm: float):
        with self._lock:
            self.hpm = max(1.0, min(600.0, float(hpm)))
        return self.state()

    # -------------------------------------------------------------------- loop
    def _loop(self):
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.1)
                continue
            t0 = time.perf_counter()
            try:
                self._step()
            except Exception as e:            # a bad hand must not kill the bot
                self.errors += 1
                self.last = {"error": f"{type(e).__name__}: {e}"}
                time.sleep(0.2)
            interval = 60.0 / max(self.hpm, 1.0)
            sleep = interval - (time.perf_counter() - t0)
            if sleep > 0:
                self._stop.wait(sleep)

    def _step(self):
        res = self.table.play_hand()
        with self._lock:
            self.hands += 1
            self.net += res.hero_delta
            if res.hero_delta > 0:
                self.won += res.hero_delta
                self.wins += 1
            elif res.hero_delta < 0:
                self.lost += -res.hero_delta
            for a in res.hero_actions:
                k = a.get("action")
                if k in self.actions:
                    self.actions[k] += 1
            if res.showdown and res.hero_in_hand:
                self.showdowns += 1
                if res.hero_won:
                    self.showdown_wins += 1
            self.bankroll.append(round(self.net, 2))
            if len(self.bankroll) > 1200:
                self.bankroll = self.bankroll[-1200:]

            hero = self.table._seat(0)
            if hero.stack < 35 * self.bb:
                hero.stack = self.stack_bb * self.bb
                self.rebuys += 1
            for p in self.table.players[1:]:
                if p.stack < 20 * self.bb or p.stack > 160 * self.bb:
                    p.stack = self.stack_bb * self.bb
            if hero.stack > 160 * self.bb:
                hero.stack = self.stack_bb * self.bb

            hero_acts = res.hero_actions
            last_dec = None
            for a in reversed(hero_acts):
                if a.get("decision"):
                    last_dec = {"street": a["street"], "action": a["action"],
                                "amount": a["amount"], "position": a["position"],
                                **{k: v for k, v in a["decision"].items() if k != "hand_label"},
                                "hand_label": a["decision"].get("hand_label", "")}
                    break

            self.last = {
                "hand_id": res.hand_id,
                "board": [card_str(c) for c in res.board],
                "hero_cards": [card_str(c) for c in res.hero_hole],
                "hero_position": res.hero_position,
                "hero_delta": round(res.hero_delta, 2),
                "pot": round(res.pot, 2),
                "showdown": res.showdown,
                "winners": res.winners,
                "hand_label": res.hand_label,
                "actions": [{k: a[k] for k in
                             ("street", "name", "position", "action", "amount", "note", "hero")}
                            for a in res.all_actions if a["action"] not in ("blind", "deal")],
                "decision": last_dec,
                "table": {
                    "seats": [p.to_dict() for p in self.table.players],
                    "pot": round(self.table.pot, 2),
                    "board": [card_str(c) for c in getattr(self.table, "board", [])],
                    "button": self.table.button,
                },
            }
            self.feed.insert(0, {
                "hand_id": res.hand_id,
                "pos": res.hero_position,
                "cards": " ".join(card_str(c) for c in res.hero_hole),
                "board": " ".join(card_str(c) for c in res.board),
                "delta": round(res.hero_delta, 2),
                "label": res.hand_label or ("fold-win" if not res.showdown else ""),
                "showdown": res.showdown,
            })
            del self.feed[MAX_FEED:]
            self.table.button = (self.table.button + 1) % self.seats

    # ------------------------------------------------------------------- state
    def state(self) -> dict:
        with self._lock:
            h = self.hands
            return {
                "running": bool(self._thread and self._thread.is_alive()
                                and not self._stop.is_set() and not self._pause.is_set()),
                "paused": self._pause.is_set(),
                "strategy": self.strategy,
                "strategy_label": STRATEGIES[self.strategy].label,
                "hands_per_min": self.hpm,
                "hands": h,
                "net": round(self.net, 2),
                "won": round(self.won, 2),
                "lost": round(self.lost, 2),
                "bb_per_100": round(self.net / self.bb / max(h, 1) * 100, 2),
                "win_rate_pct": round(self.wins / max(h, 1) * 100, 1),
                "showdowns": self.showdowns,
                "showdown_win_pct": round(self.showdown_wins / max(self.showdowns, 1) * 100, 1),
                "rebuys": self.rebuys,
                "actions": dict(self.actions),
                "aggression_factor": round((self.actions["bet"] + self.actions["raise"]) /
                                           max(self.actions["call"], 1), 2),
                "errors": self.errors,
                "bankroll": self.bankroll[-400:],
                "feed": self.feed[:30],
                "last": self.last,
                "elapsed_s": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "seed": self.seed,
            }


RUNNER = BotRunner()
