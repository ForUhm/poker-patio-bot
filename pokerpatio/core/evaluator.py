"""Fast pure-python 7-card hand evaluator.

evaluate(cards) -> int score, higher is better. Score packs category + tiebreaks
into a single int so comparison is a plain integer compare.

Layout: [category:3][t1:5][t2:5][t3:5][t4:5][t5:5]  (top 25 bits unused)
"""
from __future__ import annotations

CAT_NAMES = [
    "High Card", "Pair", "Two Pair", "Trips", "Straight",
    "Flush", "Full House", "Quads", "Straight Flush",
]

RANK_WORD = {2: "Twos", 3: "Threes", 4: "Fours", 5: "Fives", 6: "Sixes",
             7: "Sevens", 8: "Eights", 9: "Nines", 10: "Tens", 11: "Jacks",
             12: "Queens", 13: "Kings", 14: "Aces"}
RANK_CHR = "23456789TJQKA"

# rank bitmask helpers: bit N set means rank N present (N = 2..14)
_STRAIGHT_MASKS = []
for _hi in range(14, 6 - 1, -1):          # A-high down to 6-high
    m = 0
    for k in range(5):
        m |= 1 << (_hi - k)
    _STRAIGHT_MASKS.append((m, _hi))
# wheel A-5: 5,4,3,2,A  -> straight high card is 5
_WHEEL = (1 << 5) | (1 << 4) | (1 << 3) | (1 << 2) | (1 << 14)


def evaluate(cards) -> int:
    """cards: iterable of 5..7 ints. Returns comparable int score."""
    rank_counts = [0] * 15
    suit_counts = [0, 0, 0, 0]
    suit_masks = [0, 0, 0, 0]
    for c in cards:
        r = c // 4 + 2
        s = c % 4
        rank_counts[r] += 1
        suit_counts[s] += 1
        suit_masks[s] |= 1 << r

    # --- flush / straight flush ---
    flush_suit = -1
    for s in range(4):
        if suit_counts[s] >= 5:
            flush_suit = s
            break

    if flush_suit >= 0:
        fm = suit_masks[flush_suit]
        for m, hi in _STRAIGHT_MASKS:
            if fm & m == m:
                return _pack(8, hi)
        if fm & _WHEEL == _WHEEL:
            return _pack(8, 5)

    # --- rank shapes ---
    quads = -1
    trips = []
    pairs = []
    for r in range(14, 1, -1):
        n = rank_counts[r]
        if n == 4:
            if quads < 0:
                quads = r
            else:
                pairs.append(r)
        elif n == 3:
            trips.append(r)
        elif n == 2:
            pairs.append(r)

    if quads > 0:
        kick = max((r for r in range(14, 1, -1) if r != quads and rank_counts[r]), default=2)
        return _pack(7, quads, kick)

    trips.sort(reverse=True)
    pairs.sort(reverse=True)

    if len(trips) >= 2:
        return _pack(6, trips[0], trips[1])
    if trips and pairs:
        return _pack(6, trips[0], pairs[0])

    # --- straight (non-flush) ---
    mask = 0
    for r in range(14, 1, -1):
        if rank_counts[r]:
            mask |= 1 << r
    for m, hi in _STRAIGHT_MASKS:
        if mask & m == m:
            return _pack(4, hi)
    if mask & _WHEEL == _WHEEL:
        return _pack(4, 5)

    # --- flush ---
    if flush_suit >= 0:
        fm = suit_masks[flush_suit]
        top5 = [r for r in range(14, 1, -1) if fm & (1 << r)][:5]
        return _pack(5, *top5)

    # --- trips / two pair / pair / high card ---
    if trips:
        kick = [r for r in range(14, 1, -1) if rank_counts[r] and r != trips[0]][:2]
        return _pack(3, trips[0], *kick)
    if len(pairs) >= 2:
        used = {pairs[0], pairs[1]}
        kick = max((r for r in range(14, 1, -1) if rank_counts[r] and r not in used), default=2)
        return _pack(2, pairs[0], pairs[1], kick)
    if pairs:
        kick = [r for r in range(14, 1, -1) if rank_counts[r] and r != pairs[0]][:3]
        return _pack(1, pairs[0], *kick)
    top5 = [r for r in range(14, 1, -1) if rank_counts[r]][:5]
    return _pack(0, *top5)


def _pack(cat: int, *vals) -> int:
    score = cat
    for i in range(5):
        score = (score << 5) | (vals[i] if i < len(vals) else 0)
    return score


def category(score: int) -> int:
    return score >> 25


def tiebreaks(score: int) -> list[int]:
    """4 tiebreak values, most significant first (cat lives above bit 25)."""
    return [(score >> sh) & 31 for sh in (20, 15, 10, 5)]


def describe(score: int) -> str:
    return CAT_NAMES[category(score)]


def describe_hand(cards) -> str:
    """Human label for a 5..7 card holding, e.g. 'Two Pair, Kings and Sevens'."""
    sc = evaluate(cards)
    cat = category(sc)
    a, b, c, _d = tiebreaks(sc)
    if cat == 8:
        return (f"Royal Flush" if a == 14
                else f"Straight Flush, {RANK_CHR[a - 2]}-high")
    if cat == 7:
        return f"Quads, {RANK_WORD[a]}"
    if cat == 6:
        return f"Full House, {RANK_WORD[a]} over {RANK_WORD[b]}"
    if cat == 5:
        return f"Flush, {RANK_CHR[a - 2]}-high"
    if cat == 4:
        return f"Straight, {RANK_CHR[a - 2]}-high"
    if cat == 3:
        return f"Trips, {RANK_WORD[a]}"
    if cat == 2:
        return f"Two Pair, {RANK_WORD[a]} and {RANK_WORD[b]}"
    if cat == 1:
        return f"Pair of {RANK_WORD[a]}"
    return f"High Card, {RANK_CHR[a - 2]}-high"
