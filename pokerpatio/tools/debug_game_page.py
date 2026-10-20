"""On the game page: what controls does a spectator get? Dump them + screenshot."""
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
page.goto(f"https://pokerpatio.com/pg?game={room}&auto_seat=true", wait_until="domcontentloaded")
page.wait_for_timeout(9000)

info = page.evaluate(r"""() => {
  const vis = e => e && e.offsetParent !== null;
  return {
    url: location.href,
    title: document.title,
    buttons: [...document.querySelectorAll('[data-action-type]')].filter(vis)
      .map(e => ({t: e.dataset.actionType, type: e.dataset.type,
                  txt: (e.textContent||'').trim().replace(/\s+/g,' ').slice(0,26),
                  cls: (e.className||'').toString().slice(0,40)})),
    emptySeats: document.querySelectorAll('.player.is-empty-seat').length,
    seatInfo: [...document.querySelectorAll('.player.is-empty-seat')].slice(0,2).map(s => ({
      loc: s.dataset.seatLocationId, html: s.innerHTML.slice(0,220)})),
    bodyText: document.body.innerText.replace(/\n{2,}/g,'\n').slice(0, 500)
  };
}""")
print("url:", info["url"], "| title:", info["title"])
print("empty seats:", info["emptySeats"])
print("\n-- visible action buttons --")
for b in info["buttons"][:24]:
    print(f"   {str(b['t'])[:28]:28s} type={str(b['type'])[:14]:14s} '{b['txt']}'  [{b['cls']}]")
print("\n-- seat dom --")
for s in info["seatInfo"]:
    print("   ", s["loc"], s["html"][:200].replace("\n", " "))
print("\n-- body --")
print(info["bodyText"][:450])
page.screenshot(path="/tmp/game_page.png")
print("\nscreenshot /tmp/game_page.png")
site.close()
