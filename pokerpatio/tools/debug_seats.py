"""Enumerate every 'Empty Seat' control: which panel, visible or not, where."""
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
t = tables[0]
print("table:", t["name"], t["room_id"])
page.locator(f'[data-action-type="attempt_open_table"][data-type="{t["room_id"]}"]').first.click()
page.wait_for_timeout(2500)

info = page.evaluate(r"""() => {
  const nodes = [...document.querySelectorAll('[data-action-type="request_seat_join"]')];
  return nodes.map((b, i) => {
    const r = b.getBoundingClientRect();
    const seat = b.closest('.player');
    let panel = null, p = b;
    for (let k = 0; k < 8 && p; k++, p = p.parentElement) {
      if (p.dataset && (p.dataset.roomId || p.dataset.playerId)) { panel = {...p.dataset}; break; }
    }
    // what element is actually on top at the button's centre?
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const top = document.elementFromPoint(cx, cy);
    return {
      i,
      rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
      visible: !!(b.offsetParent),
      seatLoc: seat?.dataset.seatLocationId,
      seatCls: seat?.className,
      panel,
      panelId: (() => { let q=b; for(let k=0;k<8&&q;k++){ if(q.id==='players') return q.parentElement?.id||q.parentElement?.className; q=q.parentElement;} return null; })(),
      topAtPoint: top ? {tag: top.tagName, cls: (top.className||'').toString().slice(0,40),
                         action: top.dataset?.actionType || null} : null,
      display: getComputedStyle(b).display,
      pointerEvents: getComputedStyle(b).pointerEvents,
      parentPE: getComputedStyle(b.parentElement).pointerEvents,
    };
  });
}""")
print("seat buttons:", len(info))
for x in info[:6]:
    print(f"  #{x['i']} vis={x['visible']} rect={x['rect']} seatLoc={x['seatLoc']} pe={x['pointerEvents']} parentPE={x['parentPE']}")
    print(f"      top@centre={x['topAtPoint']}  panel={x['panel']}")
site.close()
