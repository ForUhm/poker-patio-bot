"""Optional Playwright runner for a real poker table (the 'dom' adapter path).

The strategy engine is transport-agnostic: this module only has to turn the site's
DOM into a `Spot` and turn a `Decision` into clicks. It is inert until a real
table URL + selectors exist (pokerpatio.net is a parked domain, so the default
mode is 'simulated').

Usage:
    python3 -m bot.dom_runner --url https://host/table/1 --dry-run

Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from core.cards import parse_cards
from core.strategies import STRATEGIES, build
from core.strategies import Spot
from bot.adapter import load_config

RANK_MAP = {"10": "T"}


def read_cards(page, selector: str):
    """Read card elements: supports data-card="As", text 'As', or rank+suit nodes."""
    els = page.query_selector_all(selector)
    out = []
    for el in els:
        raw = (el.get_attribute("data-card") or el.get_attribute("aria-label")
               or el.inner_text() or "").strip()
        raw = raw.replace(" ", "")
        if len(raw) >= 2:
            r = RANK_MAP.get(raw[:-1], raw[:-1])[-1]
            out.append(r + raw[-1].lower())
    try:
        return parse_cards("".join(out))
    except Exception:
        return []


def to_number(txt: str) -> float:
    digits = "".join(ch for ch in (txt or "") if ch.isdigit() or ch == ".")
    try:
        return float(digits)
    except ValueError:
        return 0.0


def build_spot(page, cfg, policy, street_state: dict) -> Spot | None:
    s = cfg["selectors"]
    hole = read_cards(page, s["hero_cards"])
    board = read_cards(page, s["board_cards"])
    if len(hole) != 2:
        return None
    pot = to_number(page.inner_text(s["pot"])) if s["pot"] else 0.0
    to_call = to_number(page.inner_text(s["to_call"])) if s["to_call"] else 0.0
    stack = to_number(page.inner_text(s["stack"])) if s["stack"] else 100.0
    street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(board), "preflop")
    bb = street_state.get("bb", 1.0)
    return Spot(
        hole=tuple(hole), board=tuple(board), street=street, pot=pot,
        to_call=to_call, my_stack=stack, eff_stack=stack,
        position="IP", seat=street_state.get("seat", "BTN"),
        n_opponents=street_state.get("opponents", 1),
        big_blind=bb, can_check=to_call <= 1e-9,
        my_invested=max(0.0, to_call), bet_level=max(to_call, 0.0),
        min_raise_to=max(bb, to_call * 2), max_raise_to=stack,
        iters=220,
    )


def click_action(page, cfg, action: str, amount: float):
    s = cfg["selectors"]
    buttons = page.query_selector_all(s["action_button"])
    want = {"fold": "fold", "check": "check", "call": "call",
            "bet": "bet", "raise": "raise", "allin": "all in"}[action]
    for b in buttons:
        if want in (b.inner_text() or "").lower():
            if action in ("bet", "raise") and s["raise_input"]:
                page.fill(s["raise_input"], str(int(amount)))
            b.click()
            if s["confirm_button"]:
                page.click(s["confirm_button"])
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--strategy", default="optimal", choices=list(STRATEGIES))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if cfg.get("mode") != "dom":
        print("adapter mode is 'simulated' — set mode=dom and selectors first "
              "(POST /api/adapter). Exiting.", file=sys.stderr)
        return 2
    missing = [k for k, v in cfg["selectors"].items() if not v]
    if missing:
        print("missing selectors: " + ", ".join(missing), file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"playwright unavailable: {e}", file=sys.stderr)
        return 2

    policy = build(args.strategy, seed=1)
    policy.iters = 220
    url = args.url or cfg["url"]
    poll = cfg["timing"]["poll_ms"] / 1000.0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(url)
        print(f"attached to {url} — strategy {args.strategy}"
              f"{' (DRY RUN)' if args.dry_run else ''}")
        state = {"bb": 1.0, "opponents": 1, "seat": "BTN"}
        while True:
            spot = build_spot(page, cfg, policy, state)
            if spot is None:
                time.sleep(poll)
                continue
            decision = policy.decide(spot)
            print(f"[{spot.street}] {decision.action} {decision.amount:.2f} :: "
                  f"{decision.rationale}")
            if not (args.dry_run or cfg["safety"]["dry_run"]):
                click_action(page, cfg, decision.action, decision.amount)
            time.sleep(cfg["timing"]["action_delay_ms"] / 1000.0)


if __name__ == "__main__":
    raise SystemExit(main())
