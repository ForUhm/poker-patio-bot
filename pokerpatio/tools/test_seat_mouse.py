"""Take a seat with a real mouse click on the seat container (not the covered button)."""
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
print("table:", t["name"], t["players_text"], t["stakes"])

page.locator(f'[data-action-type="attempt_open_table"][data-type="{t["room_id"]}"]').first.click()
page.wait_for_timeout(2500)

seat = page.evaluate("""() => {
  const s = document.querySelector('.player.is-empty-seat');
  if (!s) return null;
  const r = s.getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2, loc: s.dataset.seatLocationId};
}""")
print("seat target:", seat)
if seat:
    page.mouse.move(seat["x"], seat["y"])
    page.wait_for_timeout(200)
    page.mouse.click(seat["x"], seat["y"])
    print("mouse click dispatched at seat centre")

for i in range(14):
    page.wait_for_timeout(1000)
    st = page.evaluate("""() => {
      const self = document.querySelector('.player.is-this-player');
      const pop = [...document.querySelectorAll('.popup-holder')].find(e => e.offsetParent !== null);
      return {
        seated: !!self,
        name: self?.querySelector('.name')?.textContent || null,
        stack: self?.querySelector('.stack')?.textContent || null,
        popup: pop ? (pop.querySelector('.title')?.textContent || '').trim() : null,
        popupText: pop ? (pop.innerText || '').replace(/\\s+/g,' ').slice(0,200) : null,
        popupBtns: pop ? [...pop.querySelectorAll('[data-action-type],.btn,button')]
                       .filter(b=>b.offsetParent).map(b=>({t:b.dataset.actionType||null,
                        txt:(b.textContent||'').trim().slice(0,20)})) : [],
      };
    }""")
    if st["seated"] or st["popup"]:
        print(f"  {i+1}s -> seated={st['seated']} name={st['name']} stack={st['stack']} popup={st['popup']}")
        if st["popup"]:
            print("   popup text:", st["popupText"])
            print("   popup buttons:", st["popupBtns"])
        if st["seated"]:
            page.screenshot(path="/tmp/seated_ok.png")
            print("   screenshot /tmp/seated_ok.png")
            break
    else:
        print(f"  {i+1}s -> waiting…")
site.close()
