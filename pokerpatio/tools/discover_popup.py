"""Capture the 'Game Lost!' popup markup and test check-as-fold + turn guarding."""
import json
import time

from bot.site import PokerPatioSite

site = PokerPatioSite(headless=True)
site.open()
site.start_singleplayer("scoutprobe", "easy")
print("started")

t0 = time.time()
dumped = False
last_key = None
while time.time() - t0 < 150:
    st = site.observe()
    if st.get("popup"):
        html = site.page.evaluate(
            "() => document.querySelector('.popup-holder')?.outerHTML.slice(0,2500)")
        print("\n=== POPUP:", st["popup"], "===")
        print(html)
        print("\nbuttons:", site.page.evaluate("""() => [...document.querySelectorAll('.popup-holder [data-action-type], .popup-holder .btn, .popup-holder button')].map(e=>({t:e.dataset.actionType||null, txt:(e.textContent||'').trim().slice(0,24), cls:(e.className||'').toString().slice(0,50), vis:!!e.offsetParent}))"""))
        dumped = True
        break
    if st["my_turn"]:
        key = (st["street"], st["pot"], st["self"]["bet"], st["self"]["stack"])
        if key != last_key:
            last_key = key
            # deliberately bad play to bust fast: call/raise everything
            bar = st["bar"]
            if not bar["call"] and bar["check"]:
                r = site.act("check")
                if not r.get("ok"):
                    r2 = site.page.locator('.actions [data-action-type="fold"]').first
                    r = {"fallback_fold_click": True, "visible": r2.is_visible()}
                    site.page.locator('.actions [data-action-type="fold"]').first.click()
            else:
                site.act("call")
            print("acted", st["street"], st["pot"])
    time.sleep(0.5)

print("dumped popup:", dumped)
site.close()
