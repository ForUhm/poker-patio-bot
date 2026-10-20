"""Verify the two-step join: Join -> Empty Seat -> seated. Session cookie only."""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page
page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(3000)
print("authenticated:", site.is_authenticated())

tables = site.lobby_tables()
cand = [t for t in tables if (t["players"] or 0) < (t["seats"] or 99)]
# cheapest stakes first, so a test costs the least chips
def bb(t):
    return t.get("bb") or 0
cand.sort(key=bb)
pick = cand[0] if cand else None
print("trying:", pick["name"], pick["players_text"], pick["stakes"], "room", pick["room_id"])

t0 = time.time()
res = site.join_table(room_id=pick["room_id"], name=pick["name"])
print(f"join_table -> {res}  ({time.time()-t0:.1f}s)")

if res.get("ok"):
    print("seated:", page.evaluate(
        "() => ({self: !!document.querySelector('.player.is-this-player'), "
        "name: document.querySelector('.player.is-this-player .name')?.textContent, "
        "stack: document.querySelector('.player.is-this-player .stack')?.textContent, "
        "cards: [...document.querySelectorAll('.player.is-this-player .card')].length})"))
    obs = site.observe()
    print("observe:", {k: obs.get(k) for k in ("street", "pot", "my_turn", "hand_label")})
    page.screenshot(path="/tmp/seated.png")
    print("screenshot: /tmp/seated.png")
site.close()
