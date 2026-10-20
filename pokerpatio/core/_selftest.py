from __future__ import annotations

import random
import time

from .cards import parse_cards, card_str, cards_str
from .evaluator import evaluate, describe, describe_hand, category


def test_ordering():
    cases = [
        ("AsKsQsJsTs", 8),          # royal
        ("7s7d7h7c2s", 7),          # quads
        ("KhKdKc2s2d", 6),          # boat
        ("As Ks Qs Js 9s", 5),      # flush
        ("9s8d7h6c5s", 4),          # straight
        ("Ah2d3c4s5h", 4),          # wheel
        ("QsQdQh3s2d", 3),          # trips
        ("TsTd9h9c2s", 2),          # two pair
        ("8s8dAhKc2s", 1),          # pair
        ("AsKd9h7c3s", 0),          # high card
    ]
    for s, want in cases:
        got = category(evaluate(parse_cards(s)))
        assert got == want, (s, got, want)
    # strict ordering sanity
    order = [evaluate(parse_cards(s)) for s, _ in cases]
    assert order == sorted(order, reverse=True), [describe(x) for x in order]
    print("ordering OK")


def test_kickers():
    a = evaluate(parse_cards("AsAd KhQc9s"))
    b = evaluate(parse_cards("AsAd KhQc8s"))
    assert a > b
    # two pair, same pairs, different kicker
    a = evaluate(parse_cards("AsAd KsKd Qs"))
    b = evaluate(parse_cards("AsAd KsKd Js"))
    assert a > b
    # wheel straight flush
    assert category(evaluate(parse_cards("As2s3s4s5s"))) == 8
    # board plays: 7-card where board is best
    assert category(evaluate(parse_cards("2c3d AsKsQsJsTs"))) == 8
    print("kickers OK")


def test_describe():
    print(describe_hand(parse_cards("AsAd KsKd 2c")))
    print(describe_hand(parse_cards("AsKs QsJs 9s 2c")))
    print(describe_hand(parse_cards("As2d3c4s5h9d")))


def bench(n=50000):
    rng = random.Random(7)
    deck = list(range(52))
    hands = [rng.sample(deck, 7) for _ in range(n)]
    t = time.perf_counter()
    s = 0
    for h in hands:
        s += evaluate(h)
    dt = time.perf_counter() - t
    print(f"{n} evals in {dt:.3f}s -> {n/dt:,.0f}/s  (checksum {s})")


if __name__ == "__main__":
    test_ordering()
    test_kickers()
    test_describe()
    bench()
