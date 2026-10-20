"""Diagnostic: what exactly happens between 'Join' and being seated.

Uses only the stored session cookie from the vault — no password involved.
Read-only: it inspects the seat-request panel and never confirms a seat.
"""
import json

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
state = v.storage_state()
print("vault session:", bool(state), "cookies:", len(state.get("cookies", [])) if state else 0)

site = PokerPatioSite(headless=True)
site.open(storage_state=state)
page = site.page
page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(3500)
print("authenticated:", site.is_authenticated(), "| user:", site._read_username())

tables = [t for t in site.lobby_tables() if (t["players"] or 0) < (t["seats"] or 99)]
t = next((x for x in tables if x["name"] == "Chicago Kings"), tables[0])
print("target:", t["name"], t["players_text"], "room:", t["room_id"])

page.locator(f'[data-action-type="attempt_open_table"][data-type="{t["room_id"]}"]').first.click()
page.wait_for_timeout(2500)

dump = page.evaluate(r"""() => {
  const vis = (e) => e && e.offsetParent !== null;
  const seatBtns = [...document.querySelectorAll('[data-action-type="request_seat_join"]')];
  const all = [...document.querySelectorAll('[data-action-type]')].filter(vis)
    .map(e => ({t: e.dataset.actionType, type: e.dataset.type, seat: e.dataset.seat,
                txt: (e.textContent||'').trim().slice(0,24),
                cls: (e.className||'').toString().slice(0,50)}))
    .filter(x => !/card_clicked|show_popup|customization_action|show_data_tooltip/.test(x.t));
  const seen = new Set(); const panels = [];
  seatBtns.forEach(b => { let p=b; for(let i=0;i<4&&p.parentElement;i++) p=p.parentElement;
    if(!seen.has(p)){seen.add(p); panels.push(p.outerHTML.slice(0,2200));} });
  return {
    url: location.href,
    seatBtnCount: seatBtns.length,
    seatBtns: seatBtns.map(b => ({attrs: [...b.attributes].map(a=>a.name+'='+a.value),
                                  txt: (b.textContent||'').trim().slice(0,30),
                                  cls: b.className})),
    actions: all.slice(0, 30),
    panels: panels.slice(0, 1),
    bodyText: document.body.innerText.replace(/\n{2,}/g,'\n').slice(0, 700),
    gamePresent: !!document.querySelector('#players')
  };
}""")
print("\nurl:", dump["url"], "| game DOM present:", dump["gamePresent"])
print("seat buttons:", dump["seatBtnCount"])
print("\nvisible actions:")
for a in dump["actions"][:18]:
    print(f"   {str(a['t']):26s} type={str(a['type'])[:14]:14s} seat={str(a['seat'])[:6]:6s} '{a['txt']}'")
print("\n--- panel html (trimmed) ---")
for p in dump["panels"]:
    print(p[:1600])
print("\n--- body text ---")
print(dump["bodyText"][:600])
page.screenshot(path="/tmp/seat_panel.png")
print("\nscreenshot: /tmp/seat_panel.png")
site.close()
