"""Direct game-page path: /pg?game=<room>&auto_seat=true — does it seat us?"""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page
page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(3000)
tables = [t for t in site.lobby_tables() if (t["players"] or 0) < (t["seats"] or 99)]
tables.sort(key=lambda t: t.get("bb") or 0)
room = tables[0]["room_id"]
print("room:", room, tables[0]["name"])

url = f"https://pokerpatio.com/pg?game={room}&auto_seat=true"
page.goto(url, wait_until="domcontentloaded")
print("navigated to:", page.url)

for i in range(20):
    page.wait_for_timeout(1500)
    st = page.evaluate(r"""() => ({
      seated: !!document.querySelector('.player.is-this-player'),
      players: document.querySelectorAll('.player').length,
      name: document.querySelector('.player.is-this-player .name')?.textContent || null,
      stack: document.querySelector('.player.is-this-player .stack')?.textContent || null,
      popup: (() => { const p=[...document.querySelectorAll('.popup-holder')].find(e=>e.offsetParent!==null);
                      return p ? (p.querySelector('.title')?.textContent||'').trim() : null; })(),
      popupBtns: (() => { const p=[...document.querySelectorAll('.popup-holder')].find(e=>e.offsetParent!==null);
                      return p ? [...p.querySelectorAll('[data-action-type],.btn')].filter(b=>b.offsetParent)
                        .map(b=>({t:b.dataset.actionType||null, txt:(b.textContent||'').trim().slice(0,18)})) : []; })(),
      bodyText: document.body.innerText.replace(/\n{2,}/g,'\n').slice(0, 260)
    })""")
    print(f"  {i*1.5:4.1f}s seated={st['seated']} players={st['players']} name={st['name']} popup={st['popup']}")
    if st["popup"]:
        print("    popup buttons:", st["popupBtns"])
        print("    body:", st["bodyText"][:200].replace("\n", " | "))
    if st["seated"]:
        print("    SEATED as", st["name"], "stack", st["stack"])
        obs = site.observe()
        print("    observe:", {k: obs.get(k) for k in ("street", "pot", "my_turn", "hand_label")})
        print("    hole:", (obs.get("self") or {}).get("cards"))
        page.screenshot(path="/tmp/game_seated.png")
        break
site.close()
