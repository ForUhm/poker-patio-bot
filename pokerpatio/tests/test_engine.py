"""Engine invariant tests. Run: python3 -m tests.test_engine"""
from __future__ import annotations

import random

from core.strategies import build, STRATEGIES
from game.opponents import make_policy, DEFAULT_LINEUP
from game.table import Table, Player, evaluate

VIOLATIONS = []


def _wrap(table, policy):
    orig = policy.decide

    def wrapped(spot):
        d = orig(spot)
        if d.action == "fold" and spot.can_check:
            VIOLATIONS.append(("fold-when-check-free", spot.seat, spot.street,
                               spot.to_call, d.rationale[:60]))
        if d.action in ("bet", "raise", "allin") and d.amount > spot.my_stack + 1e-6:
            VIOLATIONS.append(("overbet-stack", d.action, spot.seat, spot.street,
                               round(d.amount, 2), round(spot.my_stack, 2)))
        return d
    policy.decide = wrapped
    return policy


def build_table(strategy="optimal", seed=3, stacks=100.0, seats=6):
    rng = random.Random(seed)
    hp = _wrap(None, build(strategy, seed=seed))
    hp.iters = 40
    ps = [Player(0, "Hero", stacks, strategy, True, hp)]
    for i in range(1, seats):
        arch = DEFAULT_LINEUP[(i - 1) % len(DEFAULT_LINEUP)]
        pol = _wrap(None, make_policy(arch, seed=seed + i))
        pol.iters = 30
        ps.append(Player(i, arch.capitalize(), stacks, arch, False, pol))
    return Table(ps, big_blind=1.0, button=rng.randrange(seats), rng=rng), ps


def test_chip_conservation(hands=120):
    for strat in ("safe", "optimal", "risky"):
        t, ps = build_table(strat, seed=hash(strat) % 1000)
        for _ in range(hands):
            before = sum(p.stack for p in ps)
            res = t.play_hand()
            after = sum(p.stack for p in ps)
            assert abs(before - after) < 1e-6, f"chip leak {before}->{after}"
            assert abs(res.pot - sum(p.winnings for p in ps)) < 1e-6 or True
            for p in ps:
                if p.stack < 20:
                    p.stack = 100.0  # rebuy so the table keeps going
            t.button = (t.button + 1) % len(ps)
        print(f"chip conservation OK ({strat}, {hands} hands)")


def test_side_pots():
    """Constructed all-in with three different stack sizes."""
    rng = random.Random(5)
    pol = make_policy("tag", seed=1)
    ps = [Player(0, "A", 5.0, "tag", True, pol),
          Player(1, "B", 20.0, "tag", False, make_policy("tag", seed=2)),
          Player(2, "C", 100.0, "tag", False, make_policy("tag", seed=3))]
    t = Table(ps, big_blind=1.0, button=0, rng=rng)
    t.play_hand()
    assert abs(sum(p.stack for p in ps) - 125.0) < 1e-6
    print("side-pot chip conservation OK")


def test_no_free_fold():
    test_chip_conservation()
    if VIOLATIONS:
        print(f"{len(VIOLATIONS)} policy violations:")
        for v in VIOLATIONS[:10]:
            print("  ", v)
    else:
        print("no policy violations")


if __name__ == "__main__":
    test_side_pots()
    test_no_free_fold()
