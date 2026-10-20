"""End-to-end: lobby -> Join -> game page -> SIT -> seated -> observe."""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page
page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(3000)
print("auth:", site.is_authenticated())

tables = [t for t in site.lobby_tables() if (t["players"] or 0) < (t["seats"] or 99)]
tables.sort(key=lambda t: t.get("bb") or 0)
t = tables[0]
print("target:", t["name"], t["players_text"], t["stakes"])

t0 = time.time()
res = site.join_table(room_id=t["room_id"], name=t["name"])
print(f"join_table -> {res}  ({time.time()-t0:.1f}s)")

if res.get("ok"):
    print("current page:", site.page.url)
    print("seated:", site.page.evaluate(
        "() => ({name: document.querySelector('.player.is-this-player .name')?.textContent,"
        " stack: document.querySelector('.player.is-this-player .stack')?.textContent,"
        " cards: [...document.querySelectorAll('.player.is-this-player .card')].length})"))
    obs = site.observe()
    print("observe:", {k: obs.get(k) for k in ("street", "pot", "my_turn", "hand_label")})
    print("hole:", (obs.get("self") or {}).get("cards"), "| players:", len(obs["players"]))
    site.page.screenshot(path="/tmp/seated_final.png")
    print("screenshot /tmp/seated_final.png")
site.close()
