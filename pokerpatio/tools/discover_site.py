"""One-off DOM discovery against the live site (real Playwright clicks)."""
import json
import time
from playwright.sync_api import sync_playwright

CHROME = "/usr/bin/chromium"
ENV = {"TMPDIR": "/tmp", "HOME": "/tmp"}


def dump(page, tag):
    print(f"\n===== {tag} =====")
    info = page.evaluate(r"""
    () => {
      const cards = [...document.querySelectorAll('.card')].map(c => ({
        cls: c.className, faceUp: c.dataset.faceUp, id: c.dataset.cardId,
        inSelf: !!c.closest('.player.is-this-player'),
        inBoard: !!c.closest('#communityCards'),
        style: (c.getAttribute('style')||'').slice(0,80)
      }));
      const players = [...document.querySelectorAll('#players .player')].map(p => ({
        id: p.dataset.playerId, pos: p.dataset.posType, loc: p.dataset.seatLocationId,
        self: p.classList.contains('is-this-player'),
        turn: p.classList.contains('active-turn'),
        playing: p.classList.contains('playing'),
        revealed: p.classList.contains('cards-revealed'),
        name: p.querySelector('.name')?.textContent.trim(),
        stack: p.querySelector('.stack')?.textContent.trim(),
        bet: p.querySelector('.bet, .player-bet, .current-bet')?.textContent.trim(),
        cardCls: [...p.querySelectorAll('.card')].map(c => c.className),
        inner: p.innerText.replace(/\s+/g, ' ').slice(0, 120)
      }));
      const actions = [...document.querySelectorAll('[data-action-type]')]
        .filter(e => e.offsetParent)
        .map(e => ({ type: e.dataset.actionType, text: (e.textContent||'').trim().slice(0,20),
                     cls: e.className, disabled: e.classList.contains('disabled') }));
      const sliders = [...document.querySelectorAll('input[type=range]')].map(s => ({
        cls: s.className, min: s.min, max: s.max, value: s.value,
        parent: s.parentElement?.className
      }));
      return {
        url: location.href,
        cards, players, actions, sliders,
        pot: document.querySelector('#potArea .pot-total span')?.textContent,
        potAttr: document.querySelector('#potArea .pot-total')?.dataset.totalStagePot,
        boardHTML: document.querySelector('#communityCards')?.innerHTML.slice(0, 400),
        dealer: [...document.querySelectorAll('[class*=dealer]')].map(e => e.className).slice(0,5),
        bodyText: document.body.innerText.replace(/\n{2,}/g,'\n').slice(0, 400)
      };
    }""")
    print(json.dumps(info, indent=1)[:4000])


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--no-sandbox", "--disable-dev-shm-usage"], env=ENV)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto("https://pokerpatio.com/sp", timeout=45000)
    page.wait_for_timeout(2500)
    page.fill('input[name="set_username"]', "scoutprobe")
    page.click('.difficulty-choice[data-type=easy]')
    page.wait_for_timeout(400)
    page.click('.btn[data-action-type="set_username_join_lobby"]')
    page.wait_for_timeout(9000)
    print("url now:", page.url)
    dump(page, "after start")
    page.screenshot(path="/tmp/pp_table.png", full_page=False)
    print("screenshot saved")
    b.close()
