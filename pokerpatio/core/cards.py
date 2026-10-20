"""Card primitives. Cards are ints 0..51: rank = c//4 (2..14), suit = c%4 (c,d,h,s)."""
from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i + 2 for i, r in enumerate(RANKS)}


def make_card(rank: int, suit: int) -> int:
    return (rank - 2) * 4 + suit


def parse_card(s: str) -> int:
    s = s.strip()
    r, su = s[0].upper(), s[1].lower()
    return make_card(RANK_VAL[r], SUITS.index(su))


def parse_cards(s: str) -> list[int]:
    """'AsKd' / 'As Kd' / 'As,Kd' / 'AsAd KhQc9s' -> list of cards."""
    s = "".join(ch for ch in s if not ch.isspace() and ch not in ",/")
    if len(s) % 2:
        raise ValueError(f"bad card string: {s!r}")
    return [parse_card(s[i:i + 2]) for i in range(0, len(s), 2)]


def card_str(c: int) -> str:
    return RANKS[c // 4] + SUITS[c % 4]


def cards_str(cs) -> str:
    return " ".join(card_str(c) for c in cs)


def rank_of(c: int) -> int:
    return c // 4 + 2


def suit_of(c: int) -> int:
    return c % 4


FULL_DECK = tuple(range(52))


def strip_deck(dead) -> list[int]:
    dead = set(dead)
    return [c for c in FULL_DECK if c not in dead]


def hand_class(c1: int, c2: int) -> str:
    """169-bucket class label, e.g. 'AKs', 'QQ', 'T9o'."""
    r1, r2 = rank_of(c1), rank_of(c2)
    hi, lo = max(r1, r2), min(r1, r2)
    if hi == lo:
        return RANKS[hi - 2] * 2
    suited = suit_of(c1) == suit_of(c2)
    return RANKS[hi - 2] + RANKS[lo - 2] + ("s" if suited else "o")


def class_combos(label: str) -> int:
    """Number of distinct 2-card combos in a 169-class bucket (4/6/12)."""
    if len(label) == 2:
        return 6
    return 4 if label[2] == "s" else 12


ALL_CLASSES = []
for _i in range(13):
    for _j in range(_i, 13):
        hi, lo = RANKS[12 - _i], RANKS[12 - _j]
        if hi == lo:
            ALL_CLASSES.append(hi * 2)
        else:
            ALL_CLASSES.append(hi + lo + "s")
            ALL_CLASSES.append(hi + lo + "o")
assert len(ALL_CLASSES) == 169
