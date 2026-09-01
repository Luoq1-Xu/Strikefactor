# Defense strength

A setting for how good the nine gloves behind the pitcher are — and, with it,
the first fielding errors this game has ever had.

---

## 1. What the defense was before this

A fixed league-average team, with no dial and no way to fail. Four constants
described all nine fielders: `FIELDER_SPRINT_FT_S = 27.0`,
`REACTION_DELAY_MIN/MAX_S = 0.200/0.380`, `RELEASE_ROUTINE_S = 0.80`,
`THROW_EFFECTIVE_FTS = 110.0`.

More importantly, **reaching the ball *was* fielding it.** Ground balls got a
probabilistic verdict from `infield_timing.roll_is_out`, but fly balls, liners
and pop-ups did not: `_check_in_flight_intercept` is pure geometry, and once a
fielder's body came within `INTERCEPT_REACH_PX` of the ball's shadow the out was
**certain**. A search for `error|bobble|muff|misplay|drop` across the gameplay
layer returned batter aim error and Python exceptions and nothing else.

§8 of [infield-timing-refactor.md](infield-timing-refactor.md) had already named
this as the outstanding work — bang-bang plays at 5.3% against a target of
8–12%, ground-ball hits at 21.3% against ~24% — and identified the cause:

> our fielders execute a clean route on every ball they can reach; MLB's do not

and the fix as "a fielding-difficulty model … rather than one flat probability,
which is Statcast's infield OAA and a project of its own." This is that project,
with a player-facing dial on it.

---

## 2. Design

### A pure module, and a profile that is a value

`gameplay/defense.py`, on the `contact_audio` / `infield_timing` contract: real
feet and seconds, no pygame, no game state. Three reasons it is shaped this way
rather than as a settings read:

1. **It is the only shape the calibration harness can sweep.** A `DefenseProfile`
   is a value; a `SettingsManager` is not. Every number below was tuned by Monte
   Carlo, and a harness that must build a settings object per level is a harness
   nobody runs.
2. **It gives the neutral row a job.** `LEAGUE` is *defined* to restate the
   existing constants, which turns the integration step into a verifiable no-op.
3. **`infield_timing` must not learn a second concept.** It arbitrates one race;
   handing it `release_scale` and `misplay_s` as plain numbers keeps it that way.

The profile reaches the game as a `HitAnimation(..., defense=)` kwarg, resolved
by `PitchSimulation._defense_profile()`. Reading `game.settings_manager` inside
the animation was rejected: every fielding test builds a stub game that has no
settings manager at all, and the correct stub answer is "neutral", which a
default kwarg already says.

### The identity, and why it is the load-bearing test

`LEAGUE` is not *approximately* today's game. Measured over 900 balls in play,
passing `defense=None` and `defense="league"` produced **zero differing plays** —
identical outcomes and identical margins, because the arithmetic is the same and
the RNG is consumed identically.

That is what made this safe to wire into the most-patched file in the repo.
`test_the_neutral_profile_changes_nothing_at_all` is the pin.

> Worth contrasting with the clock unification, whose Phase 1 claimed "out rates
> must not move" and was wrong — because the range caps it replaced had been a
> hand-fit approximation. A units change is only behaviour-preserving when the
> thing being replaced was exactly right, which is never why you are replacing
> it. Here it *is* exactly right, by construction, and a test says so.

### One draw, three outcomes

The rule that keeps the misplay model **one** model rather than a second verdict
that can contradict the first:

> the race decides whether there was a play; the misplay decides whether it was
> made.

```python
p_out       = p_out_from_margin(margin_s)                 # with the misplay
p_out_clean = p_out_from_margin(margin_s + misplay_s)     # without it

u = rng.random()
if u < p_out:       return "OUT"
if u < p_out_clean: return "ERROR"
return "HIT"
```

One draw, common random numbers. The window `[p_out, p_out_clean)` is *exactly*
the set of plays that would have been outs without the misplay and were not with
it — the official scorer's rule, arrived at rather than judged. Two independent
draws could not express it: they would charge errors on plays the runner was
beating anyway, and let plays the misplay genuinely cost go uncharged.

It also makes the picture and the record structurally unable to disagree. The
throw the player watches is scheduled off `release_s`, which *contains*
`misplay_s`; the verdict is drawn against `p_out`, computed from the same number.

And it gets a real baseball answer for free: a ball through a diving fielder in
the hole has a low `p_out_clean` — it was bang-bang anyway — and is scored a
**hit**; the same ball through a fielder standing still on a routine hop has a
high `p_out_clean` and is an **error**.

### Three mechanisms, told apart by what happens to the ball

| | what happens | where it fires | how it is charged |
|---|---|---|---|
| **BOBBLE** | retained, costs `MISPLAY_COST_S` on release | either reach path | `roll_verdict`'s window |
| **THROUGH** | not stopped; carries into the outfield | in-flight reach only | counterfactual `p_out` at the reach |
| **MUFF** | dropped, dead at the fielder's feet | in-flight reach, air balls | always (the clean play was a catch) |

A ball does not go "through" a fielder who was going to catch it — that is a
drop. And a through-ball fires only from `_check_in_flight_intercept`, never
from the securing gate: a ball does not go through you while you are jogging up
to a dying roller. That asymmetry is physical, and it keeps the slow roller the
canonical *infield hit* rather than the canonical error.

`body_block` is the dial for the BOBBLE/THROUGH split, because **getting the
body in front is what stops a ball you cannot glove**, and it is the most
coachable difference between a good infielder and a bad one.

---

## 3. What had to be true, and was not

Three defects found by measuring rather than by reading. Recorded because each
has a general shape.

### The gains multiply the base by 3.18×, and the base is not the rate

`field_misplay_p` was first set to 0.045 from
`P(error) = field_misplay_p × E[p_out_clean − p_out]` with `E[Δp]` guessed at
0.35. Both halves were wrong, and the second was not in the equation at all:

| | assumed | measured |
|---|---|---|
| `E[p_out_clean − p_out]` | 0.35 | **0.495** |
| mean modulation from the ranging/hop gains | *(absent)* | **3.18×** |

A fielder who came up with a ball has usually moved for it, so the gains are
near their maximum on a *typical* play. 0.045 therefore meant an 11% effective
misplay rate: errors at 3.4% of balls in play against MLB's ~1.4%, and a
ground-ball hit rate of 41%.

**A modulated base is not a rate.** Re-derive it the same way whenever the gains
or the contact distribution change.

### A "through-ball" that went through nobody

`_trigger_through` scaled the ball's speed by `through_retention`, but
`_init_ball_on_ground` builds the *nominal landing speed for the shape* — and a
grounder is intercepted partway along its path, where it is still moving far
faster than it will be when it settles.

The ball therefore left the fielder at about half of a speed it never had:

| | before | after |
|---|---|---|
| median distance past the fielder | 16.5 ft | **104 ft** |
| retrieved by the fielder it went through | 28 / 35 | **8 / 35** |
| through-balls that were still outs | 11 / 35 | **2 / 35** |

The fix takes the live speed off `infield_timing`'s retention curve — the same
curve the infield race times the ball with, so the ball that beats the shortstop
is the ball the verdict was computed against. It moved the LEAGUE error rate from
1.00% to 1.40% with no constant retuned.

**The general shape: a module that hands you an initial state built for one
situation will not silently refuse to be used in another.**

### A test that pinned an identity

`test_reaction_delays_are_real_latencies_projected_onto_the_animated_clock`
asserts `p.reaction_delay_s - p.break_delay_s == ROLE_REACTION_BIAS_S["P"]`,
which reads like a guard on the pitcher's bias. It is not:
`Fielder.__post_init__` *derives* `break_delay_s = reaction_delay_s − bias`, so
the assertion is algebra and passes whatever the numbers are.

The real constraint is that `break_delay_s` stays **positive** — scaling the
reaction band *through* the role bias drives the pitcher's toward zero, i.e. a
pitcher breaking for first before contact. `test_every_fielder_can_still_break_to_a_base`
is the successor.

---

## 4. Calibration

Measured over the batter this game actually produces — contact quality from the
recorded quantiles, spray from the recorded distribution, batted-ball type from
the recorded mix (GB 45.9% / LD 27.6% / FB 23.5% / PU 2.9%, which is markedly
liner-heavy and fly-light against MLB's ~43/21/36). n = 2500 balls in play per
level.

| | SANDLOT | MINORS | **LEAGUE** | GOLD GLOVE | target |
|---|---|---|---|---|---|
| ROE, % of balls in play | 4.28 | 3.28 | **1.40** | 1.00 | MLB ~1.4 |
| infield-hit rate on fielded GB | 16.5 | 10.9 | **7.7** | 4.4 | 6–8 |
| ground-ball hit rate | 48.2 | 39.6 | **32.5** | 25.7 | ~24 |
| BABIP | .436 | .362 | **.337** | .275 | .290 |

**`HARD_PLAY_PROB` came down from 0.22 to 0.18.** Both it and the misplay term
feed the same left tail, so they double-counted and the infield-hit rate ran
past its band. This is the better trade rather than merely the necessary one:
§8 criticises that constant *for being flat*, and the misplay term is the model
it asked for — it reads how far the fielder ranged and how hard the ball was
hit. Handing it a share of the tail replaces a hand-fit constant with a modelled
one.

**Never tune against a uniform quality sweep.** Real contact quality is crowded
toward 1.0 (p25 0.653 / p50 0.743 / p90 0.932) because it is only computed for
swings that already squared the ball up. Five constants in this repo have been
miscalibrated by assuming otherwise. The samplers live in `tests/conftest.py`
precisely so two files cannot hold drifting copies of them.

---

## 5. What is still off

**Ground-ball hit rate is 32.5% at LEAGUE against ~24%, and BABIP .337 against
.290.** Both are inherited rather than introduced — the pre-misplay build
measured 29.3% and .332 under this same harness. The harness's batted-ball mix
is the likely cause: it samples the game's own liner-heavy distribution, and
liners have much the highest BABIP. Closing it means either the contact model
producing fewer liners or the outfield alignment covering them better, and
neither is a defense-strength question.

**LEAGUE ROE sits at 1.40% but GOLD GLOVE only reaches 1.00%**, against a target
nearer 0.6%. The rungs at the top are compressed because a large share of errors
there come from through-balls on hard contact, where `hop_difficulty` dominates
`body_block`.

**The ROE ladder is not monotone at small samples.** At n = 1100 SANDLOT read
*below* MINORS; at n = 3000 it did not. Errors are rare enough that ±0.3% of
sampling noise swamps adjacent rungs — **do not tune the ladder at n < 2500**.

There is also a real mechanism pulling that way, worth knowing before it is
mistaken for a bug: a worse defense produces more through-balls, and a
through-ball is charged an error only in proportion to `p_out_clean` — which is
*lower* for a slow defense that was not going to make the play anyway. A
sufficiently bad defense gets charged fewer errors and given more hits, which is
exactly how a scorer rules it.

**Not modelled:** throwing errors that advance a runner an extra base (they need
a live-ball state *after* the throw animation, which `HitAnimation` does not
have; throw accuracy is already inside `SIGMA_S` by `infield_timing`'s own
docstring), outfield ground bobbles, and double plays — which were already out
of scope for `infield_timing`.

**Positioning is untouched.** `FIELDER_HOMES` is static and, per CLAUDE.md, was
implicitly calibrated against the uniform spray that `spray.py` replaced. It is
the largest remaining lever on BABIP and it is not a defense-strength dial.
