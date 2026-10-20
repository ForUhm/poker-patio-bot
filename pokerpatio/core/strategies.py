"""Three decision policies: RISKY, SAFE, OPTIMAL.

Each policy consumes a `Spot` and returns a `Decision` with the maths that
produced it (equity, pot odds, MDF, EV) so the dashboard can show *why* the bot
acted, not just what it did.

Common frame (all three):
    equity            = Monte-Carlo / cached preflop equity
    required_equity   = pot_odds(pot, to_call)
    mdf               = pot / (pot + bet)          -> range defence floor
    alpha             = bet / (pot + bet)          -> bluff break-even fold %
    ev_call           = eq*(pot+call) - call
They differ in: range width, bluff frequency, calling margin, sizing bias,
stack-commitment rules and how much they trust thin equity.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict

from .cards import hand_class, rank_of, suit_of, card_str
from .equity import (equity_mc, preflop_equity, board_texture, draw_equity,
                     load_preflop_table, equity_vs_ranges, class_percentile)
from .evaluator import evaluate, category, describe_hand
from .mathx import (pot_odds, alpha, mdf, ev_call, spr, sizing_by_texture,
                    equity_realization, spr_commitment_threshold, clamp,
                    value_bluff_ratio)
from .ranges import (RFI, DEFEND, SHOVE, THREEBET, THREEBET_VALUE,
                     THREEBET_BLUFF, rfi_for, defend_for, pct)


# --------------------------------------------------------------------- models
@dataclass
class Spot:
    hole: tuple
    board: tuple = ()
    street: str = "preflop"
    pot: float = 1.5
    to_call: float = 0.0
    my_stack: float = 100.0
    eff_stack: float = 100.0
    position: str = "IP"                  # 'IP' | 'OOP'
    seat: str = "BTN"                     # UTG/HJ/CO/BTN/SB/BB
    n_opponents: int = 1
    raises_faced: int = 0                 # raises already in front of me
    limpers: int = 0
    big_blind: float = 1.0
    can_check: bool = False
    my_invested: float = 0.0             # my chips already in this street
    bet_level: float = 0.0               # highest amount contributed this street
    min_raise_to: float = 0.0
    max_raise_to: float = 0.0
    opponent: dict = field(default_factory=dict)
    opp_pcts: tuple = ()                 # estimated range width per opponent (%)
    opener: str = ""
    i_am_aggressor: bool = False
    iters: int = 140
    seed: int | None = None


@dataclass
class Decision:
    action: str            # fold | check | call | bet | raise | allin
    amount: float = 0.0    # chips ADDED now by this action
    equity: float = 0.0
    required_equity: float = 0.0
    ev: float = 0.0
    rationale: str = ""
    tags: list = field(default_factory=list)
    confidence: float = 0.0
    sizing_frac: float = 0.0
    hand_label: str = ""
    strength: int = 0
    mdf: float = 0.0
    alpha: float = 0.0
    spr: float = 0.0

    def to_dict(self):
        d = asdict(self)
        d["amount"] = round(self.amount, 2)
        d["equity"] = round(self.equity, 4)
        d["required_equity"] = round(self.required_equity, 4)
        d["ev"] = round(self.ev, 2)
        d["mdf"] = round(self.mdf, 3)
        d["alpha"] = round(self.alpha, 3)
        d["spr"] = round(self.spr, 2)
        d["confidence"] = round(self.confidence, 2)
        return d


# ------------------------------------------------------------------ base policy
class BaseStrategy:
    key = "base"
    label = "Base"
    loosen = 0.0            # percentage points added to every range
    bluff_freq = 0.0        # extra bluff frequency over alpha
    call_margin = 0.02      # equity cushion required over pot odds
    sizing_bias = 1.0       # multiplier on standard bet sizing
    value_threshold = 0.62  # equity vs field needed to bet for value
    raise_threshold = 0.70  # equity needed to raise for value
    max_stack_commit = 1.0  # fraction of stack we will risk without the nuts
    open_size_bb = 2.5
    threebet_mult = 3.0
    trust_draws = 0.5       # how much draw equity we count as real
    notes = ""

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self._equity_cache: dict = {}

    # ---------------------------------------------------------------- ranges
    def _rfi(self, seat: str):
        return rfi_for(seat, self.loosen)

    def _defend(self, opener: str):
        return defend_for(opener or "BTN", self.loosen)

    def _threebet_range(self, spot: Spot):
        key = "BLIND" if spot.seat in ("SB", "BB") else (
            "IP" if spot.position == "IP" else "OOP")
        base = set(THREEBET[key])
        if self.loosen > 0:
            base |= THREEBET_BLUFF
            base = set(sorted(base))
        if self.loosen < 0:
            base = set(THREEBET_VALUE) | {"KQs", "A5s"}
        return base

    # ---------------------------------------------------------------- equity
    def equity(self, spot: Spot) -> float:
        hole, board = tuple(spot.hole), tuple(spot.board)
        pcts = tuple(spot.opp_pcts) if spot.opp_pcts else ()
        key = (hole, board, spot.n_opponents, pcts)
        if key in self._equity_cache:
            return self._equity_cache[key]
        rng = random.Random(spot.seed) if spot.seed is not None else self.rng
        if pcts:
            iters = spot.iters if board else max(spot.iters, 80)
            eq = equity_vs_ranges(hole, board, pcts, iters=iters, rng=rng)
        elif not board:
            eq = preflop_equity(hole, spot.n_opponents)
        else:
            eq = equity_mc(hole, board, n_opps=spot.n_opponents,
                           iters=spot.iters, rng=rng)
        ip = spot.position == "IP"
        suited = suit_of(hole[0]) == suit_of(hole[1])
        connected = abs(rank_of(hole[0]) - rank_of(hole[1])) <= 2
        eq *= equity_realization(ip, suited, connected, spot.n_opponents > 1)
        eq = clamp(eq, 0.01, 0.99)
        if len(self._equity_cache) > 4000:
            self._equity_cache.clear()
        self._equity_cache[key] = eq
        return eq

    # ---------------------------------------------------------------- helpers
    def _strength(self, spot: Spot) -> int:
        if not spot.board:
            return -1
        return category(evaluate(list(spot.hole) + list(spot.board)))

    def _hand_label(self, spot: Spot) -> str:
        if not spot.board:
            return hand_class(*spot.hole)
        return describe_hand(list(spot.hole) + list(spot.board))

    def _draw(self, spot: Spot) -> float:
        if not spot.board or len(spot.board) >= 5:
            return 0.0
        d = draw_equity(spot.hole, spot.board)
        # scale by how likely we are to get paid / see the next card
        streets_left = 2 if len(spot.board) == 3 else 1
        return d * (1.0 if streets_left == 2 else 0.62) * self.trust_draws

    def _bet_size(self, spot: Spot) -> float:
        tex = board_texture(spot.board) if spot.board else "medium"
        frac = sizing_by_texture(tex, spot.street, self.sizing_bias)
        return max(spot.big_blind, round(spot.pot * frac, 2))

    def _raise_to(self, spot: Spot) -> float:
        """Total amount to raise to (absolute chips committed this street)."""
        lo, hi = spot.min_raise_to, spot.max_raise_to
        if hi <= lo:
            return hi if hi > 0 else lo
        if spot.street == "preflop":
            base = spot.bet_level * self.threebet_mult
            if spot.limpers:
                base += spot.limpers * spot.big_blind
            want = max(base, lo)
        else:
            # raise to ~3x their bet, or a pot-sized raise
            base = spot.bet_level + spot.pot * 0.75
            want = max(base, lo)
        return clamp(want, lo, hi)

    def _fold_reason(self, spot, eq, req) -> str:
        return (f"Equity {eq*100:.1f}% < required {req*100:.1f}% "
                f"(pot odds {spot.pot + spot.to_call:.1f}:{spot.to_call:.1f}) — fold.")

    # ------------------------------------------------------------- preflop
    def decide_preflop(self, spot: Spot) -> Decision:
        label = hand_class(*spot.hole)
        eq = self.equity(spot)
        bb = spot.big_blind
        eff_bb = spot.eff_stack / bb if bb else 100
        d = Decision(action="fold", equity=eq, hand_label=label,
                     strength=-1, spr=0.0)
        d.hand_label = label

        # short-stack push/fold
        if eff_bb <= 15:
            shove = set(SHOVE.get(spot.seat, set()))
            shove = self._adjust_short(shove)
            if label in shove:
                amt = min(spot.my_stack, spot.max_raise_to or spot.my_stack)
                d.action = "allin"
                d.amount = amt
                d.tags = ["push-fold", "short-stack"]
                d.rationale = (f"{eff_bb:.0f}bb stack -> push/fold chart: {label} "
                               f"is a shove ({pct(shove):.0f}% range). "
                               f"Equity {eq*100:.1f}%.")
                d.confidence = 0.8
                d.ev = eq * (spot.pot + 2 * amt) - amt
                return d
            d.rationale = (f"{eff_bb:.0f}bb stack, {label} not in the "
                           f"{pct(shove):.0f}% shove range -> fold.")
            return d

        facing_raise = spot.raises_faced > 0

        # ---- facing a raise: 3-bet / call / fold
        if facing_raise:
            tb = self._threebet_range(spot)
            req = pot_odds(spot.pot, spot.to_call)
            d.required_equity = req
            if label in tb:
                raise_to = self._raise_to(spot)
                d.action = "raise"
                d.amount = max(0.0, raise_to - spot.my_invested)
                d.sizing_frac = round(raise_to / max(spot.pot, 1e-9), 2)
                kind = "value 3-bet" if label in THREEBET_VALUE else "light 3-bet"
                d.tags = ["3bet", kind.split()[0]]
                d.rationale = (f"{label} is in the {kind} range "
                               f"({pct(tb):.0f}% of hands). Raising to "
                               f"{raise_to:.1f} ({raise_to/bb:.1f}bb) with "
                               f"{eq*100:.1f}% equity.")
                d.confidence = 0.75
                d.ev = eq * (spot.pot + 2 * d.amount) - d.amount
                return d
            defend = self._defend(spot.opener or "BTN")
            if label in defend and eq >= req - 0.03:
                d.action = "call"
                d.amount = spot.to_call
                d.required_equity = req
                d.ev = ev_call(spot.pot, spot.to_call, eq)
                d.tags = ["defend", "flat"]
                d.rationale = (f"{label} is inside the {pct(defend):.0f}% defend "
                               f"range vs {spot.opener or 'open'}; equity "
                               f"{eq*100:.1f}% vs {req*100:.1f}% needed.")
                d.confidence = 0.6
                return d
            # speculative call (risky only, driven by loosen + bluff params)
            if self.loosen > 0 and eq >= req * 0.85 and spot.to_call <= 4 * bb:
                d.action = "call"
                d.amount = spot.to_call
                d.required_equity = req
                d.ev = ev_call(spot.pot, spot.to_call, eq)
                d.tags = ["speculative", "loose-call"]
                d.rationale = (f"{label} outside chart, but equity {eq*100:.1f}% "
                               f"near the {req*100:.1f}% price and implied odds "
                               f"are live -> loose call.")
                d.confidence = 0.4
                return d
            d.rationale = (f"{label} not in {pct(defend):.0f}% defend range and "
                           f"equity {eq*100:.1f}% < {req*100:.1f}% price.")
            return d

        # ---- unopened / limped pot
        open_r = self._rfi(spot.seat)
        if label in open_r:
            raise_to = max(spot.min_raise_to, round(bb * self.open_size_bb, 2))
            if spot.seat == "SB":
                raise_to = max(raise_to, round(bb * (self.open_size_bb + 0.5), 2))
            if spot.limpers:
                raise_to += spot.limpers * bb
            raise_to = clamp(raise_to, max(spot.min_raise_to, bb), spot.max_raise_to or raise_to)
            d.action = "raise"
            d.amount = max(0.0, raise_to - spot.my_invested)
            d.sizing_frac = round(raise_to / bb, 2)
            d.tags = ["open-raise", "rfi"]
            d.rationale = (f"{label} in {spot.seat} RFI ({pct(open_r):.0f}% range) "
                           f"-> open to {raise_to:.1f} ({raise_to/bb:.1f}bb). "
                           f"Equity {eq*100:.1f}%.")
            d.confidence = 0.7
            d.ev = eq * (spot.pot + 2 * d.amount) - d.amount
            return d

        # BB checking a limped pot is free
        if spot.can_check:
            d.action = "check"
            d.amount = 0.0
            d.tags = ["check"]
            d.rationale = f"{label} not worth opening; checking the option."
            d.confidence = 0.5
            return d

        # risky players steal with a wider than chart range
        if self.loosen > 6 and self.rng.random() < 0.12 and spot.to_call <= bb:
            raise_to = max(spot.min_raise_to, round(bb * self.open_size_bb, 2))
            d.action = "raise"
            d.amount = max(0.0, raise_to - spot.my_invested)
            d.tags = ["steal", "off-chart"]
            d.rationale = (f"Off-chart steal with {label} from {spot.seat} "
                           f"(aggression parameter).")
            d.confidence = 0.35
            return d

        d.rationale = f"{label} folds — outside the {pct(open_r):.0f}% {spot.seat} opening range."
        return d

    def _adjust_short(self, shove: set[str]) -> set[str]:
        from .ranges import widen_to, narrow_to
        if self.loosen > 0:
            return widen_to(shove, pct(shove) + self.loosen)
        if self.loosen < 0:
            return narrow_to(shove, pct(shove) + self.loosen)
        return shove

    # ------------------------------------------------------------ postflop
    def decide_postflop(self, spot: Spot) -> Decision:
        eq = self.equity(spot)
        req = pot_odds(spot.pot, spot.to_call)
        strength = self._strength(spot)
        draw = self._draw(spot)
        tex = board_texture(spot.board)
        spr_val = spr(spot.pot, spot.eff_stack)
        d = Decision(action="fold", equity=eq, required_equity=req,
                     hand_label=self._hand_label(spot), strength=strength,
                     spr=spr_val, mdf=mdf(spot.pot, max(spot.to_call, 1e-9)),
                     alpha=alpha(spot.pot, max(spot.to_call, 1e-9)))

        total_eq = clamp(eq + draw, 0.01, 0.99)
        commit_cat = spr_commitment_threshold(spr_val)

        # ---------- no bet in front of us
        if spot.to_call <= 1e-9:
            value_thresh = self.value_threshold if spot.n_opponents == 1 else self.value_threshold + 0.05
            if total_eq >= value_thresh and strength >= 1:
                size = self._bet_size(spot)
                size = min(size, spot.my_stack)
                d.action = "bet"
                d.amount = size
                d.sizing_frac = round(size / max(spot.pot, 1e-9), 2)
                d.tags = ["value", tex]
                d.rationale = (f"{d.hand_label}: equity {total_eq*100:.1f}% "
                               f"clears the {value_thresh*100:.0f}% value threshold "
                               f"-> bet {size/max(spot.pot,1e-9):.0%} pot on a {tex} board "
                               f"(SPR {spr_val:.1f}).")
                d.confidence = clamp(0.45 + (total_eq - value_thresh) * 1.6, 0.4, 0.95)
                d.ev = total_eq * (spot.pot + 2 * size) - size
                return d
            if draw > 0.10 and self.bluff_freq >= 0.0 and spot.street != "river":
                size = self._bet_size(spot) * (0.85 if self.sizing_bias > 1 else 1.0)
                size = min(size, spot.my_stack)
                d.action = "bet"
                d.amount = size
                d.sizing_frac = round(size / max(spot.pot, 1e-9), 2)
                d.tags = ["semi-bluff", "draw"]
                d.rationale = (f"Semi-bluff: {d.hand_label} plus a draw worth "
                               f"{draw*100:.0f}% equity; betting {size/max(spot.pot,1e-9):.0%} "
                               f"pot to fold out better hands and build the pot.")
                d.confidence = 0.5
                d.ev = total_eq * (spot.pot + 2 * size) - size
                return d
            if spot.street in ("turn", "river") and self.bluff_freq > 0:
                probe = self.bluff_freq + (spot.opponent.get("fold_to_bet", 0.45) - 0.45)
                if self.rng.random() < clamp(probe, 0, 0.7):
                    size = min(self._bet_size(spot) * 0.8, spot.my_stack)
                    d.action = "bet"
                    d.amount = size
                    d.sizing_frac = round(size / max(spot.pot, 1e-9), 2)
                    d.tags = ["bluff", "fold-equity"]
                    a = alpha(spot.pot, size)
                    d.rationale = (f"Pure bluff: opponent folds "
                                   f"{spot.opponent.get('fold_to_bet', 0.45)*100:.0f}% "
                                   f"vs the {a*100:.0f}% break-even (alpha) needed.")
                    d.confidence = 0.35
                    d.ev = (spot.opponent.get("fold_to_bet", 0.45) * spot.pot
                            - (1 - spot.opponent.get("fold_to_bet", 0.45)) * size)
                    return d
            d.action = "check"
            d.tags = ["check", "pot-control"]
            d.rationale = (f"Equity {total_eq*100:.1f}% below the "
                           f"{value_thresh*100:.0f}% betting threshold — check "
                           f"and keep the pot small (SPR {spr_val:.1f}).")
            d.confidence = 0.5
            return d

        # ---------- facing a bet
        stack_risk = spot.to_call / max(spot.my_stack + spot.to_call, 1e-9)
        if total_eq >= self.raise_threshold and strength >= max(commit_cat - 2, 0) \
                and spot.max_raise_to > spot.to_call:
            raise_to = self._raise_to(spot)
            d.action = "raise"
            d.amount = max(0.0, raise_to - spot.my_invested)
            d.sizing_frac = round(raise_to / max(spot.pot, 1e-9), 2)
            d.tags = ["raise", "value"]
            d.rationale = (f"{d.hand_label} with {total_eq*100:.1f}% equity vs a "
                           f"{req*100:.1f}% price and SPR {spr_val:.1f} -> raise to "
                           f"{raise_to:.1f} for value.")
            d.confidence = 0.7
            d.ev = total_eq * (spot.pot + 2 * d.amount) - d.amount
            return d

        if total_eq >= req + self.call_margin * (1 + stack_risk):
            d.action = "call"
            d.amount = spot.to_call
            d.ev = ev_call(spot.pot, spot.to_call, total_eq)
            d.tags = ["call", "pot-odds"]
            gap = (total_eq - req) * 100
            d.rationale = (f"{d.hand_label}: {total_eq*100:.1f}% equity vs "
                           f"{req*100:.1f}% required (+{gap:.1f}pp), MDF floor "
                           f"{mdf(spot.pot, spot.to_call)*100:.0f}% -> call.")
            d.confidence = clamp(0.4 + gap / 25, 0.35, 0.9)
            return d

        # risky bluff-raise with blockers when the price is wrong
        if self.bluff_freq > 0.15 and spot.street != "flop" and draw > 0.10 \
                and self.rng.random() < self.bluff_freq * 0.5:
            raise_to = self._raise_to(spot)
            d.action = "raise"
            d.amount = max(0.0, raise_to - spot.my_invested)
            d.tags = ["bluff-raise", "draw"]
            d.rationale = (f"Equity {total_eq*100:.1f}% below the "
                           f"{req*100:.1f}% price, but the draw gives fold equity "
                           f"-> bluff-raise to {raise_to:.1f}.")
            d.confidence = 0.3
            return d

        d.action = "fold"
        d.amount = 0.0
        d.ev = 0.0
        d.tags = ["fold"]
        d.rationale = (f"{d.hand_label}: {total_eq*100:.1f}% equity vs "
                       f"{req*100:.1f}% required — fold, "
                       f"{(req-total_eq)*100:.1f}pp short.")
        d.confidence = clamp(0.4 + (req - total_eq) * 2, 0.4, 0.95)
        return d

    # ---------------------------------------------------------------- entry
    def decide(self, spot: Spot) -> Decision:
        d = (self.decide_preflop(spot) if spot.street == "preflop"
             else self.decide_postflop(spot))
        # fill in the range-math display fields for preflop decisions too
        if not d.mdf and spot.to_call > 0:
            d.mdf = mdf(spot.pot, spot.to_call)
            d.alpha = alpha(spot.pot, spot.to_call)
        d.spr = d.spr or spr(spot.pot, spot.eff_stack)
        if d.action == "raise" and d.amount >= spot.my_stack - 1e-9:
            d.action = "allin"
            d.amount = spot.my_stack
        if d.action == "bet" and d.amount >= spot.my_stack - 1e-9:
            d.action = "allin"
            d.amount = spot.my_stack
        d.equity = round(d.equity, 4)
        d.required_equity = round(d.required_equity, 4)
        return d


# --------------------------------------------------------------- the 3 profiles
class SafeStrategy(BaseStrategy):
    key = "safe"
    label = "Safe"
    loosen = -7.0
    bluff_freq = 0.0
    call_margin = 0.09
    sizing_bias = 0.72
    value_threshold = 0.68
    raise_threshold = 0.78
    max_stack_commit = 0.35
    open_size_bb = 2.2
    threebet_mult = 2.8
    trust_draws = 0.35
    notes = ("Tight, low-variance. Narrow ranges (-7pp), no bluffing, "
             "calls only with a 9pp equity cushion, small sizings for pot control, "
             "folds anything marginal.")


class OptimalStrategy(BaseStrategy):
    key = "optimal"
    label = "Optimal"
    loosen = 0.0
    bluff_freq = 0.10
    call_margin = 0.02
    sizing_bias = 1.0
    value_threshold = 0.62
    raise_threshold = 0.70
    max_stack_commit = 1.0
    open_size_bb = 2.5
    threebet_mult = 3.0
    trust_draws = 0.5
    notes = ("Solver-shaped baseline: published RFI/defend frequencies, pot-odds "
             "thresholds, MDF-aware defence, texture-based sizing, balanced "
             "value:bluff ratio by street.")


class RiskyStrategy(BaseStrategy):
    key = "risky"
    label = "Risky"
    loosen = 9.0
    bluff_freq = 0.28
    call_margin = -0.01
    sizing_bias = 1.35
    value_threshold = 0.55
    raise_threshold = 0.62
    max_stack_commit = 1.0
    open_size_bb = 3.0
    threebet_mult = 3.6
    trust_draws = 1.15
    notes = ("Loose-aggressive, high variance. Wide ranges (+9pp), light 3-bets, "
             "overbets, semi-bluff shoves on draws, thin value, calls off with "
             "implied odds. Wins big or busts.")


STRATEGIES = {s.key: s for s in (SafeStrategy, OptimalStrategy, RiskyStrategy)}


def build(key: str, seed: int | None = None) -> BaseStrategy:
    return STRATEGIES[key](seed=seed)


def strategy_meta() -> list[dict]:
    out = []
    for k, cls in STRATEGIES.items():
        inst = cls(seed=0)
        open_widths = {pos: round(pct(inst._rfi(pos)), 1) for pos in ("UTG", "HJ", "CO", "BTN", "SB")}
        defence = {pos: round(pct(inst._defend(pos)), 1) for pos in ("UTG", "CO", "BTN")}
        out.append({
            "key": k,
            "label": cls.label,
            "notes": cls.notes,
            "params": {
                "range_adjust_pp": cls.loosen,
                "bluff_freq": cls.bluff_freq,
                "call_margin": cls.call_margin,
                "sizing_bias": cls.sizing_bias,
                "value_threshold": cls.value_threshold,
                "raise_threshold": cls.raise_threshold,
                "open_size_bb": cls.open_size_bb,
            },
            "open_widths_pct": open_widths,
            "defend_widths_pct": defence,
        })
    return out
