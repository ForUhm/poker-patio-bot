"""PokerPatio DOM driver — the real, verified selector contract.

Discovered live on 2026-10-20 against https://pokerpatio.com (free-to-play,
virtual chips). Selectors below were read off the running game, not guessed:

  login form        form[action$='/login']  input[name=email]  input[name=password]
                    .btn[type=submit] / button "Log in"
  lobby row         .lobby-row / row containing a "Join" control (see join_table)
  self seat         .player.is-this-player
  whose turn        .player.is-this-player.active-turn
  player            #players .player  (data-player-id, data-pos-type, data-seat-location-id)
                    .name .stack .stage-bets .player-icons .icon.dealer .hand .card
  card              .card.<spades|hearts|diamonds|clubs>.val-<2..10|J|Q|K|A>
                    data-face-up="true" for visible cards
  board             #communityCards .card
  pot               .pot-total[data-total-stage-pot="+ $45"]  and  .side-pot[data-side-pot]
  action bar        .actions[data-min-bet="20"]
                    fold / call / check (hidden when facing a bet) /
                    open_raise -> .set-raise-amount (custom_raise_amount) -> raise
                    quick amounts: min | half_pot | 3_qtr_pot | full_pot | max

Ethics note enforced in code: only `data-face-up="true"` cards are read. The site
does render opponents' card classes while their backs are shown; reading them
would be cheating, so `_read_cards` filters on the face-up flag.
"""
from __future__ import annotations

import re
import time

BASE = "https://pokerpatio.com"
CHROME_CANDIDATES = ("/usr/bin/chromium", "/usr/bin/chromium-browser",
                     "/usr/bin/google-chrome", "/snap/bin/chromium")

SUIT_MAP = {"spades": "s", "hearts": "h", "diamonds": "d", "clubs": "c"}
RANK_MAP = {"10": "T", "j": "T", "q": "Q", "k": "K", "a": "A"}


class SiteError(RuntimeError):
    pass


def _parse_card_class(cls: str) -> str | None:
    if "card" not in cls:
        return None
    suit = next((v for k, v in SUIT_MAP.items() if k in cls), None)
    m = re.search(r"val-([0-9a-zA-Z]+)", cls)
    if not suit or not m:
        return None
    raw = m.group(1)
    if raw.isdigit():
        r = raw if raw != "10" else "T"
        if not (2 <= int(raw) <= 14):
            return None
    else:
        up = raw.upper()
        r = {"J": "J", "Q": "Q", "K": "K", "A": "A", "T": "T"}.get(up)
        if not r:
            return None
    return r + suit


def _money(text: str) -> float:
    if not text:
        return 0.0
    digits = re.sub(r"[^0-9.]", "", str(text))
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


class PokerPatioSite:
    """One browser session against pokerpatio.com."""

    def __init__(self, headless: bool = True, chromium: str | None = None,
                 viewport=(1440, 900), timeout_ms: int = 45000):
        self.headless = headless
        self.chromium = chromium or self._find_chrome()
        self.viewport = viewport
        self.timeout_ms = timeout_ms
        self._pw = None
        self.browser = None
        self.page = None
        self.logged_in = False
        self.username = None
        self.events: list[str] = []

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _find_chrome() -> str:
        import os
        for c in CHROME_CANDIDATES:
            if os.path.exists(c):
                return c
        raise SiteError("no chromium binary found; install chromium or pass chromium=")

    def open(self, storage_state: dict | None = None):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            executable_path=self.chromium, headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
            env={"TMPDIR": "/tmp", "HOME": "/tmp"},
        )
        ctx_kwargs = dict(
            viewport={"width": self.viewport[0], "height": self.viewport[1]},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
        )
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        ctx = self.browser.new_context(**ctx_kwargs)
        self.page = ctx.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        self._ctx = ctx
        self._new_pages: list = []
        ctx.on("page", lambda pg: self._new_pages.append(pg))
        self.page.on("popup", lambda pg: self._new_pages.append(pg))
        return self

    def storage_state(self) -> dict | None:
        """Cookies/localStorage for the vault — written after a successful login."""
        try:
            return self.page.context.storage_state()
        except Exception:
            return None

    def logout(self) -> dict:
        """End the site session server-side as well as locally."""
        try:
            self._goto("/logout", 1200)
            self.logged_in = False
            self.username = None
            return {"ok": True, "url": self.page.url}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.browser = self.page = None
        self.logged_in = False

    def _goto(self, path: str, wait: int = 1800):
        self.page.goto(BASE + path, wait_until="domcontentloaded")
        self.page.wait_for_timeout(wait)

    # ------------------------------------------------------------------ login
    def login(self, email: str, password: str) -> dict:
        """Submit the site's login form. Credentials are never logged or returned."""
        if self.page is None:
            self.open()
        self._goto("/login", 1500)
        try:
            self.page.fill('input[name="email"]', email, timeout=15000)
            self.page.fill('input[name="password"]', password, timeout=15000)
        except Exception as e:
            return {"ok": False, "error": f"login form not found: {e}"}

        clicked = False
        for sel in ("form[action$='/login'] button[type=submit]",
                    "form[action$='/login'] input[type=submit]",
                    "button:has-text('Log in')",
                    ".btn:has-text('Log in')"):
            try:
                if self.page.locator(sel).count():
                    self.page.locator(sel).first.click(timeout=8000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            try:
                self.page.press('input[name="password"]', "Enter")
                clicked = True
            except Exception:
                pass

        self.page.wait_for_timeout(4000)
        return self._login_result(email)

    def is_authenticated(self) -> bool:
        """The nav bar is the honest signal: guests see 'Log in' + 'Sign up',
        members see 'Log out' + a profile link. Both sets ship in the HTML, so
        only *visible* nodes count."""
        try:
            return bool(self.page.evaluate(r"""() => {
                const vis = (e) => e && e.offsetParent !== null;
                const nodes = [...document.querySelectorAll('a,button,div')];
                const txt = (e) => (e.textContent || '').trim().toLowerCase();
                const login = nodes.some(e => vis(e) && (txt(e) === 'log in' || txt(e) === 'login'));
                const logout = nodes.some(e => vis(e) && txt(e) === 'log out');
                const profile = nodes.some(e => vis(e) && /\/profile\//.test(e.getAttribute('href') || ''));
                return (logout || profile) && !login;
            }"""))
        except Exception:
            return False

    def _login_result(self, email: str) -> dict:
        page = self.page
        url = page.url
        try:
            body = page.inner_text("body")[:4000]
        except Exception:
            body = ""
        low = body.lower()
        logged_in = self.is_authenticated()
        if not logged_in:
            err = ""
            for pat in (r"(invalid[^\n]{0,80})", r"(incorrect[^\n]{0,80})",
                        r"(wrong[^\n]{0,80})", r"(required[^\n]{0,80})",
                        r"(not found[^\n]{0,60})"):
                m = re.search(pat, low)
                if m:
                    err = m.group(1).strip()
                    break
            return {"ok": False, "url": url,
                    "error": err or "login rejected (check the email and password)"}
        self.logged_in = True
        self.username = self._read_username()
        self.events.append(f"login ok url={url}")
        return {"ok": True, "url": url, "username": self.username, "error": None}

    def _read_username(self) -> str | None:
        try:
            return self.page.evaluate("""() => {
                const vis = (e) => e && e.offsetParent !== null;
                const prof = [...document.querySelectorAll('a[href*="/profile/"]')].find(vis);
                if (prof) {
                    const t = (prof.textContent || '').trim();
                    if (t && t.length < 24) return t;
                }
                const el = [...document.querySelectorAll('.user-name,.username,[data-username]')].find(vis);
                if (el) return (el.textContent || '').trim() || el.dataset.username;
                return null;
            }""")
        except Exception:
            return None

    def is_logged_in(self) -> bool:
        try:
            return bool(self.page.evaluate("""() => [...document.querySelectorAll('a')]
                .some(a => /\\/logout$/.test(a.getAttribute('href')||''))"""))
        except Exception:
            return False

    # ------------------------------------------------------------------ table
    def start_singleplayer(self, username: str, difficulty: str = "easy") -> dict:
        """Free-play table vs the site's bots — no account required."""
        self._goto("/sp", 2500)
        try:
            self.page.fill('input[name="set_username"]', username)
            self.page.click(f'.difficulty-choice[data-type="{difficulty}"]')
            self.page.wait_for_timeout(300)
            self.page.click('.btn[data-action-type="set_username_join_lobby"]')
        except Exception as e:
            return {"ok": False, "error": f"could not start singleplayer: {e}"}
        self.page.wait_for_timeout(6000)
        ok = self.page.evaluate("() => !!document.querySelector('#players .player')")
        self.events.append(f"singleplayer started as {username} ({difficulty})")
        return {"ok": bool(ok), "username": username, "difficulty": difficulty,
                "error": None if ok else "table did not load"}

    LOBBY_JS = r"""
    () => {
      const num = (t) => {
        const d = (t||'').replace(/[^0-9.]/g,'');
        return d ? Number(d) : null;
      };
      const rows = [...document.querySelectorAll('tr.lobby-table')];
      return rows.map(tr => {
        const nameEl = tr.querySelector('.table-name');
        const joinEl = tr.querySelector('[data-action-type="attempt_open_table"]');
        const playersTxt = (tr.querySelector('.table-players')?.textContent || '').trim();
        const pMatch = playersTxt.match(/(\d+)\s*\/\s*(\d+)/);
        const stakesTxt = (tr.querySelector('.table-stakes')?.textContent || '').trim();
        const sMatch = stakesTxt.match(/([\d,]+)\s*\/\s*([\d,]+)/);
        return {
          room_id: tr.dataset.roomId || joinEl?.dataset.type || '',
          name: (nameEl?.textContent || '').replace(/\s+/g,' ').trim(),
          members_only: !!(nameEl && nameEl.querySelector('.icon')),
          players: pMatch ? Number(pMatch[1]) : null,
          seats: pMatch ? Number(pMatch[2]) : null,
          players_text: playersTxt.replace(/\s+/g,''),
          stakes: stakesTxt.replace(/\s+/g,''),
          sb: sMatch ? num(sMatch[1]) : null,
          bb: sMatch ? num(sMatch[2]) : null,
          avg_pot: num(tr.querySelector('.table-avg-pot')?.textContent),
          avg_stack: num(tr.querySelector('.table-avg-stack')?.textContent),
          filled: !!(tr.querySelector('.table-players')?.className || '').includes('text-orange'),
        };
      });
    }"""

    def lobby_tables(self) -> list[dict]:
        """The same rows the site's own lobby table renders."""
        self._goto("/lobbies", 3200)
        try:
            self.page.wait_for_selector("tr.lobby-table", timeout=15000)
        except Exception:
            pass
        tables = self.page.evaluate(self.LOBBY_JS) or []
        tables.sort(key=lambda t: (t.get("players") or 0), reverse=True)
        return tables

    # --------------------------------------------------------------- seating
    def _adopt_page(self, pg) -> bool:
        if pg is None or pg is self.page:
            return False
        try:
            if pg.is_closed():
                return False
            pg.set_default_timeout(self.timeout_ms)
            self.page = pg
            return True
        except Exception:
            return False

    def open_game_page(self, room_id: str) -> dict:
        """Open the table's game page, reusing the popup the lobby spawns."""
        self._new_pages.clear()
        url = f"{BASE}/pg?game={room_id}&auto_seat=true"
        deadline = time.time() + 9
        while time.time() < deadline and not self._new_pages:
            self.page.wait_for_timeout(300)
        adopted = False
        for pg in list(self._new_pages):
            if self._adopt_page(pg):
                adopted = True
                break
        if not adopted:
            try:
                self.page.goto(url, wait_until="domcontentloaded")
            except Exception as e:
                return {"ok": False, "error": f"could not open game page: {e}"}
        try:
            self.page.wait_for_selector(".player, .actions", timeout=20000)
        except Exception:
            pass
        self.page.wait_for_timeout(1500)
        return {"ok": True, "url": self.page.url, "via_popup": adopted}

    def take_seat(self, buyin: str = "avg") -> dict:
        """Click a 'SIT' button, accept the buy-in dialog, wait to be dealt in."""
        popup = None
        for _ in range(30):
            if self.page.evaluate("() => !!document.querySelector('.player.is-this-player')"):
                seat = self.page.evaluate(
                    "() => document.querySelector('.player.is-this-player')?.dataset.seatLocationId")
                return {"ok": True, "seat": seat}

            info = self.popup()
            if info and info.get("title"):
                title = (info.get("title") or "").lower()
                popup = info.get("title")
                if "buy-in" in title or "buy in" in title or "buyin" in title:
                    done = self._accept_buyin(buyin)
                    self.page.wait_for_timeout(1600)
                    if not done.get("ok"):
                        return done
                    continue
                if any(k in title for k in ("not enough", "full", "error", "banned", "blocked")):
                    return {"ok": False, "error": info.get("title")}
                if info.get("buttons"):
                    self.dismiss_popup()
                    self.page.wait_for_timeout(900)
                    continue

            sit = self.page.locator('[data-action-type="request_seat_join"]')
            n = sit.count() if sit else 0
            clicked = False
            for i in range(min(n, 10)):
                btn = sit.nth(i)
                try:
                    if btn.is_visible():
                        btn.click(timeout=4000)
                        clicked = True
                        self.page.wait_for_timeout(1400)
                        break
                except Exception:
                    continue
            if not clicked:
                self.page.wait_for_timeout(900)
            else:
                self.page.wait_for_timeout(600)

        return {"ok": False,
                "error": f"could not take a seat ({popup or 'no SIT button responded'})",
                "detail": self.page.url}

    def _accept_buyin(self, mode: str = "avg") -> dict:
        """The chips_buy_in dialog: min/avg/max/100BB quick buttons + Join Table."""
        page = self.page
        try:
            if mode in ("min", "avg", "max"):
                q = page.locator(f'[data-action-type="quick_chips_amount"][data-type="{mode}"]')
                if q.count():
                    q.first.click(timeout=4000)
                    page.wait_for_timeout(400)
            elif str(mode).replace(".", "", 1).isdigit():
                inp = page.locator("input.set-chips-amount").first
                if inp.count():
                    inp.click(timeout=3000)
                    page.keyboard.press("Control+A")
                    inp.fill(str(int(float(mode))))
                    page.wait_for_timeout(400)
            btn = page.locator('[data-action-type="buy_in"]').first
            if not btn.count():
                return {"ok": False, "error": "buy-in dialog has no confirm button"}
            amount = page.evaluate(
                "() => document.querySelector('input.set-chips-amount')?.value || null")
            btn.click(timeout=6000)
            return {"ok": True, "buyin": amount, "mode": mode}
        except Exception as e:
            return {"ok": False, "error": f"buy-in failed: {e}"}

    def join_table(self, room_id: str | None = None, name: str | None = None,
                   buyin: str = "avg") -> dict:
        """Lobby -> Join -> game page -> SIT -> buy-in -> seated.

        Clicking Join does not seat you: the site opens `/pg?game=<room>&auto_seat=true`
        in a new tab whose seat buttons say "SIT". Auto-seat only loads the table,
        the SIT click is what actually deals you in.
        """
        self._goto("/lobbies", 3000)
        if not self.is_authenticated():
            return {"ok": False, "error": "not logged in — public tables need an account"}

        tables = self.page.evaluate(self.LOBBY_JS) or []
        target = None
        if room_id:
            target = next((t for t in tables if t.get("room_id") == room_id), None)
        if target is None and name:
            target = next((t for t in tables if name.lower() in (t.get("name") or "").lower()), None)
        if target is None:
            target = next((t for t in tables if (t.get("players") or 0) < (t.get("seats") or 99)), None)
        if target is None:
            return {"ok": False, "error": "no joinable table found in the lobby"}

        room = target.get("room_id")
        players, seats = target.get("players") or 0, target.get("seats") or 0
        if seats and players >= seats:
            return {"ok": False, "room_id": room, "name": target.get("name"),
                    "error": f"{target.get('name')} is full ({players}/{seats}) — pick another table"}

        sel = f'[data-action-type="attempt_open_table"][data-type="{room}"]'
        if self.page.locator(sel).count():
            try:
                self.page.locator(sel).first.click(timeout=8000)
            except Exception:
                pass

        opened = self.open_game_page(room)
        if not opened.get("ok"):
            return {"ok": False, "room_id": room, "name": target.get("name"),
                    "error": opened.get("error")}

        seat = self.take_seat(buyin)
        if not seat.get("ok"):
            return {"ok": False, "room_id": room, "name": target.get("name"),
                    "error": seat.get("error"), "detail": seat.get("detail")}

        self.seated = True
        self.events.append(f"seated at {target.get('name')} (room {room})")
        return {"ok": True, "room_id": room, "name": target.get("name"),
                "seat": seat.get("seat"), "players": players, "seats": seats,
                "via_popup": opened.get("via_popup")}

    def lobby_list(self) -> list[dict]:
        return self.lobby_tables()

    # ---------------------------------------------------------------- observe
    STATE_JS = r"""
    () => {
      const money = (t) => { const d = (t||'').replace(/[^0-9.]/g,''); return d ? parseFloat(d) : 0; };
      const cardOf = (el) => {
        if (!el || el.dataset.faceUp !== 'true') return null;
        const cls = el.className;
        const suit = ['spades','hearts','diamonds','clubs'].find(s => cls.includes(s));
        const m = cls.match(/val-([0-9a-zA-Z]+)/);
        if (!suit || !m) return null;
        const raw = m[1];
        let rank;
        if (/^\d+$/.test(raw)) rank = raw === '10' ? 'T' : raw;
        else rank = raw.toUpperCase().replace('10','T');
        return rank + ({spades:'s',hearts:'h',diamonds:'d',clubs:'c'}[suit]);
      };
      const self = document.querySelector('.player.is-this-player');
      const players = [...document.querySelectorAll('#players .player')].map(p => ({
        id: p.dataset.playerId,
        loc: parseInt(p.dataset.seatLocationId || '0', 10),
        pos: p.dataset.posType,
        self: p.classList.contains('is-this-player'),
        turn: p.classList.contains('active-turn'),
        in_hand: p.classList.contains('playing'),
        name: (p.querySelector('.name')?.textContent || '')
              .replace(/Leaving room\.*/i, '').trim(),
        stack: money(p.querySelector('.stack')?.textContent),
        bet: money(p.querySelector('.stage-bets')?.textContent),
        dealer: !!p.querySelector('.player-icons .icon.dealer, .icon.dealer'),
        cards: [...p.querySelectorAll('.hand .card')].map(cardOf).filter(Boolean),
        best: (p.querySelector('.best-hand')?.textContent || '').trim(),
        folded: !p.classList.contains('playing')
      }));
      const board = [...document.querySelectorAll('#communityCards .card')]
        .map(cardOf).filter(Boolean);
      // POT: `.pot-total span` is the *collected* pot (chips already swept in),
      // `data-total-stage-pot` is only this street's delta and is unreliable
      // mid-street. True pot = collected + chips currently on the table.
      const potEl = document.querySelector('.pot-total');
      const potCollected = money(potEl?.querySelector('span')?.textContent)
                        || money(potEl?.textContent);
      const onTable = players.reduce((s, p) => s + (p.bet || 0), 0);
      const pot = potCollected + onTable;
      const bar = document.querySelector('.actions');
      const visible = (sel) => { const e = document.querySelector(sel); return !!(e && e.offsetParent); };
      const btnText = (sel) => (document.querySelector(sel)?.textContent || '').trim();
      return {
        url: location.href,
        players, board, pot,
        pot_collected: potCollected,
        pot_on_table: onTable,
        self: players.find(p => p.self) || null,
        my_turn: !!(self && self.classList.contains('active-turn')),
        hand_label: (self?.querySelector('.best-hand')?.textContent || '').trim(),
        bar: {
          present: !!bar,
          min_bet: money(bar?.dataset.minBet),
          fold: visible('.actions [data-action-type="fold"]') && !document.querySelector('.actions [data-action-type="fold"]').classList.contains('not-displayed'),
          check: visible('.actions [data-action-type="check"]'),
          call: visible('.actions [data-action-type="call"]'),
          call_text: btnText('.actions [data-action-type="call"]'),
          open_raise: !!document.querySelector('.actions [data-action-type="open_raise"]'),
          raise_visible: visible('.actions [data-action-type="raise"]'),
          raise_text: btnText('.actions [data-action-type="raise"]'),
          amount_input: !!document.querySelector('.set-raise-amount'),
          amount_value: (document.querySelector('.set-raise-amount')?.value || null),
          slider_max: (() => { const s = document.querySelector('input.slider[data-type="raise_amount"]'); return s ? Number(s.max) : null; })(),
          name_input: !document.querySelector('input[name="set_username"]')
        },
        popup: (() => {
          const p = [...document.querySelectorAll('.popup-holder')]
              .find(el => el.offsetParent !== null);
          return p ? ((p.querySelector('.title')?.textContent || '').trim() || 'popup') : null;
        })(),
        street: board.length === 0 ? 'preflop' : board.length === 3 ? 'flop'
                : board.length === 4 ? 'turn' : board.length === 5 ? 'river' : 'preflop'
      };
    }"""

    def observe(self) -> dict:
        if not self.page:
            raise SiteError("browser not open")
        return self.page.evaluate(self.STATE_JS)

    # ------------------------------------------------------------------- act
    def act(self, action: str, amount: float = 0.0) -> dict:
        """action: fold | check | call | raise. `amount` = total street commitment to raise TO."""
        page = self.page
        if action == "raise":
            return self._raise(float(amount))

        sel = {
            "fold": '.actions [data-action-type="fold"]',
            "check": '.actions [data-action-type="check"]',
            "call": '.actions [data-action-type="call"]',
        }.get(action)
        if not sel:
            return {"ok": False, "error": f"unknown action {action}"}

        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=6000)
                page.wait_for_timeout(300)
                return {"ok": True, "action": action}
        except Exception:
            pass

        # Nothing to call -> the site hides CHECK and treats FOLD as a check
        # (the fold control carries data-sub-type="check_if_unnecessary").
        if action == "check":
            try:
                fb = page.locator('.actions [data-action-type="fold"]').first
                if fb.count() and fb.is_visible():
                    fb.click(timeout=6000)
                    page.wait_for_timeout(300)
                    return {"ok": True, "action": "check", "via": "fold-check-if-unnecessary"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"{action} control not available"}

    def wait_for_turn_change(self, prev: dict, timeout: float = 3.0) -> dict:
        """Block until our turn ends or the table state visibly advances."""
        key = self._fp(prev)
        deadline = time.time() + timeout
        last = prev
        while time.time() < deadline:
            last = self.observe()
            if not last.get("my_turn") or self._fp(last) != key:
                return last
            time.sleep(0.18)
        return last

    @staticmethod
    def _fp(st: dict) -> tuple:
        me = st.get("self") or {}
        return (st.get("street"), st.get("pot"), len(st.get("board") or []),
                me.get("bet"), me.get("stack"), bool(st.get("my_turn")),
                tuple(sorted((p.get("name", ""), p.get("bet")) for p in st.get("players", []))))

    def _raise(self, total: float) -> dict:
        page = self.page
        try:
            if not page.locator('.actions [data-action-type="raise"]').count() or \
                    not page.locator('.actions [data-action-type="raise"]').first.is_visible():
                if page.locator('.actions [data-action-type="open_raise"]').count():
                    page.locator('.actions [data-action-type="open_raise"]').first.click(timeout=6000)
                    page.wait_for_timeout(450)
        except Exception as e:
            return {"ok": False, "error": f"could not open raise panel: {e}"}

        try:
            inp = page.locator('.set-raise-amount').first
            if not inp.count():
                return {"ok": False, "error": "no raise amount input"}
            target = max(1, int(round(total)))
            inp.click(timeout=4000)
            page.keyboard.press("Control+A")
            inp.fill(str(target))
            page.wait_for_timeout(350)
            actual = page.evaluate(
                "() => Number(document.querySelector('.set-raise-amount')?.value || 0)")
            btn = page.locator('.actions [data-action-type="raise"]').first
            if not btn.count() or not btn.is_visible():
                return {"ok": False, "error": "raise button missing", "requested": target}
            btn.click(timeout=6000)
            page.wait_for_timeout(400)
            return {"ok": True, "action": "raise", "requested": target,
                    "accepted": actual}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def screenshot(self, path: str) -> str:
        self.page.screenshot(path=path, full_page=False)
        return path

    def popup(self) -> dict | None:
        """Describe any blocking popup, including the transient game-end one."""
        try:
            return self.page.evaluate(r"""() => {
                const p = [...document.querySelectorAll('.popup-holder')]
                    .find(el => el.offsetParent !== null);
                if (!p) return null;
                const title = (p.querySelector('.title')?.textContent || '').trim();
                const transient = /next hand starting|starting\.\.\./i.test(p.innerText || '');
                const buttons = [...p.querySelectorAll('[data-action-type], .btn, button')]
                    .filter(b => b.offsetParent)
                    .map(b => ({ t: b.dataset.actionType || null,
                                 txt: (b.textContent||'').trim().slice(0, 20) }));
                return { title, transient, type: p.dataset.type || null, buttons };
            }""")
        except Exception:
            return None

    def dismiss_popup(self) -> dict | None:
        """Click a real dismiss control if the popup has one. Transient popups
        (game end -> next hand) have no buttons and clear themselves."""
        info = self.popup()
        if not info:
            return None
        if info["transient"] or not info["buttons"]:
            return info
        for want in ("close_popup", "close", "ok", "continue", "rebuy",
                     "play_again", "new_game", "start_new_game"):
            for b in info["buttons"]:
                if (b["t"] or "").lower() == want or want in (b["txt"] or "").lower():
                    try:
                        self.page.locator(
                            f'.popup-holder [data-action-type="{b["t"]}"]'
                        ).first.click(timeout=4000)
                        self.page.wait_for_timeout(400)
                        return info
                    except Exception:
                        continue
        return info
