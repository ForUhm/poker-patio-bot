# Strategy research → engine spec

This is the theory the bot is built on, and exactly how each idea became code.
Every formula below is implemented in `core/mathx.py`; every range in
`core/ranges.py`; every decision path in `core/strategies.py`.

---

## 0. What "winning" actually means (and why the dashboard shows variance)

Poker results are dominated by variance over small samples. With 100bb stacks in
a 6-max game, per-hand standard deviation is roughly 10–30 bb depending on style,
so after *n* hands the 95% confidence interval on your win rate is about
`±1.96 · σ / √n · 100` bb/100. At 400 hands with σ = 25 bb that is **±245 bb/100**
— wider than any realistic edge.

Consequences baked into the app:

- `game/simulator.py` reports `std_per_hand`, `se_bb100` and `ci95_bb100` next to
  every win rate, and the comparison legend prints `bb/100 ± CI`.
- The dashboard's default sample is deliberately small for interactivity; the
  numbers are honest estimates, not proof. Raise "Hands" to 2,000+ before
  drawing conclusions about *which* strategy is better.
- A strategy that is +400 bb/100 over 300 hands is not "better"; it is one that
  either ran hot or takes high-variance lines. Risky does both by design.

---

## 1. Preflop: range construction

### 1.1 Open-raise (RFI) frequencies, 6-max, 100bb

Published solver baselines converge on roughly: UTG ~15–17%, HJ ~19–22%,
CO ~25–28%, BTN ~40–45%, SB ~35–45% (raise-or-fold simplification), with 2.5bb
opens (3bb from SB). The engine's baselines, measured by `core/ranges.pct()`:

| Seat | Engine RFI | Target band | Open size |
|---|---|---|---|
| UTG | 16.1% | 15–17% | 2.5bb |
| HJ  | 22.5% | 19–22% | 2.5bb |
| CO  | 27.0% | 25–28% | 2.5bb |
| BTN | 45.7% | 40–45% | 2.5bb |
| SB  | 32.1% | 35–45% | 3.0bb |
| BB  | — (defends) | — | — |

*Why the chain widens:* fewer players left to act reduces the chance of being
3-bet, and later position means acting last on every postflop street, so
speculative hands realise more equity. Each step back from UTG adds ~5pp; the
BTN jumps because only two opponents remain.

*Why 2.5bb:* 2bb gets called too wide and builds pots out of position; 3bb wins
more folds but makes bluffs and 3-bet pots expensive. 2.5bb sits between.

### 1.2 3-bet ranges (polarised)

Value: `TT+, AJs+, AQo+, KQs`. Bluffs: suited-wheel aces (`A5s–A3s`), `K5s`,
`K4s`, suited connectors (`76s`, `65s`, `54s`) — hands with blockers and
playability when called. IP 3-bet ≈ 8%, in the blinds ≈ 9–11%.

### 1.3 Defence vs an open (call + 3-bet combined)

The BB already has 1bb invested, so it defends wide; MDF against a 2.5bb open is
~54%, and solvers land at roughly 38–63% depending on the opener:

| Opener | Engine defend width | Typical solver figure |
|---|---|---|
| UTG | 37.9% | ~38–40% |
| HJ  | ~42% | ~45% |
| CO  | 41.8% | ~48–58% |
| BTN | 63.2% | ~55–65% |
| SB  | ~44% | ~47–55% |

### 1.4 Short stacks: push/fold

At ≤15bb the engine abandons postflop play and uses 10bb shove charts
(`SHOVE`): BTN ~41%, CO ~32%, HJ ~22%, UTG ~16%, SB ~45%, BB ~28%.
Playing push/fold correctly at 10bb is worth more than any postflop refinement.

---

## 2. Postflop: the four numbers that decide every spot

### 2.1 Pot odds (callers)

```
required equity = call / (pot + call + call)
```
Bet 5 into 10 → call 5, final pot 20 → 25%. A half-pot bet gives the caller 25%.

### 2.2 Alpha (bettors)

```
alpha = bet / (pot + bet)
```
A half-pot bluff risks 5 to win 10 → needs 33% folds. This is the break-even
fold frequency for a zero-equity bluff and it is what `decide_postflop` compares
against the opponent's measured `fold_to_bet`.

### 2.3 MDF (defence floor)

```
MDF = pot / (pot + bet) = 1 - alpha
```

| Bet (% pot) | 25% | 33% | 50% | 66% | 75% | 100% | 150% | 200% | 300% |
|---|---|---|---|---|---|---|---|---|---|
| MDF | 80% | 75% | 67% | 60% | 57% | 50% | 40% | 33% | 25% |

Two patterns the engine relies on:

1. Bigger bets demand *less* defence — that is why polarised overbets work.
2. MDF compounds across streets: 60% × 60% × 60% ≈ 22% of your starting range
   reaches a river call against a triple barrel. Over-defending the river is a
   classic leak; the engine treats MDF as a *range* floor, never as a reason to
   call with one specific hand that lacks pot odds.

MDF is a river benchmark. On the flop, bluffs still have equity and future
streets exist, so raw MDF overstates how much you should continue — the engine
uses MDF only as a displayed reference plus a tie-breaker in the call margin,
and lets pot odds + equity make the actual decision.

### 2.4 SPR (stack-to-pot ratio) and commitment

```
SPR = effective stack / pot
```
Commitment threshold used by `spr_commitment_threshold()`:

| SPR | Stack off with |
|---|---|
| ≤1.0 | any pair |
| ≤2.5 | two pair+ |
| ≤4.0 | trips+ |
| ≤7.0 | straight+ |
| >7.0 | flush+ |

With SPR ≤2.5 you are committed with top pair-type strength; at SPR 10 you are
not. The engine additionally requires `strength >= commit_cat - 2` before
raising for value.

### 2.5 Value : bluff ratio

Balanced river betting ranges: `value share = 1 - alpha`. A pot-sized bet means
1:1 value to bluffs; a 2x pot overbet means 2:1 (two bluffs per value hand).
`core/mathx.py::value_bluff_ratio()` returns this, and the Risky profile inflates
bluff frequency above the balanced number (that is the definition of risky).

### 2.6 Equity realisation

Raw equity is not realised equity. Out of position you realise ~85–90% of it;
in position ~105%; suited/connected hands realise more; multiway less.
`equity_realization()` returns a multiplier applied to every MC estimate:
IP ×1.06, OOP ×0.88, ±0.04 suited, −0.05 multiway, clamped to [0.55, 1.20].

---

## 3. Equity engine

Three layers, all measured rather than assumed:

1. **169-class preflop table** (`data/preflop_equity.json`, built by
   `tools/build_preflop.py`): equity for every hand class against 1, 2, 3, 4 and
   5 random opponents, 1,200 MC iterations each. Measured values match
   published figures: AA 85.4% HU → 49.3% five-way; AKs 68.8% → 33.2%;
   72o 35.7% → 8.9%. (A naive power-law "multiway adjustment" gets this badly
   wrong — it was removed.)
2. **Range-aware MC** (`equity_vs_ranges`): opponents are not random. Each seat
   carries an estimated range width that narrows as it acts — opening tightens
   to its RFI width, calling to its defend width, and every postflop bet
   multiplies the width by 0.45 (call ×0.62, check ×0.88). Equity is then
   sampled from the top-X% of hands by playability. This is the single biggest
   realism upgrade over "equity vs random".
3. **Board texture + draw equity**: `board_texture()` scores flush/straight
   connectivity and broadway content into dry/medium/wet, which sets bet sizing;
   `draw_equity()` prices flush draws (~18%), open-enders (~16%), gutshots (~9%)
   and overcards (~6%), capped at 42%.

---

## 4. The three strategies

Shared frame, different parameters. Nothing is hand-waved: each difference
below maps to a named constant on the class.

| Parameter | Safe | Optimal | Risky |
|---|---|---|---|
| Range adjust | −7pp | 0 | +9pp |
| BTN open | 38.5% | 45.7% | 54.8% |
| UTG open | 8.9% | 16.1% | 25.2% |
| Bluff frequency | 0% | 10% | 28% |
| Call margin (equity cushion over pot odds) | +9pp | +2pp | −1pp |
| Sizing multiplier | 0.72× | 1.0× | 1.35× |
| Value threshold | 68% | 62% | 55% |
| Raise threshold | 78% | 70% | 62% |
| Open size | 2.2bb | 2.5bb | 3.0bb |
| 3-bet size | 2.8× | 3.0× | 3.6× |
| Draw trust | 0.35 | 0.50 | 1.15 |

**Safe** — narrows every range by 7 percentage points, never bluffs, demands a
9pp equity cushion before calling, bets ~72% of standard sizing for pot control,
and folds anything marginal. Its edge comes from not paying off; its cost is
that it is trivially exploitable by aggression (it over-folds vs barrels) and it
leaves value on the table.

**Optimal** — the solver-shaped baseline: published RFI/defend frequencies,
pot-odds thresholds with a 2pp cushion for model error, MDF-aware defence,
texture-driven sizing (⅓ dry, ⅔ wet, +10% on the river), balanced bluffing at
alpha.

**Risky** — everything widened and polarised: +9pp ranges, off-chart steals at
12%, light 3-bets, overbets (1.35× sizing), semi-bluff raises on draws, thin
value at 55%, and calls with implied odds when equity is within 15% of the
price. Maximum fold equity, maximum variance — exactly what the confidence
intervals in the dashboard will show you.

---

## 5. Opponent model

Five archetypes (`game/opponents.py`), each an `OptimalStrategy` with bent
parameters plus per-spot jitter, so identical spots do not play identically:

| Archetype | VPIP | PFR | Fold-to-bet | Aggression |
|---|---|---|---|---|
| TAG | 22 | 18 | 45% | 1.8 |
| LAG | 34 | 27 | 32% | 2.6 |
| Calling station | 56 | 7 | 26% | 0.5 |
| Nit | 13 | 10 | 63% | 1.2 |
| Maniac | 71 | 52 | 16% | 4.2 |

The hero's bluff logic keys off the *actual* `fold_to_bet` of the opponent in the
hand, so bluffing a nit and bluffing a station are different decisions.

---

## 6. Engine correctness

`game/table.py` implements real no-limit rules: min-raise tracking, all-in for
less, multi-street side pots by contribution layer, BB option, heads-up blind
order, rebuys. `tests/test_engine.py` asserts:

- chip conservation over 120 hands per strategy (600 chips in, 600 out),
- side-pot conservation with three different stack sizes,
- no fold when checking is free,
- no bet/raise exceeding the remaining stack.

Run it with `python3 -m tests.test_engine`.

---

## 7. Live-play additions (pokerpatio.com)

The same three policies drive a real table; only the state source changes.

| Simulator input | Live-site input |
|---|---|
| hole/board | `.player.is-this-player .hand .card[data-face-up=true]`, `#communityCards .card` |
| pot | sum over seats of (start-of-hand stack − current stack) |
| to_call | max seat `.stage-bets` − my `.stage-bets` |
| seat/position | offset from the seat holding `.icon.dealer` |
| min raise | `.actions[data-min-bet]` |
| opponent ranges | one configurable width (default 55%) for every villain |

Two adjustments matter:

* **Pot from stacks, not the pot widget.** The site's `.pot-total span` is the
  *collected* pot and `data-total-stage-pot` is only the current street's delta,
  both animated. Deriving the pot from stack deltas is exact and immune to that.
* **Check is a fold in disguise.** When nothing is owed the site hides the CHECK
  control and the FOLD button carries `data-sub-type="check_if_unnecessary"`, so
  the runner clicks that instead of forcing a hidden control.

Slow pace on purpose: the site's seats run their own 3–10 s timers, so a live
session sees 2–5 hands/min. That is the platform's clock, not the bot's.

---

## 8. Known limits (read this before trusting a number)

- **No rake.** Real micro/low-stakes games rake 5% capped, which flips many
  marginal spots. Everything here is rake-free, so results skew optimistic.
- **No ICM / tournament dynamics.** This is a cash-game model.
- **Opponents are models, not humans.** They do not adapt to the hero, so the
  hero's exploitative edges are overstated once ranges converge.
- **Equity is sampled.** 45 iterations in batch mode means ±7% per decision;
  the live bot uses 220+. Raise the iteration count for cleaner decisions.
- **Range tracking is a heuristic**, not a Bayesian range reconstructor: widths
  come from the acting player's own range definitions, not from a solved
  posterior.
- **pokerpatio.net is a parked domain.** No live client exists to attach to, so
  all results come from the local engine (see README, "Site adapter").
