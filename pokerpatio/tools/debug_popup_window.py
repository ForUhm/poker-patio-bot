"""Does Join open a new tab/window? Watch for popups."""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page
ctx = page.context

popups = []
page.on("popup", lambda p: popups.append(("page.popup", p.url)))
ctx.on("page", lambda p: popups.append(("context.page", p.url)))

page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(4000)
print("pages open:", len(ctx.pages))

tables = [t for t in site.lobby_tables() if (t["players"] or 0) < (t["seats"] or 99)]
tables.sort(key=lambda t: t.get("bb") or 0)
t = tables[0]
print("joining:", t["name"], t["room_id"])

pos = page.evaluate("""(room) => {
  const b = document.querySelector(`[data-action-type="attempt_open_table"][data-type="${room}"]`);
  const r = b.getBoundingClientRect();
  return {x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)};
}""", t["room_id"])
page.mouse.click(pos["x"], pos["y"])

for i in range(12):
    page.wait_for_timeout(1000)
    urls = [p.url for p in ctx.pages]
    print(f"  {i+1}s pages={len(ctx.pages)} urls={[u[-40:] for u in urls]} popups={popups[-2:]}")
    if len(ctx.pages) > 1:
        new = ctx.pages[-1]
        print("   NEW PAGE title:", new.title())
        new.wait_for_timeout(2500)
        print("   seated there:", new.evaluate(
            "() => !!document.querySelector('.player.is-this-player')"))
        new.screenshot(path="/tmp/newpage.png")
        print("   screenshot /tmp/newpage.png")
        break
site.close()
