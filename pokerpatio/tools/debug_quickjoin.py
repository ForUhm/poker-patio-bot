"""Are ANY lobby clicks registering? Test a sort toggle, then the site's Quick Join."""
import time

from bot.credentials import Vault
from bot.site import PokerPatioSite

v = Vault()
site = PokerPatioSite(headless=True)
site.open(storage_state=v.storage_state())
page = site.page
page.goto("https://pokerpatio.com/lobbies", wait_until="domcontentloaded")
page.wait_for_timeout(4000)

def names():
    return page.evaluate("""() => [...document.querySelectorAll('tr.lobby-table')]
        .slice(0,4).map(r => r.querySelector('.table-name')?.textContent.trim())""")

before = names()
print("before:", before)

sort = page.evaluate("""() => {
  const b = [...document.querySelectorAll('[data-action-type="toggle_table_sort"]')]
      .find(e => /stakes/i.test(e.textContent||''));
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return {x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)};
}""")
print("sort button at:", sort)
if sort:
    page.mouse.click(sort["x"], sort["y"])
    page.wait_for_timeout(1500)
after = names()
print("after sort click:", after)
print("SORT WORKS" if before != after else "sort click did nothing -> clicks are not reaching handlers")

# try the site's own Quick Join
qj = page.evaluate("""() => {
  const b = document.querySelector('[data-action-type="lobby_quick_join"]');
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return {x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2),
          txt: (b.textContent||'').trim()};
}""")
print("\nquick join:", qj)
if qj:
    page.mouse.click(qj["x"], qj["y"])
    for i in range(10):
        page.wait_for_timeout(1200)
        st = page.evaluate("""() => ({
            seated: !!document.querySelector('.player.is-this-player'),
            url: location.href,
            popup: (() => { const p=[...document.querySelectorAll('.popup-holder')].find(e=>e.offsetParent!==null);
                            return p ? (p.querySelector('.title')?.textContent||'').trim() : null; })()
        })""")
        print(f"  {i*1.2:4.1f}s seated={st['seated']} popup={st['popup']} url={st['url'][-28:]}")
        if st["seated"]:
            page.screenshot(path="/tmp/quickjoin.png")
            break
site.close()
