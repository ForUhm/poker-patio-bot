"""Inspect the buy-in dialog that appears after clicking SIT."""
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
print("target:", t["name"], t["room_id"])

opened = site.open_game_page(t["room_id"])
print("game page:", opened)
site.page.wait_for_timeout(1200)

# click the first SIT
sit = page.locator('[data-action-type="request_seat_join"]')
print("SIT buttons:", sit.count())
for i in range(min(3, sit.count())):
    try:
        if sit.nth(i).is_visible():
            sit.nth(i).click(timeout=5000)
            print("clicked SIT", i)
            break
    except Exception as e:
        print("sit click failed:", str(e)[:80])

for _ in range(8):
    page.wait_for_timeout(900)
    info = page.evaluate(r"""() => {
      const p = [...document.querySelectorAll('.popup-holder')].find(e => e.offsetParent !== null);
      if (!p) return null;
      return {
        title: (p.querySelector('.title')?.textContent||'').trim(),
        text: (p.innerText||'').replace(/\s+/g,' ').slice(0,300),
        inputs: [...p.querySelectorAll('input')].map(i => ({
            type: i.type, cls: i.className, min: i.min, max: i.max, value: i.value,
            dataType: i.dataset.type || null, action: i.dataset.actionType || null })),
        buttons: [...p.querySelectorAll('[data-action-type],.btn,button')].filter(b=>b.offsetParent)
          .map(b => ({t: b.dataset.actionType||null, type: b.dataset.type||null,
                      txt: (b.textContent||'').trim().slice(0,20), cls: (b.className||'').toString().slice(0,40)})),
        html: p.outerHTML.slice(0, 900)
      };
    }""")
    if info:
        print("\n=== POPUP:", info["title"], "===")
        print("text:", info["text"])
        print("inputs:", info["inputs"])
        print("buttons:", info["buttons"])
        print("html:", info["html"][:800])
        page.screenshot(path="/tmp/buyin.png")
        print("\nscreenshot /tmp/buyin.png")
        break
else:
    print("no popup appeared")
site.close()
