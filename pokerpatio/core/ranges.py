"""Preflop range construction and parsing (169-class shorthand -> set of labels)."""
from __future__ import annotations

import random

from .cards import RANKS, ALL_CLASSES, rank_of, suit_of

_RI = {r: i for i, r in enumerate(RANKS)}  # 'A' -> 12


def _classes_from_token(tok: str) -> set[str]:
    """Support: '22+', 'A2s+', 'AJo+', 'KQo', 'T9s', '32s-54s' style not supported."""
    tok = tok.strip().upper().replace("10", "T")
    if not tok:
        return set()

    # pair shorthand: '22' or '22+'
    if len(tok) in (2, 3) and tok[0] == tok[1] and tok[0] in _RI:
        lo = _RI[tok[0]] + 2
        if tok.endswith("+"):
            return {RANKS[i - 2] * 2 for i in range(lo, 15)}
        return {tok[:2]}

    plus = tok.endswith("+")
    core = tok[:-1] if plus else tok
    if len(core) != 3:
        raise ValueError(f"bad range token {tok!r}")
    hi, lo, kind = core[0], core[1], core[2]
    if hi not in _RI or lo not in _RI or kind not in "SO":
        raise ValueError(f"bad range token {tok!r}")
    h, l = _RI[hi] + 2, _RI[lo] + 2
    if h < l:
        h, l = l, h
    if h == l:
        return {RANKS[h - 2] * 2}
    suffix = "s" if kind == "S" else "o"
    if not plus:
        return {RANKS[h - 2] + RANKS[l - 2] + suffix}
    # plus: raise the LOW card toward (high-1), same suitedness
    out = set()
    for new_l in range(l, h):
        out.add(RANKS[h - 2] + RANKS[new_l - 2] + suffix)
    return out


def parse_range(spec: str | list[str]) -> set[str]:
    toks = spec.replace("\n", " ").replace(",", " ").split() if isinstance(spec, str) else spec
    out: set[str] = set()
    for t in toks:
        out |= _classes_from_token(t)
    return out


def pct(labels: set[str]) -> float:
    """Percentage of all 1326 combos covered."""
    from .cards import class_combos
    return sum(class_combos(l) for l in labels) / 1326 * 100


# ---------------------------------------------------------------- GTO baselines
# 6-max cash, 100bb, 2.5bb opens. Frequencies anchored to published solver
# baselines (UTG ~16%, HJ ~22%, CO ~27%, BTN ~44%, SB ~32%, BB defend 38-63%).
RFI = {
    "UTG": parse_range("22+ A2s+ K9s+ QTs+ JTs T9s 98s 87s ATs+ KQs AJo+ KQo"),
    "HJ":  parse_range("22+ A8s+ K8s+ Q8s+ J8s+ T8s+ 97s+ 87s+ 76s 65s "
                       "ATo+ KTo+ QTo+ JTo KJo QJo"),
    "CO":  parse_range("22+ A2s+ K7s+ Q8s+ J8s+ T7s+ 96s+ 86s+ 75s+ 65s 54s "
                       "A9o+ KTo+ QTo+ JTo KQo"),
    "BTN": parse_range("22+ A2s+ K2s+ Q2s+ J4s+ T5s+ 95s+ 85s+ 74s+ 64s+ 53s+ 43s "
                       "A2o+ K8o+ Q9o+ J9o+ T9o 98o"),
    "SB":  parse_range("22+ A2s+ K5s+ Q7s+ J8s+ T8s+ 96s+ 86s+ 75s+ 65s 54s "
                       "A5o+ K9o+ QTo+ JTo"),
    "BB":  set(),   # BB does not open, it defends
}

# 3-bet ranges
THREEBET = {
    "IP":   parse_range("TT+ AJs+ AQo+ KQs KJs QJs A5s A4s A3s K5s 76s 65s 54s"),
    "OOP":  parse_range("QQ+ AKs AKo AQs A5s A4s KQs 76s"),
    "BLIND": parse_range("TT+ AJs+ AQo+ KQs A5s A4s A3s K5s K4s 76s 65s 54s "
                         "Q9s J9s T9s"),
}
THREEBET_VALUE = parse_range("TT+ AJs+ AQo+ KQs")
THREEBET_BLUFF = parse_range("A5s A4s A3s K5s K4s Q9s J9s T9s 76s 65s 54s")

# Call/defend ranges vs an open, by opener position (call + 3bet combined)
DEFEND = {
    "UTG": parse_range("22+ A2s+ K4s+ Q6s+ J7s+ T7s+ 96s+ 86s+ 75s+ 65s+ 54s "
                       "A7o+ K9o+ Q9o+ J9o+ T9o 98o 87o 76o 65o"),
    "HJ":  parse_range("22+ A2s+ K4s+ Q5s+ J6s+ T6s+ 95s+ 85s+ 75s+ 64s+ 54s "
                       "A5o+ K9o+ Q9o+ J9o+ T9o 98o 87o 76o"),
    "CO":  parse_range("22+ A2s+ K3s+ Q5s+ J6s+ T6s+ 95s+ 85s+ 75s+ 64s+ 54s "
                       "A4o+ K9o+ Q9o+ J9o+ T9o 98o 87o 76o"),
    "BTN": parse_range("22+ A2s+ K2s+ Q2s+ J2s+ T3s+ 94s+ 84s+ 74s+ 63s+ 53s+ 43s "
                       "A2o+ K5o+ Q7o+ J7o+ T7o+ 96o+ 86o+ 75o+ 65o+ 54o+ 98o 87o 76o"),
    "SB":  parse_range("22+ A2s+ K4s+ Q6s+ J7s+ T7s+ 96s+ 86s+ 75s+ 65s+ 54s "
                       "A6o+ K9o+ Q9o+ J9o+ T9o 98o 87o"),
}

# push/fold (<= 15bb) — 10bb shove ranges from published charts
SHOVE = {
    "BTN": parse_range("22+ A2s+ A2o+ K2s+ K6o+ Q5s+ Q9o+ J7s+ J9o+ T7s+ T9o 97s+ 87s 76s"),
    "CO":  parse_range("22+ A2s+ A4o+ K4s+ K9o+ Q7s+ QTo+ J8s+ JTo T8s+ 97s+ 87s"),
    "HJ":  parse_range("22+ A2s+ A7o+ K8s+ KJo+ Q9s+ QJo J9s+ T9s"),
    "UTG": parse_range("22+ A2s+ A9o+ KTs+ KQo QJs"),
    "SB":  parse_range("22+ A2s+ A2o+ K2s+ K4o+ Q3s+ Q8o+ J6s+ J9o+ T7s+ T9o 97s+ 87s 76s"),
    "BB":  parse_range("22+ A2s+ A7o+ K7s+ K9o+ Q8s+ QTo+ J8s+ JTo T8s+ 98o 87s 76s"),
}


# ------------------------------------------------------- playability ordering
def _playability(label: str) -> float:
    """Static score used to widen/narrow a range in a sensible order."""
    if len(label) == 2:
        r = RANKS.index(label[0]) + 2
        return 60 + r * 2.0
    hi, lo = RANKS.index(label[0]) + 2, RANKS.index(label[1]) + 2
    suited = label[2] == "s"
    gap = hi - lo
    if suited:
        s = 34 + hi * 1.5 + lo * 0.7
        s += 10 if gap == 1 else 7 if gap == 2 else 4 if gap == 3 else 0
    else:
        s = 20 + hi * 1.6 + lo * 0.4
        s += 3 if gap == 1 else 1 if gap == 2 else 0
    return s


_PLAY_ORDER = sorted(ALL_CLASSES, key=_playability, reverse=True)


def widen_to(labels: set[str], target_pct: float) -> set[str]:
    """Add best remaining hands (by playability) until `target_pct` is reached."""
    out = set(labels)
    for label in _PLAY_ORDER:
        if pct(out) >= target_pct:
            break
        out.add(label)
    return out


def narrow_to(labels: set[str], target_pct: float) -> set[str]:
    """Remove worst hands until width <= target_pct (keeps at least 2%)."""
    out = set(labels)
    target_pct = max(2.0, target_pct)
    for label in reversed(_PLAY_ORDER):
        if pct(out) <= target_pct or len(out) <= 4:
            break
        out.discard(label)
    return out


def rfi_for(pos: str, loosen_pp: float = 0.0) -> set[str]:
    base = set(RFI.get(pos, set()))
    if not base:
        return base
    if loosen_pp > 0:
        return widen_to(base, pct(base) + loosen_pp)
    if loosen_pp < 0:
        return narrow_to(base, pct(base) + loosen_pp)
    return base


def defend_for(pos: str, loosen_pp: float = 0.0) -> set[str]:
    base = set(DEFEND.get(pos, set()))
    if not base:
        return base
    if loosen_pp > 0:
        return widen_to(base, pct(base) + loosen_pp)
    if loosen_pp < 0:
        return narrow_to(base, pct(base) + loosen_pp)
    return base


def sample_hand_from_range(rng: random.Random, labels: set[str], dead) -> tuple[int, int] | None:
    """Pick a concrete 2-card combo consistent with the range and not in dead."""
    dead = set(dead)
    combos = []
    for label in labels:
        combos.extend(_combos_for(label, dead))
    if not combos:
        return None
    return rng.choice(combos)


def _combos_for(label: str, dead: set[int]) -> list[tuple[int, int]]:
    from .cards import make_card
    if len(label) == 2:
        r = RANKS.index(label[0]) + 2
        return [(make_card(r, s1), make_card(r, s2))
                for s1 in range(4) for s2 in range(s1 + 1, 4)
                if make_card(r, s1) not in dead and make_card(r, s2) not in dead]
    hi = RANKS.index(label[0]) + 2
    lo = RANKS.index(label[1]) + 2
    suited = label[2] == "s"
    out = []
    if suited:
        for s in range(4):
            a, b = make_card(hi, s), make_card(lo, s)
            if a not in dead and b not in dead:
                out.append((a, b))
    else:
        for s1 in range(4):
            for s2 in range(4):
                if s1 == s2:
                    continue
                a, b = make_card(hi, s1), make_card(lo, s2)
                if a not in dead and b not in dead:
                    out.append((a, b))
    return out


def in_range(labels: set[str], hole) -> bool:
    from .cards import hand_class
    return hand_class(hole[0], hole[1]) in labels


def random_class(rng: random.Random) -> str:
    return rng.choice(ALL_CLASSES)
