"""The preview has its own 'Join Table' button. Click it and see what it asks for."""
import json
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
t = tables[0]
print("table:", t["name"], t["stakes"], t["room_id"])

page.locator(f'[data-action-type="attempt_open_table"][data-type="{t["room_id"]}"]').first.click()
page.wait_for_timeout(2600)

btn = page.evaluate(r"""() => {
  const el = [...document.querySelectorAll('div,button,a,span')]
      .filter(b => b.offsetParent && /^\s*join table\s*$/i.test((b.textContent||'').trim()))
      .filter(b => b.children.length === 0)
      .pop();
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {
    html: el.outerHTML.slice(0, 300),
    parentHtml: el.parentElement.outerHTML.slice(0, 300),
    chain: (() => { const out=[]; let p=el; for(let i=0;i<5&&p;i++,p=p.parentElement)
                   out.push(p.tagName+'.'+((p.className||'').toString().split(' ')[0])+(p.id?'#'+p.id:''));
                   return out; })(),
    rect: {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2), w: Math.round(r.width)},
    visible: !!el.offsetParent,
  };
}""")
print("Join Table control:", json.dumps(btn, indent=1))
if btn:
    page.mouse.click(btn["rect"]["x"], btn["rect"]["y"])
    print("clicked Join Table at", btn["rect"])

for i in range(12):
    page.wait_for_timeout(1200)
    st = page.evaluate(r"""() => {
      const self = document.querySelector('.player.is-this-player');
      const pop = [...document.querySelectorAll('.popup-holder')].find(e => e.offsetParent !== null);
      const preview = document.querySelector('.table-preview');
      return {
        seated: !!self,
        name: self?.querySelector('.name')?.textContent || null,
        stack: self?.querySelector('.stack')?.textContent || null,
        previewGone: !preview,
        popup: pop ? (pop.querySelector('.title')?.textContent||'').trim() : null,
        popupText: pop ? (pop.innerText||'').replace(/\s+/g,' ').slice(0,220) : null,
        popupBtns: pop ? [...pop.querySelectorAll('[data-action-type],.btn,button')].filter(b=>b.offsetParent)
                     .map(b=>({t:b.dataset.actionType||null, txt:(b.textContent||'').trim().slice(0,18)})) : [],
        url: location.href,
        bodyTail: document.body.innerText.replace(/\s+/g,' ').slice(0,180),
      };
    }""")
    print(f"  {i*1.2:4.1f}s seated={st['seated']} popup={st['popup']} previewGone={st['previewGone']} url={st['url'][-30:]}")
    if st["popup"]:
        print("    text:", st["popupText"])
        print("    buttons:", st["popupBtns"])
    if st["seated"]:
        page.screenshot(path="/tmp/joined.png")
        print("    SEATED -> /tmp/joined.png")
        break
site.close()
