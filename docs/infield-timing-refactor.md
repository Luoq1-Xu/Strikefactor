# Time-based infield plays

Making "is it a hit?" a race between the throw and the runner, instead of a
question about whether two circles overlapped.

---

## 1. What decides an infield hit today

Nothing that resembles baseball. For a batted ball the outcome arrives as
`IN_PLAY` from [hit_outcome_manager.py](../strikefactor/gameplay/hit_outcome_manager.py)
— `_resolve_outcome` rolls only the home run and defers everything else — and
the animation settles it geometrically in
[`_check_in_flight_intercept`](../strikefactor/gameplay/hit_animation.py):

> a fielder is eligible, has passed their reaction delay, the ball's **shadow**
> is within `INTERCEPT_REACH_PX` (12 px) of their body, and the ball's lift is
> under `INTERCEPT_MAX_LIFT_PX` → **out**.

If nobody's body touches the ball's shadow, it's a hit, and `SINGLE` /
`DOUBLE` / `TRIPLE` is then decided by how many milliseconds the outfielder
took to pick it up (`RETRIEVE_TIME_SINGLE_MAX_MS` = 2800, `..._DOUBLE_MAX_MS`
= 4200).

The throw to first exists — `GO_FIELD_HOLD_MS`, `GO_THROW_MS`,
`GO_CATCH_HOLD_MS`, the whole `COVER_ROLE_PRIORITY` mechanism — but it is
**presentation played after the verdict is already in**. Nothing about it can
change the call.

What that costs, concretely:

- **There is no runner.** Batter speed, handedness, hustle — none of it can
  matter, because nothing is racing anything.
- **There is no throw.** A ball fielded cleanly at the edge of the outfield
  grass and a ball fielded on the lip of the infield dirt are the same out.
- **Slow rollers are backwards.** A squibber gives the fielder *more* time to
  reach it, so the animation converts it more often — where in reality the
  slow roller is the canonical infield hit.
- **Bang-bang plays cannot exist.** Every play is decided by a 12 px overlap,
  so the margin is always enormous in one direction or the other.
- **The deep-vs-shallow axis is inverted.** A SS ranging into the hole is
  *more* likely to record the out here (they touched it), where reality says
  that is the play the runner most often beats.

---

## 2. The obstacle that has to be dealt with first: there are two clocks

This is the part that makes it a refactor rather than a patch.

The animation's flight time comes from `HIT_BASE_DURATION_MS = 3300`, scaled
by contact quality. Measured against the distance the ball actually covers:

| contact quality | animated flight | ball's implied average speed |
|---|---|---|
| q = 0.2 | 3.70 s to 140 ft | 37.9 ft/s (**26 mph**) |
| q = 0.5 | 3.30 s to 140 ft | 42.4 ft/s (**29 mph**) |
| q = 0.9 | 2.77 s to 140 ft | 50.5 ft/s (**34 mph**) |

A ball struck at 90–100 mph is rendered as though it were rolling at 26–34
mph. The animation clock runs roughly **2.5× slow**.

That dilation has already leaked into the fielding constants.
`FIELDER_MAX_SPEED_PX_MS` is set to 40 px/s ≈ **27 ft/s**, which is a correct
MLB sprint speed — but it is spent against a 3.3 s clock instead of the ~1.3 s
a real grounder allows, so fielders cover ~2.5× the ground they should. Every
one of these constants exists to claw that back:

- `INFIELD_LOW_BALL_RANGE_PX = 55` — its comment says so outright: *"a fielder
  sprinting at a realistic speed through that stretched clock covers two to
  three times the ground they ever could in reality"*
- `FIRST_BASE_GROUNDER_RANGE_PX = 55`
- `INFIELD_CHASE_RANGE_PX = 130`
- `ROLE_MAX_INTERCEPT_DIST_PX`, `PITCHER_CLEAN_FIELD_PROB`

None of those are physics. They are all corrections for the clock.

**Correction, after implementing it.** This section originally claimed the
clock had to be unified *before* the verdict could become time-based —
that a timing model on the dilated clock "would disagree with the picture."
That was overstated, and implementation showed why:

- The verdict never reads the animation clock. It is computed from the
  **geometry in feet** and the modelled exit velocity, so the dilation
  cannot leak into it.
- A viewer cannot perceive absolute seconds. What they see is the fielder
  come up with the ball, throw, and the runner beat it or not — which is
  the play either way.

What the dilation actually distorts is **fielder range** — which balls get
fielded at all — not what happens once one is. Those are separable, and the
range half is already compensated (badly, but compensated) by the cap
constants. So the verdict work shipped first, on the existing clock.

Unifying the clock is still worth doing, but for its own reasons: it retires
the cap constants and makes ball-travel time consistent between the model and
the animation. It is no longer a prerequisite.

### The fix: one real-time model, one presentation scale

Do all physical reasoning in **real seconds and feet**. Render it through a
single explicit constant:

```python
PRESENTATION_TIME_SCALE = 2.5   # 1 real second is shown over 2.5 animated seconds
```

Everything physical is specified in real units and divided by that scale once,
at the rendering boundary. The play still *looks* the way it looks today
(slow, readable, watchable — that pacing is a deliberate and good choice), but
it is now a uniform slow-motion replay of a real play rather than a real-speed
fielder inside a slow-motion ball flight.

The payoff beyond correctness: **the range-cap constants stop being needed.**
A fielder moving at 27 ft/s ÷ 2.5 on the dilated clock automatically covers
exactly the ground a real fielder covers in the real flight time. The whole
`INFIELD_LOW_BALL_RANGE_PX` / `INFIELD_CHASE_RANGE_PX` / reach-vs-legs split
that the last few rounds of work has been fighting collapses into a single
honest speed. That is a large simplification of the most heavily-patched part
of this file.

---

## 3. MLB reference numbers

Statcast's infield Outs Above Average model is built as exactly this race, so
the framing is borrowed rather than invented. Tango's original infield OAA
writeup walks a real play through the same four components: intercept time
from release, the fielder's distance to first at that moment, a throw at "a
bit over 100 ft/s", and ~¾ of a second to release.

**Two clocks, both starting at contact:**

```
defense = ball travel to fielder + fielder release + throw flight
offense = batter's home-to-first
```

### Runner: home to first

| source | RHB | LHB |
|---|---|---|
| Scouting standard (max effort) | ~4.3 s | ~4.2 s |
| Biomechanics (Coleman & Dupler) | 4.35 s | 4.31 s |
| Statcast 2016, all non-bunt runs | 4.62 s | 4.58 s |
| Elite (records) | 3.72 s (Buxton) | 3.61 s (Hamilton) |

**Use ~4.3 / 4.2, not 4.62.** The Statcast league average includes jogs on
obvious outs; our batter is always hustling on a play that's close enough to
matter. This distinction was wrong in the first draft of this document.

By position, if batter-as-defender realism is ever wanted: CF 4.16, SS 4.26,
2B 4.27, 3B 4.39, C 4.48, 1B 4.50.

**Sprint Speed is a trap.** League average 27 ft/s, elite 29–30, slowest
23–25 — but it is a *top-speed* metric measured over the fastest one-second
window, **not** an average over the run. `90 ft ÷ 27 ft/s = 3.33 s` is
nonsense; the real answer is 4.3 s. A runner averages ~77% of top speed over
home-to-first. Rather than model acceleration explicitly, fit the two
endpoints:

```python
HOME_TO_FIRST_S = 4.30 - 0.143 * (sprint_fts - 27.0)   # clamp [3.6, 5.0]
```
which gives 4.30 s at 27 ft/s, 3.87 s at 30, 4.87 s at 23 — matching the
observed spread, with LHB −0.10 s on top.

### Ball: contact to the fielder's glove

Dominant variance driver. A grounder bleeds speed to bounces and friction:
effective average is **60–75% of exit velocity** for a typical ground ball,
and materially lower for a topped roller.

| contact | ~EV | to a normally-positioned IF |
|---|---|---|
| Scorched | 95–100 mph | **1.3–1.5 s** (140 ft) |
| Medium | 85–90 mph | **1.6–1.8 s** |
| Topped chopper | ~45 mph | **2.5–3.5 s** (110 ft to 3B) |

*(The first draft had 2.0 s for a medium grounder — too slow.)*

### Fielder: glove to release

**The weakest link in the chain** — there is no public infielder release
leaderboard. Tango's **0.75 s** is the anchor. Catcher exchange time gives a
usable distribution *shape*: MLB average 0.73 s, elite 0.64, poor 0.85 — a
footwork-included transfer that maps reasonably onto an infielder planting
and throwing.

| | time |
|---|---|
| Barehand charge on a slow roller | 0.50–0.60 s |
| **Routine, set, on balance** | **0.75 s** |
| Backhand / from the hole / off balance | 0.90–1.00 s |

Because it is the least-documented input, it is also **the right calibration
dial**: tune release time until the simulated infield-hit rate hits target
(§4), rather than fudging any of the better-sourced numbers.

### Throw to first

**Statcast "arm strength" is not throw speed.** It is the average of a
player's top 5% of throws (min 75), so those leaderboard figures — 85–95 mph
for infielders, high 90s for elite arms — are *max effort*. The first draft
misread them as typical.

For flight time use **effective average speed**, which accounts for drag over
the throw and for most throws not being max effort: a ball sheds ~8–10% of
velocity per 55 ft, so a 90 mph release across 130 ft arrives near 72 mph and
averages ~80. **Use 100–115 ft/s for a routine throw across the diamond.**

Bases sit at 1B (63.64, 63.64), 2B (0, 127.28), 3B (−63.64, 63.64) — which is
exactly the game's existing `_BASE_AXIS_FT = 90/√2`, so no geometry change is
needed.

| from | distance to 1B | flight @ ~110 ft/s |
|---|---|---|
| SS | 120–135 ft | ~1.15–1.25 s |
| 3B | 110–127 ft | ~1.05–1.15 s |
| 2B | 75–90 ft | ~0.70–0.80 s |
| 1B | 35–55 ft | ~0.4 s, or unassisted step |

### Does it reproduce baseball?

| play | intercept | release | flight | defense | batter | result |
|---|---|---|---|---|---|---|
| Routine grounder to SS | 1.50 | 0.75 | 1.30 (130 ft) | **3.55** | 4.30 | out by 0.75 s |
| Slow roller, 3B charging | 2.60 | 0.60 | 0.90 (95 ft) | **4.10** | 4.30 | out, bang-bang |
| Same play, fast LHB | 2.60 | 0.60 | 0.90 | **4.10** | 4.00 | **infield hit** |
| Deep in the hole, SS | 2.00 | 0.95 | 1.45 (150 ft) | **4.40** | 4.30 | **infield hit** |

Routine grounders out by half a step to a step; charges and hole plays inside
a tenth or two. That spread is what MLB looks like, and it is what the current
12-pixel overlap test can never produce.

---

## 4. Calibration targets — from your own database

This is what the refactor has to hold, and it is measured, not assumed. Balls
in play by month, from `strikefactor.db`:

| month | BABIP | 2B/1B | note |
|---|---|---|---|
| 2026-03 | .712 | 0.62 | |
| 2026-05 | .558 | 0.62 | |
| 2026-06 | .368 | 1.10 | fielding work lands |
| 2026-07 | .378 | 1.28 | |
| 2026-08 | **.395** | **0.96** | current |
| **MLB** | **.290** | **0.32** | target |

Two separate problems, and the data says the second one is bigger:

1. **Too many balls in play fall in** — BABIP .395 vs .290. The fielding work
   already brought this from .712, and the timing model is the right tool to
   close the rest.
2. **Far too many of the hits are extra-base hits** — 2B/1B is 0.96 where MLB
   is 0.32, and triples are ~7% of hits where MLB is ~1%. This is *not* an
   infield problem; it is the `RETRIEVE_TIME_*` thresholds deciding bases by
   outfielder pickup time with no runner in the race.

The user asked about infield hits, which is problem 1. **Problem 2 is the
larger distortion and yields to exactly the same technique** — see Phase 4.

### Two different rates, which the first draft conflated

- **~24% of ground balls become hits** — but *mostly by going through the
  infield untouched*, not by being beaten out.
- **Of grounders actually fielded by an infielder, only ~6–8% are beaten
  out.**

These are separate gates and must be validated separately. The first is
governed by fielder positioning and range (already largely working — that is
what the recent fielding passes fixed). The second is what this refactor
introduces. **If the infield-hit rate on fielded balls comes out much above
8%, the time budget is too generous** — and per §3 the dial to turn is
release time.

### Guardrails so it doesn't become unplayable

The failure mode of a physics-honest model is that it is *correct and no fun*:
a real MLB defense converts ~76% of ground balls, and a player who mostly hits
grounders will feel like they can't get a hit.

- **Don't threshold the margin — use a logistic.** A hard `margin > 0 → out`
  makes every play deterministic and the sim brittle at the boundary. Instead:

  ```python
  p_out = 1 / (1 + exp(-margin_s / SIGMA_S))     # SIGMA_S ≈ 0.10–0.15
  ```

  The sigma is doing real work: it absorbs throw accuracy, the first
  baseman's scoop, umpire error, and the batter's own variance. At σ = 0.12 a
  play that is "out by 0.1 s" comes out ~70–80% an out rather than a
  certainty — which is precisely how a bang-bang play should feel. This
  replaces the additive `TIMING_JITTER_S` the first draft proposed; the
  logistic is better motivated and needs one constant instead of two.
- **Bang-bang frequency then falls out for free** rather than being
  engineered. Sanity-check that |margin| < 0.15 s lands around 8–12% of
  fielded infield plays; if it is near zero, sigma or the inputs are wrong.
- **Calibrate to the aggregate, not to the model's purity.** Target GB BABIP
  ~.240 and total BABIP ~.290. Adjustment goes into release time first (§3),
  then the runner clock — visible dials, not a fudge on the verdict.
- **Difficulty maps onto the runner clock, not onto a probability.**
  `out_probability_modifier` becomes a time offset: ROOKIE gives the batter
  −0.25 s to first, HALL_OF_FAME +0.15 s. Far more intelligible than the
  current multiplier, and it keeps difficulty from breaking the physics.
- **Separate difficulty-of-play from outcome.** Statcast scores force plays
  using the runner's *average* sprint speed rather than his speed on that
  particular play, so a runner who gives up halfway doesn't make the fielder
  look good. Keep the same split here: the play's difficulty (and anything we
  ever log or grade off it) uses the batter's baseline speed; only the actual
  safe/out call uses this-play effort.
- **Never let the verdict contradict the picture.** The animation must play
  the throw and show the runner; if the model says safe by 0.1 s the screen
  has to show safe by 0.1 s. This is what §2 buys.

---

## 5. Proposed design

### A new pure module: `strikefactor/gameplay/infield_timing.py`

Modelled on [contact_audio.py](../strikefactor/engine/contact_audio.py) — no
pygame, no game state, no animation objects, so it is unit-testable and
tunable in isolation. That module is the precedent for how this codebase likes
its physics: pure, calibrated against a table, guarded by tests.

```python
@dataclass(frozen=True)
class PlayTiming:
    ball_to_glove_s:  float
    release_s:        float
    throw_flight_s:   float
    defense_s:        float       # sum of the three above
    runner_s:         float
    margin_s:         float       # runner_s - defense_s; > 0 favours the defense
    p_out:            float       # logistic(margin_s / SIGMA_S)
    is_bang_bang:     bool        # |margin_s| < BANG_BANG_S

def ball_travel_time_s(ev_mph, path_distance_ft) -> float
def release_time_s(role, ranging_ft, is_charging, is_backhand) -> float
def throw_time_s(fielder_xy_ft, effective_throw_fps) -> float
def home_to_first_s(handedness, sprint_fts, difficulty_offset_s) -> float

def resolve_infield_play(...) -> PlayTiming
```

The core is small enough to state outright:

```python
def resolve_infield_play(intercept_s, fielder_xy_ft, release_s,
                         throw_fps, runner_s, sigma_s=SIGMA_S):
    dx, dy = FIRST_BASE_FT[0] - fielder_xy_ft[0], FIRST_BASE_FT[1] - fielder_xy_ft[1]
    flight_s = math.hypot(dx, dy) / throw_fps
    defense_s = intercept_s + release_s + flight_s
    margin_s = runner_s - defense_s
    return PlayTiming(..., p_out=1.0 / (1.0 + math.exp(-margin_s / sigma_s)))
```

Returning a *timing*, not a boolean, is deliberate: double plays, tag plays
and force outs all need the components rather than the verdict, so this keeps
that door open (§7).

### Where it plugs in

`HitAnimation` already knows everything the model needs at the moment a
fielder reaches the ball:

| model input | already available as |
|---|---|
| exit velocity | `contact_audio.exit_velocity_mph(self.quality, swing_type)` |
| fielder + position | `self._primary_role`, `fielder.pos`, `home_pos` |
| distance ball travelled | `self._ball` vs `HOME`, ÷ `FT_TO_PX_*` |
| ranging distance | `math.dist(fielder.pos, fielder.home_pos)` |
| batter handedness | `self.game.batter.get_handedness()` |
| difficulty | `settings_manager.get_difficulty_multipliers()` |

The change at the call site is small: `_check_in_flight_intercept` stops
*deciding* and starts *reporting*. Reaching the ball becomes "the fielder
fielded it", and `resolve_infield_play` then says whether the throw beat the
runner. The existing throw sub-animation (`GO_*`, `COVER_ROLE_PRIORITY`) stops
being decoration and becomes the actual play, with a SAFE/OUT at the end of
it.

### Runner speed

Currently there is no batter-runner at all. Minimum viable: a per-play
`sprint_speed_fts` drawn from a distribution (league mean 27 ft/s, σ 1.8),
plus the LHB bonus. A later step could make it a real batter attribute, which
would also give `BatterProfile` something new to model.

---

## 6. Phasing

> **Status.** The model (`gameplay/infield_timing.py`) and the infield
> verdict are **done and shipped** — what were Phases 2 and 3. They landed
> before the clock work because §2's prerequisite claim turned out to be
> wrong. Measured on 1200 grounders: infield-hit rate on fielded balls
> **7.6%** (target 6–8%), bang-bang **7.5%**, and the sign flip holds —
> soft contact beaten out 8.7%, scorched contact 0.0%. Phase 0 (schema),
> Phase 1 (clock) and Phase 4 (extra bases) remain.

Each phase is shippable and independently verifiable.

**Phase 0 — make it measurable.** Add `batted_ball_type`, `fielder_role`, and
`play_margin_s` to the `pitches` table (`SCHEMA_VERSION` bump + `_migrate`
branch, per the CLAUDE.md recipe). *Today the DB cannot distinguish a ground
ball from a fly ball*, so there is no way to check a ground-ball model against
recorded play. Do this first or Phase 3 is unfalsifiable.

**Phase 1 — unify the clock.** Introduce `PRESENTATION_TIME_SCALE`. Respecify
fielder speed, reaction delays and the `GO_*` throw timings in real units,
divided by the scale at the render boundary. Delete the range caps that exist
only to correct the dilation. *Verification: the existing fielding tests must
still pass, and out rates must not move — this phase is a change of units, not
of behaviour.* This is the riskiest phase and it carries no user-visible
feature, which is exactly why it should be its own step.

**Phase 2 — build the model.** `infield_timing.py` plus its tests, calibrated
against the §3 table. Pure, no integration. Verify the five reference plays
reproduce their expected margins.

**Phase 3 — switch the infield verdict over.** `_check_in_flight_intercept`
reports, `resolve_infield_play` decides. Play the throw. Show SAFE/OUT.
*Verification: infield-hit rate on **fielded** grounders lands at 6–8% (the
gate this phase introduces); GB BABIP near .240; bang-bang plays 8–12%; and
slow rollers become hits more often than scorched grounders — the sign flip
that proves the model, not the geometry, is doing the work.*

**Phase 4 — extra bases, same technique** (optional, and per the data the
higher-value one). Replace `RETRIEVE_TIME_SINGLE_MAX_MS` / `..._DOUBLE_MAX_MS`
with a race: runner time to second/third vs retrieve + relay. Target 2B/1B
0.96 → 0.32 and triples 7% → 1% of hits.

---

## 7. Risks

- **Phase 1 is a units change across the most-patched file in the repo.**
  `hit_animation.py` is ~3100 lines and its constants are interdependent and
  heavily documented. Mitigation: it is behaviour-preserving by construction,
  so the existing tests are a real gate — if out rates move in Phase 1,
  something was mis-scaled.
- **The honest model may be less fun.** 76% of grounders being outs is
  correct and may not be enjoyable. Mitigation: the runner clock is the dial,
  and difficulty already exists to move it. Decide the target BABIP as a
  *game design* choice, then let the model hit it.
- **Double plays, tags, and force outs are not modelled** and interact with
  all of this. Out of scope here; the model should be shaped so they can be
  added (`resolve_infield_play` returning a timing, not a boolean, is what
  keeps that door open).
- **Fielder release time is the weakest-sourced input** — no public infielder
  leaderboard exists, so the 0.75 s ± 0.15 range rests on Tango's figure plus
  the catcher-exchange distribution as a shape proxy. This is a risk *and*
  the reason it is the designated calibration dial: it is where uncertainty
  already lives, so tuning it doesn't corrupt a better-measured number.
- **Sprint Speed must not be used as an average.** It is a top-speed metric;
  dividing 90 ft by it yields 3.3 s against a real 4.3 s. Use the fitted
  home-to-first mapping in §3.
- **Statcast arm strength must not be used as throw speed.** It is the
  average of a player's top 5% of throws. Use the 100–115 ft/s effective
  flight speed instead.
