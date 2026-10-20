"""Third discovery pass: full action-bar markup + raise mechanics."""
import json
from playwright.sync_api import sync_playwright

CHROME = "/usr/bin/chromium"
ENV = {"TMPDIR": "/tmp", "HOME": "/tmp"}

FIND_BAR = r"""
() => {
  // the action bar is the closest common ancestor of the fold button
  const fold = document.querySelector('[data-action-type="fold"]');
  if (!fold) return {error: 'no fold button'};
  let node = fold;
  for (let i = 0; i < 5 && node.parentElement; i++) node = node.parentElement;
  return {cls: node.className, id: node.id, html: node.outerHTML.slice(0, 5000)};
}
"""

PLAYER_HTML = r"""
() => {
  const p = document.querySelector('.player:not(.is-this-player)');
  return p ? p.outerHTML.slice(0, 1800) : null;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--no-sandbox", "--disable-dev-shm-usage"], env=ENV)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto("https://pokerpatio.com/sp", timeout=45000)
    page.wait_for_timeout(2000)
    page.fill('input[name="set_username"]', "scoutprobe")
    page.click('.difficulty-choice[data-type=easy]')
    page.wait_for_timeout(300)
    page.click('.btn[data-action-type="set_username_join_lobby"]')
    page.wait_for_timeout(7000)

    for i in range(30):
        turn = page.evaluate("() => !!document.querySelector('.player.is-this-player.active-turn')")
        if turn:
            break
        page.wait_for_timeout(1200)

    print("=== ACTION BAR ===")
    bar = page.evaluate(FIND_BAR)
    print(json.dumps(bar, indent=1)[:5200])
    print("\n=== OPPONENT PLAYER HTML ===")
    print(page.evaluate(PLAYER_HTML))
    print("\n=== SELF PLAYER HTML (trimmed) ===")
    self_html = page.evaluate("() => document.querySelector('.player.is-this-player')?.outerHTML.slice(0,1500)")
    print(self_html)
    b.close()
