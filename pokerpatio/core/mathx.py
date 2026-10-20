"""Poker math: pot odds, EV, MDF, alpha, SPR, sizing, equity realisation.

All formulas follow the standard solver definitions:
  pot_odds (required equity to call) = call / (pot + call + call)
  alpha  (bluff break-even fold%)   = bet / (pot + bet)
  MDF    (defender continue floor)  = pot / (pot + bet) = 1 - alpha
"""
from __future__ import annotations

# MDF reference table straight from the theory (used by the UI + engine)
MDF_TABLE = {
    0.25: 0.80, 0.33: 0.75, 0.50: 0.667, 0.66: 0.60,
    0.75: 0.571, 1.00: 0.50, 1.50: 0.40, 2.00: 0.333, 3.00: 0.25,
}


def pot_odds(pot: float, call: float) -> float:
    """Equity needed to make calling break even."""
    if call <= 0:
        return 0.0
    return call / (pot + call + call)


def alpha(pot: float, bet: float) -> float:
    """Fold frequency a zero-equity bluff needs to break even."""
    if pot + bet <= 0:
        return 0.0
    return bet / (pot + bet)


def mdf(pot: float, bet: float) -> float:
    """Minimum fraction of range that must continue vs `bet` into `pot`."""
    if pot + bet <= 0:
        return 1.0
    return pot / (pot + bet)


def spr(pot: float, stack: float) -> float:
    return stack / pot if pot > 0 else 0.0


def ev_call(pot: float, call: float, equity: float) -> float:
    """Expected chips gained (relative to folding=0) by calling."""
    return equity * (pot + call) - call


def ev_fold() -> float:
    return 0.0


def ev_bet(pot: float, bet: float, fold_prob: float, equity_when_called: float) -> float:
    """EV of betting: win pot when they fold; when called realise equity of the
    final pot, having put in `bet`."""
    win_now = fold_prob * pot
    called = (1.0 - fold_prob) * (equity_when_called * (pot + 2 * bet) - bet)
    return win_now + called


def ev_raise(pot: float, raise_to: float, my_call: float, fold_prob: float,
             equity_when_called: float) -> float:
    """EV of raising_to over the current bet (already facing `my_call`)."""
    invest = raise_to - my_call
    win_now = pot * fold_prob
    called = (1.0 - fold_prob) * (equity_when_called * (pot + 2 * invest) - invest)
    return win_now + called - my_call * 0.0


def breakeven_fold_pct(pot: float, bet: float) -> float:
    """Alias of alpha, named for the bluffing side."""
    return alpha(pot, bet)


def required_equity_multiway(pot: float, call: float, n_opponents: int) -> float:
    """Same as pot odds; kept for symmetry/documentation."""
    return pot_odds(pot, call)


def value_bluff_ratio(bet_frac: float) -> tuple[float, float]:
    """Balanced river value:bluff share for a given pot fraction bet."""
    a = bet_frac / (1.0 + bet_frac)
    return 1.0 - a, a


def spr_commitment_threshold(spr_val: float) -> float:
    """Rule of thumb: with low SPR you commit with top-pair-or-better.

    Returns the minimum made-hand category (evaluator category index) worth
    stacking off at this SPR.
    """
    if spr_val <= 1.0:
        return 1      # any pair
    if spr_val <= 2.5:
        return 2      # two pair
    if spr_val <= 4.0:
        return 3      # trips
    if spr_val <= 7.0:
        return 4      # straight
    return 5          # flush+


def equity_realization(position_ip: bool, hole_suited: bool, connected: bool,
                       multiway: bool) -> float:
    """Multiplier applied to raw equity to model how much of it we actually
    realise. IP realises more; OOP and multiway realise less (GTO Wizard /
    solvers put OOP realisation around 0.85-0.9 of raw equity)."""
    f = 1.06 if position_ip else 0.88
    if hole_suited:
        f += 0.04
    if connected:
        f += 0.02
    if multiway:
        f -= 0.05
    return max(0.55, min(1.20, f))


def sizing_by_texture(texture: str, street: str, strategy_bias: float = 1.0) -> float:
    """Return a pot fraction for a bet, given board texture and street.

    Dry boards -> small (1/3), wet boards -> large (2/3-3/4), river polarised.
    """
    base = {"dry": 0.33, "medium": 0.55, "wet": 0.72}.get(texture, 0.55)
    if street == "river":
        base += 0.10
    return max(0.25, min(1.6, base * strategy_bias))


def effective_stack(stacks) -> float:
    live = [s for s in stacks if s > 0]
    return min(live) if live else 0.0


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def round_to_blind(amount: float, bb: float, minimum: float = 0.0) -> float:
    step = max(bb / 2.0, 0.5)
    v = round(amount / step) * step
    return max(v, minimum)
