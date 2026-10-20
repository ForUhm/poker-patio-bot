"""What does the table preview panel actually offer? List its visible controls."""
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
page.wait_for_timeout(2600)

info = page.evaluate(r"""() => {
  const vis = e => e && e.offsetParent !== null;
  const btn = [...document.querySelectorAll('[data-action-type]')].filter(vis)
    .map(e => ({t: e.dataset.actionType, type: e.dataset.type,
                txt: (e.textContent||'').trim().replace(/\s+/g,' ').slice(0,30),
                cls: (e.className||'').toString().slice(0,45)}));
  const joinTable = [...document.querySelectorAll('*')].filter(e =>
    /join table/i.test((e.textContent||'').trim()) && e.children.length === 0 && vis(e));
  // find the preview container: closest common ancestor of a seat + the Join Table text
  const seat = document.querySelector('.player.is-empty-seat');
  let panel = null, p = seat;
  for (let i = 0; i < 6 && p; i++, p = p.parentElement) {
    if (p.className && /preview|table-info|game|modal|overlay|panel/i.test(p.className)) {
      panel = {cls: p.className, id: p.id, html: p.outerHTML.slice(0, 400)}; break;
    }
  }
  return {
    buttons: btn.slice(0, 40),
    joinTable: joinTable.map(e => ({tag: e.tagName, cls: e.className,
                                    parent: e.parentElement?.className,
                                    action: e.parentElement?.dataset?.actionType})),
    panel,
    bodyTail: document.body.innerText.replace(/\n{2,}/g,'\n').slice(-700)
  };
}""")
print("\n-- visible action buttons --")
for b in info["buttons"][:26]:
    print(f"   {str(b['t'])[:26]:26s} type={str(b['type'])[:16]:16s} '{b['txt']}'")
print("\n-- elements containing 'Join Table' --")
for j in info["joinTable"][:6]:
    print("   ", j)
print("\n-- preview panel --")
print(info["panel"])
print("\n-- body tail --")
print(info["bodyTail"][:600])
site.close()
