"""No-limit hold'em table engine: blinds, betting rounds, all-ins, side pots.

The engine is policy-agnostic: every seat carries a policy object exposing
`decide(spot) -> Decision`. The hero seat uses one of the three shipped
strategies; the other seats use archetype policies (see game/opponents.py).
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from core.cards import card_str, hand_class
from core.evaluator import evaluate, describe_hand, category
from core.strategies import Spot, Decision, BaseStrategy

MAX_SEATS = 6
# label for offset 0,1,2,... from the button seat
POSITIONS_BY_COUNT = {
    2: ["BTN", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
}
STREETS = ("preflop", "flop", "turn", "river")


@dataclass
class Player:
    seat: int
    name: str
    stack: float
    style: str
    is_hero: bool
    policy: object
    hole: tuple = ()
    in_hand: bool = True
    all_in: bool = False
    invested: float = 0.0     # chips in on the current street
    committed: float = 0.0    # chips in for the whole hand
    acted: bool = False
    last_action: str = ""
    winnings: float = 0.0
    start_stack: float = 0.0
    range_pct: float = 100.0   # estimated % of hands still in their range

    def to_dict(self):
        return {
            "seat": self.seat, "name": self.name, "stack": round(self.stack, 2),
            "style": self.style, "hero": self.is_hero,
            "hole": [card_str(c) for c in self.hole] if self.is_hero else [],
            "in_hand": self.in_hand, "all_in": self.all_in,
            "committed": round(self.committed, 2),
            "last_action": self.last_action,
            "winnings": round(self.winnings, 2),
        }


@dataclass
class HandResult:
    hand_id: int
    board: list
    pot: float
    players: list
    winners: list
    hero_seat: int
    hero_delta: float
    hero_stack_after: float
    showdown: bool
    hero_hole: list
    hero_position: str
    hero_actions: list
    all_actions: list
    hand_label: str = ""
    result_type: str = ""      # showdown | fold-win
    hero_won: bool = False
    hero_in_hand: bool = False  # hero still had cards at the end

    def to_dict(self):
        return {
            "hand_id": self.hand_id,
            "board": [card_str(c) for c in self.board],
            "pot": round(self.pot, 2),
            "players": [p.to_dict() if isinstance(p, Player) else p for p in self.players],
            "winners": self.winners,
            "hero_seat": self.hero_seat,
            "hero_delta": round(self.hero_delta, 2),
            "hero_stack_after": round(self.hero_stack_after, 2),
            "showdown": self.showdown,
            "hero_hole": [card_str(c) for c in self.hero_hole],
            "hero_position": self.hero_position,
            "hero_actions": self.hero_actions,
            "hand_label": self.hand_label,
            "result_type": self.result_type,
            "hero_won": self.hero_won,
            "hero_in_hand": self.hero_in_hand,
            "all_actions": self.all_actions,
        }


class Table:
    def __init__(self, players: list[Player], big_blind: float = 1.0,
                 button: int = 0, rng: random.Random | None = None):
        self.players = players
        self.bb = big_blind
        self.sb = big_blind / 2.0
        self.button = button
        self.rng = rng or random.Random()
        self.hand_id = 0
        self.action_log: list[dict] = []
        self.hero_seat = next((p.seat for p in players if p.is_hero), 0)

    # ------------------------------------------------------------------ utils
    @property
    def n(self) -> int:
        return len(self.players)

    @property
    def pot(self) -> float:
        return sum(p.committed for p in self.players)

    def _active(self):
        return [p for p in self.players if p.in_hand]

    def _can_act(self):
        return [p for p in self.players if p.in_hand and not p.all_in and p.stack > 0]

    def positions(self) -> dict[int, str]:
        """Map seat -> position label for this hand (offset from the button)."""
        labels = POSITIONS_BY_COUNT.get(self.n, POSITIONS_BY_COUNT[6])
        out = {}
        for off in range(self.n):
            seat = (self.button + off) % self.n
            out[seat] = labels[off] if off < len(labels) else "CO"
        return out

    def _label_for(self, seat: int) -> str:
        pos = self.positions()
        return pos.get(seat, "BTN")

    def _order_from(self, start: Player):
        idx = self.players.index(start)
        for k in range(self.n):
            yield self.players[(idx + k) % self.n]

    def _commit(self, p: Player, amount: float) -> float:
        amount = max(0.0, min(amount, p.stack))
        p.stack -= amount
        p.invested += amount
        p.committed += amount
        if p.stack <= 1e-9:
            p.stack = 0.0
            p.all_in = True
        return amount

    # ------------------------------------------------------------------- hand
    def play_hand(self) -> HandResult:
        self.hand_id += 1
        self.action_log = []
        board: list[int] = []
        deck = list(range(52))
        self.rng.shuffle(deck)

        for p in self.players:
            p.hole = ()
            p.in_hand = p.stack > 1e-9
            p.all_in = False
            p.invested = 0.0
            p.committed = 0.0
            p.acted = False
            p.last_action = ""
            p.winnings = 0.0
            p.start_stack = p.stack
            p.range_pct = 100.0

        live = [p for p in self.players if p.in_hand]
        if len(live) < 2:
            return self._build_result(board, press_showdown=False, note="not-enough-players")

        self.street = "preflop"
        self.board = board
        self._raises_faced = 0
        self._limpers = 0
        self._opener_pos = ""
        self._aggressor = None
        self.bet_level = 0.0
        self.last_raise = self.bb
        self.min_raise_to = self.bb
        self.pot_before_street = 0.0

        # deal
        for i, p in enumerate(live):
            p.hole = (deck.pop(), deck.pop())

        # blinds
        seats_in = [p.seat for p in live]
        sb_seat = (self.button + 1) % self.n
        bb_seat = (self.button + 2) % self.n
        # if the blind seat is empty, walk forward
        while sb_seat not in seats_in:
            sb_seat = (sb_seat + 1) % self.n
        while bb_seat not in seats_in or bb_seat == sb_seat:
            bb_seat = (bb_seat + 1) % self.n
        self._commit(self._seat(sb_seat), self.sb)
        self._commit(self._seat(bb_seat), self.bb)
        self.bet_level = self.bb
        self.min_raise_to = 2 * self.bb
        for p in live:
            p.acted = False

        self._log(None, "blind", self.sb, note=f"SB {self._seat(sb_seat).name}")
        self._log(None, "blind", self.bb, note=f"BB {self._seat(bb_seat).name}")

        # preflop: action starts left of BB
        start = (bb_seat + 1) % self.n
        while self._seat(start).seat not in seats_in:
            start = (start + 1) % self.n
        self._betting_round(self._seat(start), "preflop")
        if self._only_one_left():
            self._settle_fold_win()
            return self._build_result(board, press_showdown=False)

        # postflop streets
        for street, count in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(self._can_act()) <= 1:
                board.extend(deck.pop() for _ in range(count))
                continue
            self.street = street
            self.bet_level = 0.0
            self.last_raise = self.bb
            self.min_raise_to = self.bb
            for p in self.players:
                p.invested = 0.0
                p.acted = False
                p.last_action = ""
            board.extend(deck.pop() for _ in range(count))
            self.board = board
            self._raises_faced = 0
            self._limpers = 0
            self._log(None, "deal", 0, note=f"{street}: " + " ".join(card_str(c) for c in board))
            start = (self.button + 1) % self.n
            while not (self._seat(start).in_hand and not self._seat(start).all_in):
                start = (start + 1) % self.n
                if start == self.button:
                    break
            self._betting_round(self._seat(start), street)
            if self._only_one_left():
                self._settle_fold_win()
                return self._build_result(board, press_showdown=False)

        # run out remaining board if everyone is all-in
        while len(board) < 5:
            board.append(deck.pop())
        self.board = board

        self._settle_showdown(board)
        return self._build_result(board, press_showdown=True)

    def _seat(self, seat: int) -> Player:
        return next(p for p in self.players if p.seat == seat)

    def _only_one_left(self) -> bool:
        return len(self._active()) <= 1

    # --------------------------------------------------------------- betting
    def _needs_action(self, p: Player) -> bool:
        if not p.in_hand or p.all_in:
            return False
        return (not p.acted) or p.invested < self.bet_level - 1e-9

    def _round_complete(self) -> bool:
        for p in self.players:
            if not p.in_hand or p.all_in:
                continue
            if not p.acted or p.invested < self.bet_level - 1e-9:
                return False
        return True

    def _betting_round(self, start: Player, street: str) -> None:
        guard = 0
        cur = start
        while True:
            p = cur
            if self._needs_action(p):
                self._act(p, street)
                if self._only_one_left():
                    return
            cur = self.players[(self.players.index(p) + 1) % self.n]
            guard += 1
            if self._round_complete():
                return
            if guard > 400:       # safety valve against pathological loops
                return

    def _build_spot(self, p: Player, street: str) -> Spot:
        to_call = max(0.0, self.bet_level - p.invested)
        others = [o for o in self.players if o is not p and o.in_hand]
        n_opp = max(1, len(others))
        pot_for_call = self.pot  # pot already includes everything committed
        is_ip = self._is_in_position(p)
        seat_label = self._label_for(p.seat)
        max_raise_to = p.invested + p.stack
        min_raise_to = min(self.min_raise_to, max_raise_to)
        return Spot(
            hole=tuple(p.hole),
            board=tuple(getattr(self, "board", ())),
            street=street,
            pot=pot_for_call,
            to_call=to_call,
            my_stack=p.stack,
            eff_stack=min([p.stack] + [o.stack for o in others]),
            position="IP" if is_ip else "OOP",
            seat=seat_label,
            n_opponents=n_opp,
            raises_faced=self._raises_faced,
            limpers=self._limpers,
            big_blind=self.bb,
            can_check=to_call <= 1e-9,
            my_invested=p.invested,
            bet_level=self.bet_level,
            min_raise_to=min_raise_to,
            max_raise_to=max_raise_to,
            opponent=p.policy.__dict__.get("opp_stats", {}),
            opp_pcts=tuple(o.range_pct for o in others),
            opener=getattr(self, "_opener_pos", ""),
            i_am_aggressor=getattr(self, "_aggressor", None) is p,
            iters=getattr(p.policy, "iters", 120),
            seed=self.rng.randrange(1 << 30),
        )

    def _is_in_position(self, p: Player) -> bool:
        """True if p acts last among remaining players this street."""
        can = self._can_act()
        if len(can) <= 1:
            return True
        order = list(self._order_from(self.players[(self.button + 1) % self.n]))
        order = [x for x in order if x in can]
        return order and order[-1] is p

    _raises_faced = 0
    _limpers = 0

    def _act(self, p: Player, street: str) -> None:
        spot = self._build_spot(p, street)
        decision: Decision = p.policy.decide(spot)
        pos = self._label_for(p.seat)
        before = p.invested
        act = decision.action

        if act == "fold":
            p.in_hand = False
            p.acted = True
            p.last_action = "fold"
        elif act == "check":
            p.acted = True
            p.last_action = "check"
        elif act == "call":
            if street == "preflop" and self._raises_faced == 0:
                self._limpers += 1
            self._commit(p, spot.to_call)
            p.acted = True
            p.last_action = "call"
        else:  # bet / raise / allin
            add = decision.amount if decision.amount > 0 else p.stack
            target = p.invested + add
            if target > p.invested + p.stack:
                target = p.invested + p.stack
            min_target = self.min_raise_to if street != "preflop" else self.min_raise_to
            if target < min_target and p.invested + p.stack >= min_target:
                target = min_target
            add = target - p.invested
            was_raise = self.bet_level > 0
            old_level = self.bet_level
            self._commit(p, add)
            new_level = max(old_level, p.invested)
            if new_level > old_level + 1e-9:
                self.last_raise = new_level - old_level
                self.min_raise_to = new_level + max(self.last_raise, self.bb)
                self.bet_level = new_level
                for o in self.players:
                    if o is not p and o.in_hand and not o.all_in:
                        o.acted = False
                if street == "preflop":
                    self._raises_faced = 1 if not was_raise else self._raises_faced + 1
                    self._opener_pos = pos
                self._aggressor = p
            p.acted = True
            p.last_action = "bet" if not was_raise else "raise"
        p.acted = True
        self._update_range(p, p.last_action, street, spot)

        self._log(p, p.last_action, p.invested - before,
                  decision=decision.to_dict(), street=street, position=pos)

    def _update_range(self, p: Player, act: str, street: str, spot) -> None:
        """Track how wide this player's range still is, from their own actions."""
        from core.ranges import pct as _pct
        pol = p.policy
        try:
            if street == "preflop":
                if act in ("raise", "bet"):
                    if spot.raises_faced > 0 and hasattr(pol, "_threebet_range"):
                        w = _pct(pol._threebet_range(spot))
                    else:
                        w = _pct(pol._rfi(spot.seat)) or 25.0
                        if spot.seat == "BB":
                            w = 20.0
                    p.range_pct = max(4.0, w)
                elif act == "call":
                    w = _pct(pol._defend(spot.opener or "BTN"))
                    p.range_pct = max(6.0, w)
                elif act == "check":
                    p.range_pct = max(20.0, p.range_pct * 0.92)
            else:
                if act in ("bet", "raise"):
                    p.range_pct = max(4.0, p.range_pct * 0.45)
                elif act == "call":
                    p.range_pct = max(5.0, p.range_pct * 0.62)
                elif act == "check":
                    p.range_pct = max(6.0, p.range_pct * 0.88)
        except Exception:
            pass

    # ---------------------------------------------------------------- settle
    def _settle_fold_win(self) -> None:
        live = self._active()
        if not live:
            return
        winner = live[0]
        pot = self.pot
        winner.stack += pot
        winner.winnings = pot
        self._log(winner, "wins", pot, note="everyone folded")

    def _settle_showdown(self, board) -> None:
        contribs = {p.seat: p.committed for p in self.players}
        levels = sorted({v for v in contribs.values() if v > 0})
        scores = {}
        for p in self.players:
            if p.in_hand:
                scores[p.seat] = evaluate(list(p.hole) + list(board))
        prev = 0.0
        for lvl in levels:
            layer = lvl - prev
            contributors = [p for p in self.players if p.committed >= lvl - 1e-9]
            pot_size = layer * len(contributors)
            eligible = [p for p in contributors if p.in_hand and p.seat in scores]
            if not eligible or pot_size <= 0:
                prev = lvl
                continue
            best = max(scores[p.seat] for p in eligible)
            winners = [p for p in eligible if scores[p.seat] == best]
            share = pot_size / len(winners)
            for w in winners:
                w.stack += share
                w.winnings += share
            self._log(winners[0], "wins", pot_size,
                      note=f"side pot @{lvl:.1f} -> " + ", ".join(w.name for w in winners))
            prev = lvl

    # ------------------------------------------------------------------ log
    def _log(self, p: Player | None, action: str, amount: float,
             decision: dict | None = None, note: str = "", street: str | None = None,
             position: str = "") -> None:
        self.action_log.append({
            "hand_id": self.hand_id,
            "street": street or getattr(self, "street", "preflop"),
            "seat": p.seat if p else None,
            "name": p.name if p else "",
            "position": position,
            "action": action,
            "amount": round(amount, 2),
            "pot": round(self.pot, 2),
            "note": note,
            "decision": decision,
            "hero": bool(p and p.is_hero),
        })

    def _build_result(self, board, press_showdown: bool, note: str = "") -> HandResult:
        hero = self._seat(self.hero_seat)
        hero_acts = [a for a in self.action_log if a["hero"]]
        winners = [p.name for p in self.players if p.winnings > 0]
        delta = hero.stack - hero.start_stack
        label = ""
        if press_showdown and hero.in_hand and hero.hole and board:
            label = describe_hand(list(hero.hole) + list(board))
        return HandResult(
            hand_id=self.hand_id,
            board=list(board),
            pot=sum(p.winnings for p in self.players),
            players=list(self.players),
            winners=winners,
            hero_seat=self.hero_seat,
            hero_delta=delta,
            hero_stack_after=hero.stack,
            showdown=press_showdown,
            hero_hole=list(hero.hole),
            hero_position=self._label_for(hero.seat),
            hero_actions=hero_acts,
            all_actions=self.action_log,
            hand_label=label,
            result_type="showdown" if press_showdown else "fold-win",
            hero_won=hero.winnings > 0,
            hero_in_hand=hero.in_hand,
        )
