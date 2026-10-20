"""Does a lobby click actually reach the site's handler? Watch console + network."""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page

events = []
page.on("console", lambda m: events.append(("console", m.type, m.text[:180])))
page.on("pageerror", lambda e: events.append(("pageerror", str(e)[:180])))
page.on("request", lambda r: events.append(("req", r.method, r.url[:120])))
page.on("response", lambda r: events.append(("res", r.status, r.url[:120])))
page.on("websocket", lambda ws: events.append(("ws-open", ws.url[:100])))

page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(4000)
print("ws/console so far:", [e for e in events if e[0].startswith(("ws", "pageerror"))][:5])

tables = [t for t in site.lobby_tables() if (t["players"] or 0) < (t["seats"] or 99)]
tables.sort(key=lambda t: t.get("bb") or 0)
t = tables[0]
print("table:", t["name"], t["room_id"])

info = page.evaluate(r"""() => {
  const row = document.querySelector('[data-action-type="attempt_open_table"]');
  const jt = [...document.querySelectorAll('[data-action-type="attempt_open_table"]')]
      .find(b => /join table/i.test(b.textContent||''));
  const probe = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const top = document.elementFromPoint(cx, cy);
    return {rect:{x:Math.round(cx),y:Math.round(cy)}, roomId: el.dataset.type,
            top: top ? top.tagName+'.'+((top.className||'').toString().split(' ')[0]) : null,
            same: top === el};
  };
  return {row: probe(row), joinTable: probe(jt),
          popupsHolder: (document.getElementById('popupsHolder')?.innerText || '').slice(0,200)};
}""")
print("probe:", info)

events.clear()
target = info["joinTable"] or info["row"]
page.mouse.click(target["rect"]["x"], target["rect"]["y"])
page.wait_for_timeout(3000)

print("\n--- after clicking the table's Join Table ---")
for e in events[:25]:
    print("  ", e)
print("\npopupsHolder:", page.evaluate("() => (document.getElementById('popupsHolder')?.innerText||'').replace(/\\s+/g,' ').slice(0,300)"))
print("seated:", page.evaluate("() => !!document.querySelector('.player.is-this-player')"))
site.close()
