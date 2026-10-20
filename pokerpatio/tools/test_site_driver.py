"""End-to-end test of the site driver against the live (free) singleplayer table."""
import json
import sys
import time

from bot.site import PokerPatioSite
from core.cards import parse_cards, cards_str
from core.strategies import build, Spot

STRATEGY = sys.argv[1] if len(sys.argv) > 1 else "optimal"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 60


def to_spot(st: dict, pol, opp_pct=55.0) -> Spot | None:
    me = st.get("self")
    if not me or len(me["cards"]) != 2:
        return None
    board = parse_cards("".join(st["board"])) if st["board"] else []
    hole = parse_cards("".join(me["cards"]))
    others = [p for p in st["players"] if not p["self"] and p["in_hand"]]
    max_bet = max([p["bet"] for p in st["players"]] + [0.0])
    to_call = max(0.0, max_bet - me["bet"])
    return Spot(
        hole=tuple(hole), board=tuple(board), street=st["street"],
        pot=st["pot"], to_call=to_call, my_stack=me["stack"],
        eff_stack=min([me["stack"]] + [p["stack"] for p in others]) if others else me["stack"],
        position="IP", seat="BTN", n_opponents=max(1, len(others)),
        raises_faced=1 if max_bet > 5 else 0, limpers=0, big_blind=10.0,
        can_check=to_call <= 1e-9, my_invested=me["bet"], bet_level=max_bet,
        min_raise_to=max(st["bar"]["min_bet"] or 20.0, max_bet * 2),
        max_raise_to=me["bet"] + me["stack"],
        opp_pcts=tuple([opp_pct] * max(1, len(others))),
        iters=120, seed=int(time.time() * 1000) % (1 << 30),
    )


site = PokerPatioSite(headless=True)
site.open()
print("starting singleplayer…")
print(site.start_singleplayer("scoutprobe", "easy"))
pol = build(STRATEGY, seed=7)
pol.iters = 120

acted = 0
seen_turns = 0
streets = set()
t0 = time.time()
last_turn_id = None
while time.time() - t0 < SECONDS:
    st = site.observe()
    streets.add(st["street"])
    if st.get("popup"):
        print("POPUP:", st["popup"])
        site.handle_popup()
        time.sleep(1)
        continue
    if not st["my_turn"]:
        time.sleep(0.45)
        continue
    # only act once per turn instance
    key = (st["self"]["bet"], len(st["board"]), st["pot"], st["self"]["stack"])
    spot = to_spot(st, pol)
    if spot is None:
        time.sleep(0.4)
        continue
    decision = pol.decide(spot)
    target = spot.my_invested + decision.amount
    seen_turns += 1
    if decision.action in ("fold", "check", "call"):
        res = site.act(decision.action)
    else:
        res = site.act("raise", target)
    print(f"[{st['street']:7s}] {cards_str(spot.hole)} | {cards_str(spot.board) or '-':12s} "
          f"pot={st['pot']:.0f} call={spot.to_call:.0f} eq={decision.equity:.0%} "
          f"-> {decision.action} {decision.amount:.0f} :: {res}")
    acted += 1
    time.sleep(0.8)

print(f"\nturns handled: {seen_turns}, actions sent: {acted}, streets seen: {sorted(streets)}")
print("final state:", json.dumps({k: site.observe()[k] for k in ("street", "pot", "my_turn")}))
site.screenshot("/tmp/pp_bot_final.png")
site.close()
