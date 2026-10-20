"""Experiment: which click method actually takes an 'Empty Seat'?

The button is visually behind its parent (.left-side.seat-info) so Playwright's
hit-target check refuses normal clicks. Try (a) a direct DOM click, then
(b) unlocking pointer-events and doing a trusted mouse click.
"""
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
print("table:", t["name"], t["players_text"], t["stakes"], t["room_id"])

page.locator(f'[data-action-type="attempt_open_table"][data-type="{t["room_id"]}"]').first.click()
page.wait_for_timeout(2200)
print("empty seats:", page.locator('[data-action-type="request_seat_join"]').count())


def seated():
    return page.evaluate("() => !!document.querySelector('.player.is-this-player')")


# --- method A: direct DOM click (untrusted event)
page.evaluate("""() => {
  const b = document.querySelector('.player.is-empty-seat [data-action-type="request_seat_join"]')
         || document.querySelector('[data-action-type="request_seat_join"]');
  if (b) b.click();
  return !!b;
}""")
for _ in range(8):
    page.wait_for_timeout(800)
    if seated():
        print("A (dom click) -> SEATED")
        break
else:
    print("A (dom click) -> not seated")

# --- method B: unlock pointer events, then a trusted click
if not seated():
    page.evaluate("""() => {
      const st = document.createElement('style');
      st.id = '__unlock';
      st.textContent = '.left-side.seat-info{pointer-events:none !important}';
      document.head.appendChild(st);
    }""")
    try:
        page.locator('[data-action-type="request_seat_join"]').first.click(timeout=6000)
        print("B click dispatched")
    except Exception as e:
        print("B click failed:", str(e)[:120])
    page.evaluate("() => document.getElementById('__unlock')?.remove()")
    for _ in range(10):
        page.wait_for_timeout(800)
        if seated():
            print("B (pointer-events unlock) -> SEATED")
            break
    else:
        print("B -> not seated")

info = page.evaluate("""() => ({
  seated: !!document.querySelector('.player.is-this-player'),
  name: document.querySelector('.player.is-this-player .name')?.textContent || null,
  stack: document.querySelector('.player.is-this-player .stack')?.textContent || null,
  popup: (() => { const p=[...document.querySelectorAll('.popup-holder')].find(e=>e.offsetParent!==null);
                  return p ? (p.querySelector('.title')?.textContent||'').trim() : null; })(),
  url: location.href
})""")
print("final:", info)
page.screenshot(path="/tmp/seat_test.png")
site.close()
