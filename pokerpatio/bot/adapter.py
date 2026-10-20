"""Site adapter layer.

pokerpatio.net is currently a parked domain (GoDaddy lander), so the shipped
default is `SimulatedAdapter`: it plays the app's own table engine. The
`DomSiteAdapter` is the real-site path — it drives a browser tab with
configurable selectors so a *live* table can be wired in without touching the
strategy code.

Selector config schema (all CSS selectors, resolved against the table iframe or
document):

    table_root      container that holds the table
    hero_cards      hero's hole cards (should return 2 nodes; read data-card or text)
    board_cards     community cards
    pot             element whose text parses to the pot size
    to_call         element with the amount to call (optional; derived from bet_level)
    stack           hero stack
    seat            selector for each opponent seat
    action_button   base selector for action controls
    raise_input     raise amount field
    confirm_button  confirm/commit control

`probe_script()` returns a snippet to paste into the browser console on the
poker site; it reports candidate selectors by heuristics (class names containing
'card', 'pot', 'stack', buttons) so selectors can be captured in seconds.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "adapter.json")

DEFAULT_CONFIG = {
    "mode": "simulated",
    "url": "https://pokerpatio.net",
    "selectors": {
        "table_root": "",
        "hero_cards": "",
        "board_cards": "",
        "pot": "",
        "to_call": "",
        "stack": "",
        "seat": "",
        "action_button": "",
        "raise_input": "",
        "confirm_button": "",
    },
    "timing": {"poll_ms": 400, "action_delay_ms": 900, "max_action_ms": 15000},
    "safety": {"dry_run": True, "max_buyin": 100, "stop_loss": 300},
    "notes": ("pokerpatio.net resolves to a GoDaddy parking lander, so 'simulated' "
              "mode is the only functional backend until a live table URL exists."),
}

PROBE_SCRIPT = r"""
(() => {
  const pick = (el) => {
    if (!el) return null;
    if (el.id) return '#' + el.id;
    const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean);
    if (cls.length) return '.' + cls.slice(0, 2).join('.');
    return el.tagName.toLowerCase();
  };
  const hunt = (re) => {
    const out = [];
    document.querySelectorAll('*').forEach(el => {
      const key = (el.className || '') + ' ' + (el.id || '') + ' ' + (el.dataset ? Object.keys(el.dataset).join(' ') : '');
      if (re.test(key) && el.children.length < 6) {
        out.push({ sel: pick(el), tag: el.tagName, text: (el.textContent || '').trim().slice(0, 40) });
      }
    });
    return out.slice(0, 12);
  };
  const res = {
    url: location.href,
    title: document.title,
    iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0, 5),
    cards: hunt(/card|hole|board|community/i),
    pot: hunt(/pot|jackpot|total/i),
    stack: hunt(/stack|balance|chips|bankroll/i),
    buttons: [...document.querySelectorAll('button,[role=button],a.btn')]
      .map(b => ({ sel: pick(b), text: (b.textContent || '').trim().slice(0, 24) })).slice(0, 20),
    canvas_count: document.querySelectorAll('canvas').length,
  };
  console.log(JSON.stringify(res, null, 2));
  return res;
})()
"""


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            merged = json.loads(json.dumps(DEFAULT_CONFIG))
            merged.update({k: v for k, v in cfg.items() if k != "selectors"})
            merged["selectors"].update(cfg.get("selectors", {}))
            return merged
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg: dict) -> dict:
    base = load_config()
    base.update({k: v for k, v in cfg.items() if k in DEFAULT_CONFIG})
    if "selectors" in cfg:
        base["selectors"].update(cfg["selectors"])
    if "timing" in cfg:
        base["timing"].update(cfg["timing"])
    if "safety" in cfg:
        base["safety"].update(cfg["safety"])
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(base, f, indent=2)
    return base


class SimulatedAdapter:
    """Default backend: the local table engine. Full-fidelity, no network."""

    mode = "simulated"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "target": self.cfg.get("url"),
            "reachable": False,
            "detail": ("pokerpatio.net returns a parking lander (HTTP 200 -> /lander); "
                       "no poker client to attach to. Running the local engine instead."),
            "selectors_configured": all(self.cfg["selectors"].values()),
        }

    def connect(self):
        return {"ok": True, "mode": self.mode}

    def observe(self):
        raise NotImplementedError("simulated adapter is driven by game.table.Table")

    def act(self, action: str, amount: float = 0.0):
        raise NotImplementedError


class DomSiteAdapter:
    """Browser-driven adapter for a real table. Requires Playwright + selectors."""

    mode = "dom"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ok = False
        self._page = None

    def status(self) -> dict:
        missing = [k for k, v in self.cfg["selectors"].items() if not v]
        return {
            "mode": self.mode,
            "target": self.cfg.get("url"),
            "reachable": self.ok,
            "detail": ("selectors incomplete: " + ", ".join(missing)) if missing
                      else "selectors configured; Playwright not started",
            "selectors_configured": not missing,
        }

    def connect(self):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception as e:
            return {"ok": False, "error": f"playwright not installed: {e}"}
        missing = [k for k, v in self.cfg["selectors"].items() if not v]
        if missing:
            return {"ok": False, "error": "missing selectors: " + ", ".join(missing)}
        return {"ok": False,
                "error": ("selectors present but no browser session was opened by this "
                          "process; run `python3 -m bot.dom_runner` to attach a tab")}

    def observe(self):
        raise NotImplementedError

    def act(self, action: str, amount: float = 0.0):
        raise NotImplementedError


def get_adapter(cfg: dict):
    return DomSiteAdapter(cfg) if cfg.get("mode") == "dom" else SimulatedAdapter(cfg)


def adapter_report(cfg: dict) -> dict:
    a = get_adapter(cfg)
    return {"status": a.status(), "config": cfg, "probe_script": PROBE_SCRIPT}
