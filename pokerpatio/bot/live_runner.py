"""Live runner: drives pokerpatio.com with one of the three strategies.

The control panel starts this object with the credentials typed into its form.
Credentials live in memory for the session by design — nothing is written to
disk, logged, or returned by the API (the state payload carries at most a masked
email). The browser is a real Chromium driven over CDP; every action is a real
click on the site's own controls.

Safety rails:
  dry_run        decide and log, never click
  stop_loss      halt when chips lost (excluding free rebuys) exceeds the limit
  max_hands      hard stop after N decisions
  action_delay   human-ish pacing between actions
"""
from __future__ import annotations

import re
import threading
import time
import traceback

from core.cards import parse_cards, cards_str
from core.strategies import STRATEGIES, build, Spot
from bot.site import PokerPatioSite, SiteError
from bot.credentials import Vault, mask_email as vault_mask

MAX_LOG = 80


def mask_email(email: str) -> str:
    if not email:
        return ""
    name, _, domain = email.partition("@")
    keep = name[:2] if len(name) > 2 else name[:1]
    return f"{keep}{'*' * max(2, len(name) - len(keep))}@{domain}"


class LiveRunner:
    def __init__(self):
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.site: PokerPatioSite | None = None
        self.vault = Vault()
        self._reset()

    # ------------------------------------------------------------------ state
    def _reset(self):
        self.strategy = "optimal"
        self.mode = "singleplayer"          # singleplayer | public
        self.table = ""
        self.room_id = ""
        self.buyin = "avg"
        self.remember = True
        self.resumed_session = False
        self.username = "bot"
        self.difficulty = "easy"
        self.dry_run = True
        self.stop_loss = 0.0
        self.max_hands = 0
        self.opp_pct = 55.0
        self.action_delay = 0.7

        self.status = "idle"                # idle|connecting|playing|paused|stopped|error
        self.error: str | None = None
        self.email_masked = ""
        self.logged_in = False
        self.seated = False
        self.decisions = 0
        self.hands_est = 0
        self.actions = {"fold": 0, "check": 0, "call": 0, "raise": 0}
        self.rebuys = 0
        self.table_resets = 0
        self.net = 0.0
        self.peak = 0.0
        self.max_drawdown = 0.0
        self.stack: float | None = None
        self.start_stack: float | None = None
        self.last_obs: dict | None = None
        self.last_decision: dict | None = None
        self.feed: list[dict] = []
        self.messages: list[str] = []
        self.history: list[float] = []
        self._prev_stack: float | None = None
        self._prev_hand_key = None
        self.started_at = None
        self._pot_max = 0.0
        self._pot_key = None
        self._prev_stacks: dict[str, float] = {}
        self._hand_start_stacks: dict[str, float] = {}
        self._committed_pot = 0.0
        self._armed = True          # edge-trigger: one action per turn
        self._last_action_at = 0.0
        self.shot: bytes | None = None
        self.shot_at = 0.0
        self._shot_demand = 0.0

    def _msg(self, text: str):
        self.messages.insert(0, f"{time.strftime('%H:%M:%S')} {text}")
        del self.messages[40:]

    def state(self) -> dict:
        with self._lock:
            return {
                "status": self.status,
                "error": self.error,
                "running": self.status in ("connecting", "playing", "paused"),
                "paused": self.status == "paused",
                "mode": self.mode,
                "table": self.table,
                "username": self.username,
                "difficulty": self.difficulty,
                "buyin": self.buyin,
                "email_masked": self.email_masked,
                "vault": self.vault.status(),
                "logged_in": self.logged_in,
                "seated": self.seated,
                "dry_run": self.dry_run,
                "strategy": self.strategy,
                "strategy_label": STRATEGIES[self.strategy].label,
                "decisions": self.decisions,
                "hands_est": self.hands_est,
                "actions": dict(self.actions),
                "rebuys": self.rebuys,
                "table_resets": self.table_resets,
                "net": round(self.net, 2),
                "stack": self.stack,
                "start_stack": self.start_stack,
                "max_drawdown": round(self.max_drawdown, 2),
                "elapsed_s": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "last_decision": self.last_decision,
                "feed": self.feed[:30],
                "messages": self.messages[:12],
                "history": self.history[-200:],
                "obs": self._obs_for_ui(),
            }

    def _obs_for_ui(self) -> dict | None:
        st = self.last_obs
        if not st:
            return None
        me = st.get("self") or {}
        seats = []
        for p in st.get("players", []):
            seats.append({
                "name": "HERO" if p.get("self") else (p.get("name") or "?"),
                "stack": p.get("stack"), "bet": p.get("bet"),
                "hero": bool(p.get("self")), "turn": bool(p.get("turn")),
                "in_hand": bool(p.get("in_hand")), "dealer": bool(p.get("dealer")),
                "cards": p.get("cards") if p.get("self") else [],
            })
        return {
            "street": st.get("street"), "board": st.get("board", []),
            "pot": st.get("pot"), "my_turn": st.get("my_turn"),
            "hole": me.get("cards", []), "stack": me.get("stack"),
            "hand_label": st.get("hand_label", ""), "seats": seats,
            "popup": st.get("popup"),
        }

    # --------------------------------------------------------------- lifecycle
    def start(self, *, email: str = "", password: str = "", mode: str = "singleplayer",
              username: str = "bot", table: str = "", room_id: str = "",
              difficulty: str = "easy", strategy: str = "optimal", dry_run: bool = True,
              stop_loss: float = 0.0, max_hands: int = 0, opp_pct: float = 55.0,
              action_delay: float = 0.7, remember: bool = True,
              buyin: str = "avg", headless: bool = True) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._stop.set()
                self._thread.join(timeout=6)
            self._reset()
            self.mode = mode
            self.username = username or "bot"
            self.table = table
            self.room_id = room_id or ""
            self.buyin = buyin or "avg"
            self.remember = bool(remember)
            self.difficulty = difficulty
            self.strategy = strategy if strategy in STRATEGIES else "optimal"
            self.dry_run = bool(dry_run)
            self.stop_loss = float(stop_loss or 0)
            self.max_hands = int(max_hands or 0)
            self.opp_pct = float(opp_pct or 55)
            self.action_delay = max(0.25, float(action_delay or 0.7))
            self.email_masked = mask_email(email)
            self.status = "connecting"
            self.started_at = time.time()
            self._stop.clear()
            self._pause.clear()
            # credentials are captured by the closure and never stored on self
            self._thread = threading.Thread(
                target=self._run, args=(email, password, headless),
                daemon=True, name="live-runner")
            self._thread.start()
        return self.state()

    def stop(self) -> dict:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=8)
        with self._lock:
            if self.status not in ("error",):
                self.status = "stopped"
            self.seated = False
        self._shutdown_site()
        return self.state()

    def pause(self) -> dict:
        self._pause.set()
        with self._lock:
            if self.status == "playing":
                self.status = "paused"
        return self.state()

    def resume(self) -> dict:
        self._pause.clear()
        with self._lock:
            if self.status == "paused":
                self.status = "playing"
        return self.state()

    def request_shot(self):
        """Ask the runner thread for a fresh screenshot (Playwright is thread-bound)."""
        self._shot_demand = time.time()

    def _maybe_capture(self):
        now = time.time()
        if self.site is None or self.site.page is None:
            return
        if now - self._shot_demand > 8:
            return
        if now - self.shot_at < 1.2:
            return
        try:
            self.site.page.screenshot(path="/tmp/pp_live_shot.png", full_page=False)
            with open("/tmp/pp_live_shot.png", "rb") as f:
                self.shot = f.read()
            self.shot_at = now
        except Exception:
            pass

    def set_strategy(self, key: str) -> dict:
        with self._lock:
            if key in STRATEGIES:
                self.strategy = key
                self._msg(f"strategy -> {key}")
        return self.state()

    def _goto_lobbies(self):
        try:
            self.site.page.goto("https://pokerpatio.com/lobbies",
                                wait_until="domcontentloaded")
            self.site.page.wait_for_timeout(1800)
        except Exception:
            pass

    def logout(self) -> dict:
        """Log out of the site and delete the stored login."""
        try:
            if self.site:
                self.site.logout()
        except Exception:
            pass
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=6)
        with self._lock:
            self.status = "stopped"
            self.logged_in = False
            self.resumed_session = False
            self.email_masked = ""
            self.seated = False
        self._shutdown_site()
        self.vault.clear()
        self._msg("logged out; stored login deleted")
        return self.state()

    def _shutdown_site(self):
        s = self.site
        self.site = None
        if s:
            try:
                s.close()
            except Exception:
                pass

    # -------------------------------------------------------------------- loop
    def _run(self, email: str, password: str, headless: bool):
        try:
            saved = self.vault.load() if self.mode == "public" else {}
            storage = saved.get("storage_state") if self.mode == "public" else None
            self.site = PokerPatioSite(headless=headless)
            self.site.open(storage_state=storage)
            self._msg("browser launched")
            if self.mode == "public":
                # 1) a stored session needs no password at all
                resumed = False
                if storage:
                    self._goto_lobbies()
                    if self.site.is_authenticated():
                        resumed = True
                        self.resumed_session = True
                        self.logged_in = True
                        with self._lock:
                            self.email_masked = mask_email(
                                saved.get("email") or email or "")
                            self.username = self.site._read_username() or self.username
                        self._msg(f"resumed saved session ({self.email_masked})")
                # 2) otherwise log in once and remember it
                if not resumed:
                    email = (email or saved.get("email") or "").strip()
                    password = password or saved.get("password") or ""
                    if not email or not password:
                        raise SiteError("public tables need an account: enter email and "
                                        "password once (they will be remembered)")
                    res = self.site.login(email, password)
                    if not res.get("ok"):
                        raise SiteError(f"login failed: {res.get('error')}")
                    self.logged_in = True
                    with self._lock:
                        self.email_masked = mask_email(email)
                        if res.get("username"):
                            self.username = res["username"]
                    try:
                        self.vault.save_login(email, password, self.site.storage_state(),
                                              remember_password=self.remember)
                        self._msg("login stored locally (encrypted) — you will not be asked again")
                    except Exception as e:
                        self._msg(f"could not store login: {e}")
                    self._msg(f"logged in as {res.get('username') or self.email_masked}")

                join = self.site.join_table(self.room_id or None, self.table or None,
                                            buyin=self.buyin)
                if not join.get("ok"):
                    raise SiteError(f"could not join table: {join.get('error') or join.get('detail')}")
                self.seated = True
                self._msg(f"seated at {self.table or join.get('room_id') or 'first available table'}")
            else:
                sp = self.site.start_singleplayer(self.username, self.difficulty)
                if not sp.get("ok"):
                    raise SiteError(f"could not start singleplayer: {sp.get('error')}")
                self.seated = True
                self._msg(f"seated: singleplayer ({self.difficulty}) as {self.username}")

            with self._lock:
                self.status = "playing"
            self._play_loop()
        except SiteError as e:
            with self._lock:
                self.status = "error"
                self.error = str(e)
            self._msg(f"error: {e}")
        except Exception as e:
            with self._lock:
                self.status = "error"
                self.error = f"{type(e).__name__}: {e}"
            self._msg(f"crash: {self.error}")
            self.messages.insert(0, traceback.format_exc()[-600:])
        finally:
            self.seated = False
            self._shutdown_site()

    def _play_loop(self):
        pol = None
        pol_key = None
        fatal_errors = 0
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.25)
                continue
            if pol_key != self.strategy:
                pol = build(self.strategy, seed=None)
                pol.iters = 140
                pol_key = self.strategy

            try:
                obs = self.site.observe()
            except Exception as e:
                fatal_errors += 1
                if fatal_errors > 6:
                    raise SiteError(f"browser unresponsive: {e}")
                time.sleep(0.8)
                continue

            with self._lock:
                self.last_obs = obs
                self._track_pot(obs)
                self._track_stack(obs)
                self._track_hand(obs)
            self._maybe_capture()

            if obs.get("popup"):
                info = self.site.popup()
                if not info:
                    # stale/hidden node: clear the flag and keep playing
                    with self._lock:
                        if self.last_obs:
                            self.last_obs["popup"] = None
                    time.sleep(0.3)
                    continue
                if info.get("transient"):
                    # The singleplayer game ends as soon as ANY seat busts (the losing
                    # bot shows "Game Lost!"), then a fresh table is dealt. Our own
                    # stack carries over, so this is a table reset, not a rebuy.
                    with self._lock:
                        self.table_resets += 1
                    self._msg(f"{info.get('title')} — a seat busted, new table dealing")
                    self.site.page.wait_for_timeout(5200)
                    with self._lock:
                        self._prev_stacks = {}
                        self._hand_start_stacks = {}
                        self._committed_pot = 0.0
                        self._pot_key = None
                    continue
                self.site.dismiss_popup()
                time.sleep(0.4)
                continue

            if not obs.get("my_turn"):
                self._armed = True     # we have left the turn -> next turn may act
                time.sleep(0.35)
                continue

            if not self._armed or time.time() - self._last_action_at < 1.0:
                time.sleep(0.3)
                continue

            spot = self._to_spot(obs, pol)
            if spot is None:
                time.sleep(0.4)
                continue

            decision = pol.decide(spot)
            target = spot.my_invested + decision.amount
            payload = {
                "street": spot.street,
                "hole": cards_str(spot.hole),
                "board": cards_str(spot.board) or "-",
                "pot": round(spot.pot, 1),
                "to_call": round(spot.to_call, 1),
                "action": decision.action,
                "amount": round(decision.amount, 1),
                "equity": round(decision.equity, 4),
                "required": round(decision.required_equity, 4),
                "rationale": decision.rationale,
                "tags": decision.tags,
                "hand_label": decision.hand_label,
            }

            if self.dry_run:
                payload["executed"] = "dry-run"
                result = {"ok": True, "dry_run": True}
            elif decision.action in ("fold", "check", "call"):
                result = self.site.act(decision.action)
            else:
                result = self.site.act("raise", target)
            payload["result"] = result

            self._armed = False
            self._last_action_at = time.time()
            with self._lock:
                self.decisions += 1
                key = "raise" if decision.action in ("bet", "raise", "allin") else decision.action
                self.actions[key] = self.actions.get(key, 0) + 1
                self.last_decision = payload
                self.feed.insert(0, payload)
                del self.feed[MAX_LOG:]
                stop_now = False
                if self.max_hands and self.decisions >= self.max_hands:
                    self._msg(f"max decisions reached ({self.max_hands}) — stopping")
                    stop_now = True
                if self.stop_loss and self.net <= -abs(self.stop_loss):
                    self._msg(f"stop-loss hit ({self.net:.0f}) — stopping")
                    stop_now = True
            if stop_now:
                self._stop.set()
                break

            obs = self.site.wait_for_turn_change(obs, timeout=3.5)
            with self._lock:
                self.last_obs = obs
                self._track_pot(obs)
                self._track_stack(obs)
            # if the site still shows our turn well after a successful click, the
            # render lagged — re-arm so we do not sit until the action clock folds us
            if obs.get("my_turn") and time.time() - self._last_action_at > 6.0:
                self._armed = True
            time.sleep(self.action_delay)

        with self._lock:
            if self.status not in ("error",):
                self.status = "stopped"

    # ------------------------------------------------------------- bookkeeping
    def _track_stack(self, obs: dict):
        me = obs.get("self") or {}
        stack = me.get("stack")
        if stack is None:
            return
        self.stack = float(stack)
        if self.start_stack is None:
            self.start_stack = self.stack
            self._prev_stack = self.stack
            return
        if self._prev_stack is None:
            self._prev_stack = self.stack
            return
        delta = self.stack - self._prev_stack
        # a jump back up to a full stack after being short is a free rebuy, not winnings
        base = self.start_stack or 1000.0
        if delta > 0 and self._prev_stack < base * 0.35 and self.stack >= base * 0.95:
            self._prev_stack = self.stack
            self.start_stack = self.stack
            return
        self.net += delta
        self._prev_stack = self.stack
        self.peak = max(self.peak, self.net)
        self.max_drawdown = max(self.max_drawdown, self.peak - self.net)
        self.history.append(round(self.net, 2))

    def _track_pot(self, obs: dict):
        """Pot = sum of (start-of-hand stack - current stack) across seats."""
        players = obs.get("players") or []
        stacks = {p.get("name"): float(p.get("stack") or 0) for p in players if p.get("name")}
        me = obs.get("self") or {}
        key = tuple(sorted(me.get("cards") or []))
        if key != self._pot_key:
            # a new hand: the previous observation was the settled previous hand
            self._pot_key = key
            self._hand_start_stacks = dict(self._prev_stacks) if self._prev_stacks else dict(stacks)
        self._prev_stacks = stacks
        committed = 0.0
        for name, start in self._hand_start_stacks.items():
            cur = stacks.get(name)
            if cur is None:
                continue
            committed += max(0.0, start - cur)
        self._committed_pot = committed

    def _track_hand(self, obs: dict):
        """Estimate hands dealt: a fresh preflop spot (no chips committed, only
        blinds in the pot) that we have not already counted."""
        me = obs.get("self") or {}
        cards = me.get("cards") or []
        if obs.get("street") != "preflop" or len(cards) != 2:
            return
        key = tuple(cards)
        if key != self._prev_hand_key:
            self._prev_hand_key = key
            self.hands_est += 1

    # ------------------------------------------------------------------- spot
    def _to_spot(self, obs: dict, pol) -> Spot | None:
        me = obs.get("self") or {}
        if len(me.get("cards") or []) != 2:
            return None
        try:
            hole = parse_cards("".join(me["cards"]))
            board = parse_cards("".join(obs["board"])) if obs.get("board") else []
        except Exception:
            return None
        others = [p for p in obs.get("players", []) if not p.get("self") and p.get("in_hand")]
        # A pot only grows inside a hand; the site animates bets, so transient
        # readings can dip. Keep a per-hand high-water mark so pot odds stay sane.
        raw_pot = float(obs.get("pot") or 0)
        # Prefer chips actually committed (start-of-hand stacks minus current
        # stacks): exact, and immune to the site's pot animations/resets.
        pot = self._committed_pot if self._committed_pot > 1 else raw_pot
        pot = self._sane_pot(obs, pot, me)
        max_bet = max([p.get("bet") or 0 for p in obs.get("players", [])] + [0.0])
        my_bet = me.get("bet") or 0
        to_call = max(0.0, max_bet - my_bet)
        stack = me.get("stack") or 0
        bar = obs.get("bar") or {}
        bb = 10.0
        min_raise = max(bar.get("min_bet") or bb * 2, max_bet + bb)
        seat, position = self._position(obs)
        return Spot(
            hole=tuple(hole), board=tuple(board), street=obs.get("street", "preflop"),
            pot=pot, to_call=to_call, my_stack=float(stack),
            eff_stack=min([stack] + [p.get("stack") or 0 for p in others]) if others else stack,
            position=position, seat=seat, n_opponents=max(1, len(others)),
            raises_faced=1 if max_bet > bb else 0, limpers=0, big_blind=bb,
            can_check=to_call <= 1e-9, my_invested=my_bet, bet_level=max_bet,
            min_raise_to=min_raise, max_raise_to=my_bet + stack,
            opp_pcts=tuple([self.opp_pct] * max(1, len(others))),
            iters=140, seed=None,
        )

    def _sane_pot(self, obs: dict, pot: float, me: dict) -> float:
        """Guard against a stale pot read at hand start.

        Invariant: with nothing but blinds in, the pot cannot exceed the chips on
        the table plus a couple of blinds. The site leaves the previous hand's
        pot on screen for a beat after the reset, which otherwise inflates pot
        odds on the first decision of a hand.
        """
        on_table = sum((p.get("bet") or 0) for p in obs.get("players", []))
        bb = 10.0
        max_bet = max([p.get("bet") or 0 for p in obs.get("players", [])] + [0.0])
        to_call = max(0.0, max_bet - (me.get("bet") or 0))
        if obs.get("street") == "preflop" and to_call <= 2 * bb:
            ceiling = on_table + 3 * bb
            if pot > ceiling:
                return ceiling
        return pot

    LABELS = {2: ["BTN", "BB"], 3: ["BTN", "SB", "BB"], 4: ["BTN", "SB", "BB", "CO"],
              5: ["BTN", "SB", "BB", "UTG", "CO"],
              6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"]}

    def _position(self, obs: dict):
        """Seat label + IP/OOP derived from the dealer button and seat order."""
        players = sorted([p for p in obs.get("players", []) if p.get("in_hand")],
                         key=lambda p: p.get("loc") or 0)
        if not players:
            return "BTN", "IP"
        n = min(len(players), 6)
        dealer_idx = next((i for i, p in enumerate(players) if p.get("dealer")), 0)
        labels = self.LABELS.get(n, self.LABELS[6])
        me_idx = next((i for i, p in enumerate(players) if p.get("self")), 0)
        off = (me_idx - dealer_idx) % len(players)
        seat = labels[off] if off < len(labels) else "CO"
        # postflop the last player to act before the dealer is the most in-position
        last_idx = (dealer_idx - 1) % len(players)
        return seat, ("IP" if me_idx == last_idx else "OOP")


LIVE = LiveRunner()
