"""Session simulator: plays N hands for a strategy and produces chart-ready metrics.

Everything the dashboard plots comes out of here, from real simulated hands —
no placeholders. Metrics are keyed by strategy so the UI can compare all three:

    bankroll        cumulative chips per hand (downsampled)
    won / lost      gross chips won vs lost
    net             won - lost
    win_rate        share of hands with a positive delta
    showdown        share of showdowns won
    drawdown        max peak-to-trough fall
    actions         fold/check/call/bet/raise/allin counts
    af              aggression factor (bets+raises)/calls
    by_position     net chips by position
    by_street       net chips by street where the hand ended
    by_category     net chips by hero's final hand category
    ev_capture      mean decision EV vs mean realised delta
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from core.strategies import STRATEGIES, build
from core.evaluator import category, CAT_NAMES
from .opponents import DEFAULT_LINEUP, make_policy
from .table import Table, Player

DEFAULT_STACK_BB = 100.0
REBUY_THRESHOLD_BB = 35.0
MAX_STACK_BB = 160.0   # rathole above this: ranges are solved for ~100bb


@dataclass
class SessionMetrics:
    strategy: str
    hands: int = 0
    net: float = 0.0
    won: float = 0.0
    lost: float = 0.0
    wins: int = 0
    showdowns: int = 0
    showdown_wins: int = 0
    fold_wins: int = 0
    bankroll: list = field(default_factory=list)
    deltas: list = field(default_factory=list)
    actions: dict = field(default_factory=lambda: {
        "fold": 0, "check": 0, "call": 0, "bet": 0, "raise": 0, "allin": 0})
    by_position: dict = field(default_factory=dict)
    by_city: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    ev_sum: float = 0.0
    ev_n: int = 0
    sum_sq: float = 0.0
    n_delta: int = 0
    rebuys: int = 0
    max_peak: float = 0.0
    max_drawdown: float = 0.0
    biggest_win: float = 0.0
    biggest_loss: float = 0.0
    elapsed: float = 0.0
    bb: float = 1.0
    hands_detail: list = field(default_factory=list)

    def _std(self) -> float:
        n = max(self.n_delta, 1)
        mean = self.net / n
        var = max(0.0, self.sum_sq / n - mean * mean)
        return var ** 0.5

    def summary(self) -> dict:
        bb = self.bb or 1.0
        wins = self.wins
        return {
            "strategy": self.strategy,
            "hands": self.hands,
            "net": round(self.net, 2),
            "net_bb": round(self.net / bb, 1),
            "bb_per_100": round(self.net / bb / max(self.hands, 1) * 100, 2),
            "won": round(self.won, 2),
            "lost": round(self.lost, 2),
            "won_bb": round(self.won / bb, 1),
            "lost_bb": round(self.lost / bb, 1),
            "win_rate_pct": round(wins / max(self.hands, 1) * 100, 1),
            "wins": wins,
            "showdowns": self.showdowns,
            "showdown_win_pct": round(self.showdown_wins / max(self.showdowns, 1) * 100, 1),
            "fold_win_pct": round(self.fold_wins / max(self.hands, 1) * 100, 1),
            "max_drawdown": round(self.max_drawdown, 2),
            "std_per_hand": round(self._std(), 2),
            "se_bb100": round(self._std() / max(self.n_delta, 1) ** 0.5 / bb * 100, 2),
            "ci95_bb100": round(1.96 * self._std() / max(self.n_delta, 1) ** 0.5 / bb * 100, 2),
            "profit_factor": round(self.won / max(self.lost, 1e-9), 2),
            "max_drawdown_bb": round(self.max_drawdown / bb, 1),
            "biggest_win": round(self.biggest_win, 2),
            "biggest_loss": round(self.biggest_loss, 2),
            "actions": self.actions,
            "aggression_factor": round((self.actions["bet"] + self.actions["raise"]) /
                                       max(self.actions["call"], 1), 2),
            "by_position": {k: round(v, 2) for k, v in sorted(self.by_position.items())},
            "by_category": {k: round(v, 2) for k, v in
                            sorted(self.by_category.items(), key=lambda kv: -kv[1])},
            "ev_capture": round(self.ev_sum / max(self.ev_n, 1), 3),
            "rebuys": self.rebuys,
            "elapsed_s": round(self.elapsed, 2),
            "hands_per_s": round(self.hands / max(self.elapsed, 1e-9), 1),
            "bankroll": self.bankroll,
            "deltas": self.deltas[-300:],
        }


def _downsample(xs: list, target: int = 240) -> list:
    if len(xs) <= target:
        return [round(x, 2) for x in xs]
    step = len(xs) / target
    return [round(xs[min(len(xs) - 1, int(i * step))], 2) for i in range(target)]


def run_session(strategy_key: str, hands: int = 400, seed: int | None = None,
                stack_bb: float = DEFAULT_STACK_BB, bb: float = 1.0,
                seats: int = 6, lineup: list[str] | None = None,
                iters: int = 60, progress=None, keep_detail: int = 60) -> SessionMetrics:
    seed = seed if seed is not None else random.randrange(1 << 30)
    rng = random.Random(seed)
    lineup = lineup or DEFAULT_LINEUP
    hero_policy = build(strategy_key, seed=seed + 7)
    hero_policy.iters = iters
    hero_policy.label = STRATEGIES[strategy_key].label

    players = [Player(seat=0, name="Hero", stack=stack_bb * bb, style=strategy_key,
                      is_hero=True, policy=hero_policy)]
    for i in range(1, seats):
        arch = lineup[(i - 1) % len(lineup)]
        players.append(Player(seat=i, name=arch.capitalize(), stack=stack_bb * bb,
                              style=arch, is_hero=False,
                              policy=make_policy(arch, seed=seed + 100 + i)))

    table = Table(players, big_blind=bb, button=rng.randrange(seats), rng=rng)
    m = SessionMetrics(strategy=strategy_key, bb=bb)
    cum = 0.0
    peak = 0.0
    t0 = time.perf_counter()
    hero = players[0]

    for h in range(hands):
        res = table.play_hand()
        delta = res.hero_delta
        m.hands += 1
        m.deltas.append(round(delta, 2))
        m.sum_sq += delta * delta
        m.n_delta += 1
        cum += delta
        m.bankroll.append(round(cum, 2))
        peak = max(peak, cum)
        m.max_peak = peak
        m.max_drawdown = max(m.max_drawdown, peak - cum)
        m.net = cum
        if delta > 0:
            m.won += delta
            m.wins += 1
            m.biggest_win = max(m.biggest_win, delta)
        elif delta < 0:
            m.lost += -delta
            m.biggest_loss = min(m.biggest_loss, delta)

        if res.showdown and res.hero_in_hand:
            m.showdowns += 1
            if res.hero_won:
                m.showdown_wins += 1
        elif res.hero_won:
            m.fold_wins += 1

        pos = res.hero_position
        m.by_position[pos] = m.by_position.get(pos, 0.0) + delta
        ended = res.all_actions[-1]["street"] if res.all_actions else "preflop"
        m.by_city[ended] = m.by_city.get(ended, 0.0) + delta

        if res.hero_hole and res.board:
            from core.evaluator import evaluate
            cat = category(evaluate(list(res.hero_hole) + list(res.board)))
            name = CAT_NAMES[cat]
        elif res.hero_hole:
            name = "No showdown"
        else:
            name = "Uncontested"
        m.by_category[name] = m.by_category.get(name, 0.0) + delta

        for a in res.hero_actions:
            act = a["action"]
            if act in m.actions:
                m.actions[act] += 1
            elif act in ("allin",):
                m.actions["allin"] += 1
            dec = a.get("decision") or {}
            if dec.get("ev") is not None:
                m.ev_sum += float(dec["ev"])
                m.ev_n += 1

        # rebuy if the hero is short (cash-game style)
        if hero.stack < REBUY_THRESHOLD_BB * bb:
            hero.stack = stack_bb * bb
            m.rebuys += 1
        # keep the table in the ~100bb regime the ranges were designed for:
        # short stacks rebuy, deep stacks rathole back to 100bb
        for p in players[1:]:
            if p.stack < 20 * bb:
                p.stack = stack_bb * bb
            elif p.stack > MAX_STACK_BB * bb:
                p.stack = stack_bb * bb
        if hero.stack > MAX_STACK_BB * bb:
            hero.stack = stack_bb * bb

        table.button = (table.button + 1) % seats
        if progress and h % max(1, hands // 20) == 0:
            progress(h / hands)

    m.elapsed = time.perf_counter() - t0
    m.bankroll = _downsample(m.bankroll)
    m.deltas = _downsample(m.deltas, 200)
    return m


def run_comparison(hands: int = 300, seed: int | None = None, bb: float = 1.0,
                   iters: int = 60, progress=None) -> dict:
    seed = seed if seed is not None else random.randrange(1 << 30)
    out = {}
    for i, key in enumerate(("safe", "optimal", "risky")):
        out[key] = run_session(key, hands=hands, seed=seed + i * 31, bb=bb,
                               iters=iters,
                               progress=(lambda f, k=key: progress((i + f) / 3, k))
                               if progress else None).summary()
    return out
