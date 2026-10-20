"""Fifth discovery: the action bar itself + how a raise is submitted."""
import json
from playwright.sync_api import sync_playwright

CHROME = "/usr/bin/chromium"
ENV = {"TMPDIR": "/tmp", "HOME": "/tmp"}

JS_BAR = r"""
() => {
  const fold = document.querySelector('[data-action-type="fold"]');
  if (!fold) return {error: 'no fold'};
  const bar = fold.parentElement;
  return {
    parent_cls: bar.className, parent_id: bar.id,
    html: bar.outerHTML.slice(0, 3000),
    buttons: [...bar.querySelectorAll('[data-action-type]')].map(e => ({
      t: e.dataset.actionType, type: e.dataset.type,
      txt: (e.textContent||'').trim().slice(0,20),
      cls: (e.className||'').toString().slice(0,60)
    }))
  };
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--no-sandbox", "--disable-dev-shm-usage"], env=ENV)
    page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    page.goto("https://pokerpatio.com/sp", timeout=45000)
    page.wait_for_timeout(2000)
    page.fill('input[name="set_username"]', "scoutprobe")
    page.click('.difficulty-choice[data-type=easy]')
    page.wait_for_timeout(300)
    page.click('.btn[data-action-type="set_username_join_lobby"]')
    page.wait_for_timeout(7000)
    for _ in range(30):
        if page.evaluate("() => !!document.querySelector('.player.is-this-player.active-turn')"):
            break
        page.wait_for_timeout(1000)

    bar = page.evaluate(JS_BAR)
    print("=== BAR ===")
    print("parent:", bar.get("parent_cls"), bar.get("parent_id"))
    print(bar.get("html", "")[:2200])
    print("\n=== BUTTONS ===")
    print(json.dumps(bar.get("buttons"), indent=1)[:1500])

    page.screenshot(path="/tmp/pp_bar.png")
    print("\nscreenshot -> /tmp/pp_bar.png")

    # try raising: drive the hidden rangeslider input
    res = page.evaluate(r"""
    () => {
      const s = document.querySelector('input.slider[data-type="raise_amount"]');
      if (!s) return 'no slider';
      const target = Math.round((Number(s.min) + Number(s.max)) / 2);
      s.value = target;
      s.dispatchEvent(new Event('input', {bubbles: true}));
      s.dispatchEvent(new Event('change', {bubbles: true}));
      return {set: target, value: s.value};
    }""")
    print("slider set:", res)
    page.wait_for_timeout(1200)
    after = page.evaluate(JS_BAR)
    print("\n=== BUTTONS AFTER SLIDER ===")
    print(json.dumps(after.get("buttons"), indent=1)[:1500])
    print("\nbar text:", page.evaluate("() => document.querySelector('[data-action-type=fold]')?.parentElement?.innerText.replace(/\\s+/g,' ').slice(0,200)"))
    page.screenshot(path="/tmp/pp_bar2.png")
    b.close()
