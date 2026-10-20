"""Equity engine: exact preflop table + postflop Monte Carlo."""
from __future__ import annotations

import json
import os
import random
from functools import lru_cache

from .cards import FULL_DECK, hand_class, rank_of, suit_of
from .evaluator import evaluate

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TABLE_PATH = os.path.join(DATA, "preflop_equity.json")

_TABLE: dict[str, dict] | None = None


def load_preflop_table(force: bool = False) -> dict:
    global _TABLE
    if _TABLE is not None and not force:
        return _TABLE
    if os.path.exists(TABLE_PATH):
        with open(TABLE_PATH) as f:
            _TABLE = json.load(f)
    else:
        _TABLE = {}
    return _TABLE


def equity_mc(hole, board, n_opps: int = 1, iters: int = 200,
              rng: random.Random | None = None) -> float:
    """Monte-Carlo equity for `hole` vs `n_opps` random hands, given `board`."""
    rng = rng or random.Random()
    dead = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in dead]
    need_board = 5 - len(board)
    base_board = list(board)
    h0, h1 = hole
    total = 0.0
    for _ in range(iters):
        s = rng.sample(deck, need_board + 2 * n_opps)
        full = base_board + s[:need_board]
        mine = evaluate(full + [h0, h1])
        idx = need_board
        opp = []
        for _o in range(n_opps):
            opp.append(evaluate(full + [s[idx], s[idx + 1]]))
            idx += 2
        best = max(opp)
        if mine > best:
            total += 1.0
        elif mine == best:
            tied = 1 + sum(1 for v in opp if v == mine)
            total += 1.0 / tied
    return total / iters


def equity_mc_fast(hole, board, n_opps: int = 1, iters: int = 60,
                   rng: random.Random | None = None) -> float:
    """Cheaper variant used inside batch simulation."""
    return equity_mc(hole, board, n_opps=n_opps, iters=iters, rng=rng)


def preflop_equity(hole, n_opps: int = 1) -> float:
    """Preflop equity vs `n_opps` random hands, from the exact 169-class table.

    Entries are keyed n1..n5 (one to five opponents). Values are measured by
    Monte-Carlo per hand class, so AA is ~85% heads-up and ~49% five-way —
    the falloff is real, not an approximation.
    """
    table = load_preflop_table()
    label = hand_class(hole[0], hole[1])
    entry = table.get(label)
    n = max(1, min(5, int(n_opps)))
    if entry is not None:
        val = entry.get(f"n{n}")
        if val is not None:
            return val
        if n == 1 and "hu" in entry:
            return entry["hu"]
    return equity_mc(hole, [], n_opps=n, iters=400)


def build_table(iters: int = 1500, seed: int = 11) -> dict:
    """Compute the 169-class equity table for 1..5 opponents (slow, run once)."""
    from .ranges import _combos_for
    from .cards import ALL_CLASSES
    rng = random.Random(seed)
    out = {}
    for label in ALL_CLASSES:
        combos = _combos_for(label, set())
        c1, c2 = combos[0]
        row = {}
        for n in range(1, 6):
            row[f"n{n}"] = round(equity_mc((c1, c2), [], n_opps=n,
                                           iters=iters, rng=rng), 5)
        row["hu"] = row["n1"]
        out[label] = row
    os.makedirs(DATA, exist_ok=True)
    with open(TABLE_PATH, "w") as f:
        json.dump(out, f, indent=0, sort_keys=True)
    return out


# ------------------------------------------------------- range-aware equity
from functools import lru_cache as _lru

_CLASS_COMBOS: dict[str, tuple] = None
_CLASS_RANK: dict[str, int] = None


def _init_class_index():
    global _CLASS_COMBOS, _CLASS_RANK
    if _CLASS_COMBOS is not None:
        return
    from .ranges import _combos_for, _PLAY_ORDER
    _CLASS_COMBOS = {lab: tuple(_combos_for(lab, set())) for lab in _PLAY_ORDER}
    _CLASS_RANK = {lab: i for i, lab in enumerate(_PLAY_ORDER)}


@_lru(maxsize=256)
def _range_pool(pct: int) -> tuple:
    """Combos for the top `pct`% of hands by playability."""
    _init_class_index()
    from .ranges import _PLAY_ORDER
    n = max(4, min(169, int(round(pct / 100.0 * 169))))
    out = []
    for lab in _PLAY_ORDER[:n]:
        out.extend(_CLASS_COMBOS[lab])
    return tuple(out)


def equity_vs_ranges(hole, board, opp_pcts, iters: int = 120,
                     rng: random.Random | None = None) -> float:
    """Equity vs opponents whose preflop range is the top `pct`% of hands.

    This is the honest model: calling stations get a near-random range (60-70%),
    nits get the top 10-15%, and postflop action narrows both. Equity vs a
    random hand is wrong by 10+ points in exactly the spots that decide money.
    """
    rng = rng or random.Random()
    pcts = tuple(max(3, min(100, int(round(p)))) for p in opp_pcts) or (100,)
    pools = [_range_pool(p) for p in pcts]
    dead = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in dead]
    need = 5 - len(board)
    base = list(board)
    h0, h1 = hole
    total = 0.0
    for _ in range(iters):
        s = rng.sample(deck, need)
        full = base + s
        used = dead | set(s)
        mine = evaluate(full + [h0, h1])
        best = -1
        opp_scores = []
        for pool in pools:
            c1 = c2 = -1
            for _try in range(10):
                a, b = rng.choice(pool)
                if a not in used and b not in used:
                    c1, c2 = a, b
                    break
            if c1 < 0:
                pick = rng.sample([c for c in deck if c not in used], 2)
                c1, c2 = pick
            used.add(c1)
            used.add(c2)
            opp_scores.append(evaluate(full + [c1, c2]))
        best = max(opp_scores)
        if mine > best:
            total += 1.0
        elif mine == best:
            total += 1.0 / (1 + sum(1 for v in opp_scores if v == mine))
    return total / iters


def class_percentile(label: str) -> float:
    """Where a hand class sits in the playability ordering, as a percentage."""
    _init_class_index()
    return (_CLASS_RANK.get(label, 84) + 1) / 169.0 * 100.0


# ---------------------------------------------------------------- board texture
_WET_RANKS = {14, 13, 12, 11, 10}


def board_texture(board) -> str:
    """Classify flop/turn/river texture as dry / medium / wet."""
    if len(board) < 3:
        return "medium"
    suits = [suit_of(c) for c in board]
    ranks = sorted((rank_of(c) for c in board), reverse=True)
    suited_pairs = max(suits.count(s) for s in set(suits))
    gaps = [ranks[i] - ranks[i + 1] for i in range(len(ranks) - 1)]
    connected = any(g <= 2 for g in gaps)
    broadway = sum(1 for r in ranks if r in _WET_RANKS)
    score = 0
    if suited_pairs >= 2:
        score += 1
    if connected:
        score += 1
    if broadway >= 2:
        score += 1
    if ranks[0] - ranks[-1] <= 4 and len(ranks) >= 3:
        score += 1
    if score >= 3:
        return "wet"
    if score <= 1:
        return "dry"
    return "medium"


def draw_equity(hole, board) -> float:
    """Rough extra equity from a draw (used to justify semi-bluffs)."""
    if len(board) < 3 or len(board) >= 5:
        return 0.0
    suits = [s for s in (suit_of(c) for c in list(hole) + list(board))]
    ranks = sorted({rank_of(c) for c in list(hole) + list(board)})

    bonus = 0.0
    # flush draw
    for s in set(suits):
        n = suits.count(s)
        if n == 4:
            bonus += 0.18 if len(board) == 3 else 0.19
            break
    # open-ended / gutshot straight draw
    best = 0
    for start in range(2, 11):
        window = set(range(start, start + 5))
        have = len(window & set(ranks))
        if have == 4:
            missing = list(window - set(ranks))[0]
            outs = 8 if (missing == start or missing == start + 4) else 4
            best = max(best, outs)
    if best:
        bonus += 0.16 if best >= 8 else 0.09
    # overcards
    if len(board) == 3 and all(rank_of(h) > max(rank_of(b) for b in board) for h in hole):
        bonus += 0.06
    return min(bonus, 0.42)
