"""Opponent archetypes used to populate the other seats.

Each archetype is an instance of OptimalStrategy with its parameters bent to a
recognisable playing style. `opp_stats` is handed to the hero's Spot so the
bluff logic can key off the opponent's real fold-to-bet tendency.
"""
from __future__ import annotations

import random

from core.strategies import OptimalStrategy

ARCHETYPES = {
    "tag": {
        "label": "TAG (tight-aggressive)",
        "vpip": 22, "pfr": 18, "fold_to_bet": 0.45, "aggression": 1.8,
        "loosen": -1.0, "bluff_freq": 0.10, "call_margin": 0.03,
        "value_threshold": 0.63, "raise_threshold": 0.71,
        "sizing_bias": 1.0, "trust_draws": 0.5, "open_size_bb": 2.5,
    },
    "lag": {
        "label": "LAG (loose-aggressive)",
        "vpip": 34, "pfr": 27, "fold_to_bet": 0.32, "aggression": 2.6,
        "loosen": 7.0, "bluff_freq": 0.24, "call_margin": 0.0,
        "value_threshold": 0.57, "raise_threshold": 0.66,
        "sizing_bias": 1.15, "trust_draws": 0.7, "open_size_bb": 3.0,
    },
    "station": {
        "label": "Calling station",
        "vpip": 56, "pfr": 7, "fold_to_bet": 0.26, "aggression": 0.5,
        "loosen": 15.0, "bluff_freq": 0.0, "call_margin": -0.17,
        "value_threshold": 0.80, "raise_threshold": 0.93,
        "sizing_bias": 0.75, "trust_draws": 0.95, "open_size_bb": 2.0,
    },
    "nit": {
        "label": "Nit",
        "vpip": 13, "pfr": 10, "fold_to_bet": 0.63, "aggression": 1.2,
        "loosen": -9.0, "bluff_freq": 0.0, "call_margin": 0.12,
        "value_threshold": 0.72, "raise_threshold": 0.82,
        "sizing_bias": 0.85, "trust_draws": 0.35, "open_size_bb": 2.5,
    },
    "maniac": {
        "label": "Maniac",
        "vpip": 71, "pfr": 52, "fold_to_bet": 0.16, "aggression": 4.2,
        "loosen": 24.0, "bluff_freq": 0.46, "call_margin": -0.20,
        "value_threshold": 0.48, "raise_threshold": 0.54,
        "sizing_bias": 1.55, "trust_draws": 1.2, "open_size_bb": 3.5,
    },
}

DEFAULT_LINEUP = ["tag", "lag", "station", "nit", "maniac"]


class ArchetypePolicy(OptimalStrategy):
    """OptimalStrategy with an archetype's tendencies, plus mild noise."""

    def __init__(self, arch: str, seed: int | None = None):
        super().__init__(seed=seed)
        cfg = ARCHETYPES[arch]
        self.arch = arch
        self.label = cfg["label"]
        self.loosen = cfg["loosen"]
        self.bluff_freq = cfg["bluff_freq"]
        self.call_margin = cfg["call_margin"]
        self.value_threshold = cfg["value_threshold"]
        self.raise_threshold = cfg["raise_threshold"]
        self.sizing_bias = cfg["sizing_bias"]
        self.trust_draws = cfg["trust_draws"]
        self.open_size_bb = cfg["open_size_bb"]
        self.opp_stats = {
            "archetype": arch,
            "vpip": cfg["vpip"],
            "pfr": cfg["pfr"],
            "fold_to_bet": cfg["fold_to_bet"],
            "aggression": cfg["aggression"],
        }
        self.iters = 90
        self._noise = 0.06
        self._rng2 = random.Random(seed)

    def decide(self, spot):
        # per-spot jitter so identical spots do not always play identically
        jitter = self._rng2.uniform(-self._noise, self._noise)
        saved = self.call_margin, self.value_threshold
        self.call_margin = saved[0] + jitter
        self.value_threshold = saved[1] + jitter * 0.5
        try:
            return super().decide(spot)
        finally:
            self.call_margin, self.value_threshold = saved


def make_policy(arch: str, seed: int | None = None) -> ArchetypePolicy:
    return ArchetypePolicy(arch, seed=seed)


def lineup_meta() -> list[dict]:
    return [{"key": k, "label": v["label"], "vpip": v["vpip"], "pfr": v["pfr"],
             "fold_to_bet": v["fold_to_bet"], "aggression": v["aggression"]}
            for k, v in ARCHETYPES.items()]
