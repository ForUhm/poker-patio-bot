"""Fourth discovery: action-bar container, bet element, raise flow."""
import json
from playwright.sync_api import sync_playwright

CHROME = "/usr/bin/chromium"
ENV = {"TMPDIR": "/tmp", "HOME": "/tmp"}

JS = r"""
() => {
  const out = {};
  const fold = document.querySelector('[data-action-type="fold"]');
  if (fold) {
    let n = fold;
    for (let i = 0; i < 3 && n.parentElement; i++) n = n.parentElement;
    out.actionBar = {cls: n.className, id: n.id, html: n.outerHTML.slice(0, 2500)};
  }
  // any player with a numeric bet: dump descendants
  const p = [...document.querySelectorAll('#players .player')].find(p => {
    const lines = p.innerText.trim().split('\n').map(s=>s.trim()).filter(Boolean);
    return lines.length >= 3 && /^\$/.test(lines[2] || '');
  });
  if (p) {
    out.betPlayer = {
      name: p.querySelector('.name')?.textContent,
      lines: p.innerText.trim().split('\n').map(s=>s.trim()),
      kids: [...p.querySelectorAll('*')].map(e => ({
        tag: e.tagName, cls: (e.className||'').toString().slice(0,50),
        text: [...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').slice(0,24)
      })).filter(k => k.text).slice(0, 20)
    };
  }
  out.sliderHolder = document.querySelector('.slide-container')?.outerHTML.slice(0, 1200);
  return out;
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
    for _ in range(25):
        if page.evaluate("() => !!document.querySelector('.player.is-this-player.active-turn')"):
            break
        page.wait_for_timeout(1200)

    info = page.evaluate(JS)
    print("=== ACTION BAR ===")
    print(info.get("actionBar", {}).get("html", "none")[:2600])
    print("\n=== BET PLAYER ===")
    print(json.dumps(info.get("betPlayer"), indent=1)[:1800])
    print("\n=== SLIDER HOLDER ===")
    print((info.get("sliderHolder") or "none")[:1200])
    b.close()
