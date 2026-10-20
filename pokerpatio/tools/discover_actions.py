"""Second discovery pass: action bar, bet slider, pot, button marker."""
import json
import time
from playwright.sync_api import sync_playwright

CHROME = "/usr/bin/chromium"
ENV = {"TMPDIR": "/tmp", "HOME": "/tmp"}

STATE_JS = r"""
() => {
  const self = document.querySelector('.player.is-this-player');
  const actions = [...document.querySelectorAll('[data-action-type]')]
    .filter(e => e.offsetParent)
    .map(e => ({ type: e.dataset.actionType, text: (e.textContent||'').trim().slice(0,24),
                 cls: (e.className||'').toString().slice(0,60) }))
    .filter(a => ['fold','check','call','raise','bet','all_in','bet_slider','slide','confirm'].includes(a.type)
              || /fold|call|raise|check/i.test(a.text));
  const sliders = [...document.querySelectorAll('input[type=range]')].map(s => ({
    cls: s.className, min: s.min, max: s.max, value: s.value, id: s.id,
    parent: s.parentElement?.className, visible: !!s.offsetParent
  }));
  return {
    turn: !!self && self.classList.contains('active-turn'),
    selfPos: self?.dataset.posType, selfLoc: self?.dataset.seatLocationId,
    selfText: self?.innerText.replace(/\s+/g,' ').slice(0,100),
    actions, sliders,
    potSpan: document.querySelector('#potArea .pot-total span')?.textContent,
    potAttr: document.querySelector('#potArea .pot-total')?.dataset.totalStagePot,
    board: [...document.querySelectorAll('#communityCards .card')].map(c => ({
      cls: c.className, up: c.dataset.faceUp })),
    seats: [...document.querySelectorAll('#players .player')].map(p => ({
      pos: p.dataset.posType, loc: p.dataset.seatLocationId,
      turn: p.classList.contains('active-turn'),
      playing: p.classList.contains('playing'),
      dealerish: p.innerHTML.includes('dealer'),
      text: p.innerText.replace(/\s+/g,' ').slice(0,70)
    })),
    dealerEls: [...document.querySelectorAll('[class*="dealer"],[class*="btn-marker"],[class*="position"]')]
      .map(e => ({cls: e.className, parent: e.parentElement?.className})).slice(0,8),
    bodyText: document.body.innerText.replace(/\n{2,}/g,'\n').slice(0, 500)
  };
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
    page.wait_for_timeout(6000)

    seen_turn = False
    for i in range(40):
        st = page.evaluate(STATE_JS)
        if st["turn"] and not seen_turn:
            seen_turn = True
            print("=== MY TURN ===")
            print(json.dumps(st, indent=1)[:2600])
            page.screenshot(path="/tmp/pp_turn.png")
        if i == 3 and not seen_turn:
            print("=== no turn yet (sample) ===")
            print(json.dumps(st, indent=1)[:1400])
        if seen_turn and i > 6:
            break
        page.wait_for_timeout(1500)
    page.screenshot(path="/tmp/pp_final.png")
    print("seen_turn:", seen_turn)
    b.close()
