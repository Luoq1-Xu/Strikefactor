# Contact geometry rework: a square bat and one collision

Status: **implemented 2026-10-09** on branch `contact-geometry-rework` (cut from `main` at `1169a11`). All four stages are done and the suite is green. The plan below is kept as written; **"What was built"** at the end records the baseline, the result against each acceptance row, and where the implementation departed from the plan.

The numbers in "What the prototype measured" came from throwaway scripts that were not committed. `tools/calibrate_contact.py` is the committed harness that replaced them, and every number in "What was built" comes from it.

## The problem

Two things are wrong, and the swing replay shows both on one frame.

**The bat is never square.** On a middle-middle pitch, timed perfectly, the barrel meets the ball 2.25 ft in front of the plate with the bat 49° past square. Across the strike zone the on-time bat sits between 19° and 71° past square. The cause is in `bat_path._contact_pose`: the knob is pinned to one point for every pitch (`hands_anchor_ft`, 1.55 ft off the plate's centreline and 0.40 ft in front of it). The bat is 2.46 ft from knob to sweet spot, so the only way to put the sweet spot over the plate is to point the bat toward the pitcher.

`spray.spray_angle_deg` hides this from the outcome. It subtracts `SQUARE_REF_DEG` (49), rescales the location response (`LOCATION_GAIN`, `LOCATION_SPAN_DEG`) and multiplies the timing response by `TIMING_GAIN` (2.4). The replay then draws the real bat beside the remapped ray, which is why a bat at 43° is shown sending the ball to dead centre.

**One collision is modelled three times.** Horizontal direction comes from the bat's bearing (`spray`). Vertical direction comes from the vertical offset alone (`ball_flight.launch_angle_deg`, with `ZERO_OFFSET_LAUNCH_DEG`, `NORMAL_GAIN` and a bounded jitter). Speed comes from quality (`contact_audio.EV_CALIBRATION`). The first two are one vector in a real collision, and they interact: on a tilted bat, getting under the ball also turns it sideways. Nothing models that today.

## What this plan does

1. **Pose.** Let the hands move, so the bat is near square on a middle pitch and the ball is met about half a foot in front of the plate.
2. **Direction.** Compute one exit direction from a 3D bat-ball collision at first touch. Launch angle and spray are both read off that vector. The spray remap and the launch-angle fit are retired.
3. **Recalibrate** everything rule 5 in CLAUDE.md lists, because this changes which contacts are fair and how quality is distributed.

Exit velocity stays on `EV_CALIBRATION`. The foul verdict keeps its two limbs (quality, direction).

## Not in this plan

- **Exit velocity from the collision.** The swing has one bat speed (72 mph), so a physical exit velocity tops out near 103 mph. It needs bat-speed variation first.
- **A realistic vertical bat angle.** See "What the prototype measured", finding 5. It needs a tilted swing plane and is a follow-up.
- **A physical foul verdict** (replacing the quality threshold with where the exit vector points).
- **Outfield alignment** (`FIELDER_HOMES`), the open item in CLAUDE.md. This work re-measures BABIP and records it; it does not tune it.
- **A DB schema change.** `spray_angle_deg` keeps its meaning (the ball's bearing off the bat, pull-positive, before any foul deflection). Recording launch angle would be a new column and is not needed here.

## What the prototype measured

All rows: right-handed batter, AMATEUR, through the real `resolve_contact`, using the player model in `tests/test_spray.py` (aim scatter 0.42 ft, timing N(+19, 35) ms). This is a lighter model than the one the anchors were derived with, so the foul shares here are comparable to each other and **not** to the documented 30/31/39 split.

| | Today | Pose only, spray = bare face normal | Pose + collision |
|---|---|---|---|
| Bat bearing, middle pitch, on time | 49° past square | 7° | 5° |
| Contact depth, middle pitch | +2.25 ft | +0.70 ft | +0.61 ft |
| On-time spray, outside to inside corner | −22° to +30° | −19° to +31° | −18° to +38° |
| Ball direction per ms of timing error | 1.7° (0.7° before the 2.4 gain) | 1.0° | 1.5°, no gain |
| Contact, share of swings | 90% | 86% | 88% |
| Fouls, share of contact | 33% | 14% | 27% |
| …by direction / by quality | 18% / 27% | 1% / 13% | 23% / 17% |
| Fair spray, pull / centre / oppo | 32 / 43 / 25 | 30 / 47 / 24 | 35 / 42 / 23 |
| Fair spray sd | 21° | 20° | 22° |
| Fair launch, GB / LD / FB / PU | 41 / 24 / 28 / 7 (`BATTED_BALL_MIX`) | not measured | 58 / 20 / 18 / 4 |

The last column used the pose in "Design" below (bearing rule 5° + 27°/ft, today's hand height, body set 0.7 ft back), n = 3000.

Findings:

1. **The pose alone is not enough.** With a square bat, a mistimed ball stays on the barrel instead of sliding to the handle (quality 0.94 at 20 ms late, against 0.56 today), so quality fouls collapse. Read off the bare face normal, direction fouls collapse too.
2. **The ball does not leave along the face normal.** It leaves about 1.6 times as far round as the bat has turned, because the pitch's motion along the barrel is partly kept (a bunt off an angled bat is the limiting case). That is the physical content of `TIMING_GAIN`: with the collision in place the response is 1.5°/ms with no gain constant.
3. **The location response has to be gentler than today's on-time spread.** A bearing rule of 42°/ft put the on-time inside corner at +50°, an automatic foul. At 27°/ft it is +38°.
4. **The launch mix came out wrong.** 58% grounders, mean launch +4° against +14° today. The spread is right (sd 27°). An on-time, perfectly aimed swing launches at +8°, so the population sits several degrees under the squared-up value and the cause is not yet known. This is the main calibration job.
5. **Raising the hands breaks the timing response.** Hands at a realistic 3.6 ft give a realistic 27° barrel-down bat, but the ball's direction then turns only 0.36°/ms. The swing rotates about a vertical axis, so a tilted bat sweeps a cone, and sliding along it changes the vertical offset in the direction that cancels the turn. A real swing plane is tilted with the bat. Hand height therefore stays where it is in this plan.
6. **"Grounders are pulled, flies go the other way" is not reproduced in aggregate.** It appears only on swings with the barrel more than 15° down (grounders +4.5°, flies −0.5°). With today's hand height most swings are flatter than that. This is a consequence of finding 5 and is left to the same follow-up.
7. **The rest of the swing survives the new pose.** Across the strike zone the hand orbit runs 1.10 to 1.89 ft (1.41 everywhere today), the solved `ease_k` runs 2.04 to 2.57 inside its 1.05–3.0 rails, and barrel speed at contact is still 72 mph.

## Design

### The contact pose (`bat_path._contact_pose`)

The swing remains a function of aim and handedness only, the cursor remains a ray, and the sweet spot still lands on the cursor's ray at the solved depth. What changes is which condition closes the system. Today it is "the knob sits on the pivot". The proposal is "the bat has a stated bearing":

```
bearing = POSE_MEAN_DEG + POSE_SPAN_DEG * tanh(POSE_GAIN_DEG_PER_FT * x_in / POSE_SPAN_DEG)
depth   = HAND_CONTACT_DEPTH_FT + L * cos(tilt) * sin(bearing)        # iterate: tilt depends on depth
knob    = sweet(depth) - L * axis(bearing, tilt)
```

`x_in` is the aim's lateral position, inside-positive for either batter. `L` is `HANDS_TO_SWEET_SPOT_FT`. Tilt follows from the hand height and the ball's height as it does now.

- **The three constants are the ones `spray` already has**, moved to where they are physically true: `LEAGUE_MEAN_DEG`, `LOCATION_GAIN` and `LOCATION_SPAN_DEG` become statements about the bat. Prototype values were 5°, 27°/ft and 48°; stage 3 fits them through the collision.
- **Contact depth stays an output.** Inside pitches are met about 1.3 ft out front and outside ones 0.15 ft behind the plate's front edge. Depth can be negative now, so the `max(0.0, depth)` clamp goes and every reader of depth has to accept a negative value (`aim_at_pitch`, `timing_error_s`, the replay's `_compute_depth_range` and its `BALL AT` / `BARREL AT` readouts).
- **The body moves back.** `BatSwing.spine_xy` is `(SPINE_OFFSET_FT, 0.0)` today, level with the plate's front edge. With the hands at 2.4 ft from the centreline that leaves a 0.6 ft hand orbit, and on the inside corner the hands land behind the spine. A new `SPINE_DEPTH_FT` of about −0.7 (level with the middle of the plate) gives the orbits in finding 7.
- **Reach is bounded in feet.** Outside the zone the solved hands run away (0.8 ft from the centreline at 1.2 ft outside, 3.3 ft at 1.2 ft inside). Bound the hands' position relative to the spine; past the bound the bat falls short of the cursor and the sweep whiffs honestly, as `MAX_HAND_SLIDE_FT` does today. The bearing stays continuous in the aim.
- **The pixel pivot retires.** `PIVOT_PX` and `HitOutcomeManager.rhpos` / `lhpos` exist only to state the knob position. Restate the hand height and depth in feet and pin the removal with a `test_*_are_gone` test.

### The collision (new pure module, `gameplay/bat_ball_collision.py`)

Same contract as `spray` and `ball_flight`: real units, no pygame, no game state. One function, evaluated once per contact:

```
w      = relative velocity (ball - bat at the contact point), minus its part along the bat axis
b      = closest-approach separation, minus its parts along the axis and along w
sin(psi) = |b| / (bat_radius(along) + BALL_RADIUS_FT)
n      = -unit(w) * cos(psi) + unit(b) * sin(psi)                     # bat -> ball at first touch
v_out  = (1 + q) * (v_bat . n) n  -  q * (v_ball . n) n               # normal part
       + v_bat_tangential + keep * (v_ball - v_bat)_tangential        # tangential part
```

- **First touch, not closest approach.** The sweep reports the instant the two centres are nearest, where the separation is perpendicular to the relative velocity by construction. Used directly as the normal it describes a glancing blow on every swing. The separation at that instant is the impact parameter, and the first-touch normal is rebuilt from it.
- **Two constants, both physics and neither a dial:** `q = 0.20` (collision efficiency at the sweet spot, the standard `EV = q·pitch + (1+q)·bat`) and `keep = 5/7` (a sphere that leaves rolling). Cross and Nathan measured more grip than rolling, so `keep` may come down; decide it against their data before fitting anything else.
- **Only the direction of `v_out` is used.** Its magnitude is discarded, and that is stated in the module so nobody wires up a second exit velocity.
- **Inputs the engine already has:** `Contact.ball_ft`, `axis_point_ft`, `along`, `knob_ft`, `barrel_ft`; the ball's velocity from the trajectory; the bat's velocity at the contact point from the swing. Add an accessor for the last one on `BatSwing` and `TranslatedBatSwing` (through `_SwingTracks`, so the assisted path cannot miss it).
- **Stamped once.** `resolve_contact` computes the exit direction and `Contact` carries it. `Contact.spray_deg` and a new `Contact.launch_deg` read it. `SwingRecord` builds a `Contact` by hand for the replay (`swing_record.py`, near line 246); it must copy the stamped direction and never recompute it.
- **Deterministic.** No jitter: the collision's launch spread is already 27°. `LAUNCH_JITTER_DEG` and `JITTER_LIMIT_SIGMA` retire unless stage 3 shows the spread is too narrow under the canonical player model.

### What is retired

- `spray.SQUARE_REF_DEG`, `LOCATION_GAIN`, `LOCATION_SPAN_DEG`, `TIMING_GAIN`, `LEAGUE_MEAN_DEG` and `spray_angle_deg`. `spray` keeps `attack_direction_deg`, `is_foul`, the foul-departure functions and the frame conversions.
- `ball_flight.launch_angle_deg(vertical_offset_in)` with `ZERO_OFFSET_LAUNCH_DEG`, `NORMAL_GAIN` and `CONTACT_NORMAL_RADIUS_IN`. `HitOutcomeManager.launch_angle_deg` returns `contact.launch_deg`. `hit_animation._shape_from_offset` is a second caller and its fallback branches in `_pick_shape` need a decision (pass the launch angle in, or delete the fallback).
- `bat_path._reach`, `MAX_HAND_SLIDE_FT`, `PIVOT_PX`, the depth clamp.

### What does not change

- `Contact.attack_deg` and `pose_attack_deg` stay as facts about the bat. `batted_ball_path` still bends the flight by their difference.
- `Contact.vertical_offset_ft`, `quality` and its three scores. The DB's `vertical_offset_in` still receives the pixel offset.
- `SWING_DURATION_MS`, `PEAK_BAT_SPEED_MPH`, `ATTACK_ANGLE_DEG`, the load and follow-through.
- Every forgiveness still moves the bat and none widens it. `spray` gets no difficulty dial.

## Stages

The branch is not mergeable between stage 2 and the end of stage 3: the game runs but is uncalibrated.

**Stage 0. Commit the measuring instrument.** `tools/calibrate_contact.py`: the canonical player model (aim scatter 0.75 ft per axis, timing N(+19, 48) ms, AMATEUR) through `aim_at_pitch` and `resolve_contact`, printing the whiff/foul/fair split, the foul limbs, quality quantiles overall and by shape, the launch-angle quantiles and mix, spray mean/sd and thirds, contact depth, and the per-pitch on-time table. Flags for handedness, difficulty, n and seed. **It must reproduce today's anchors** (`QUALITY_QUANTILES`, `BATTED_BALL_MIX`, `SPRAY_MEAN_DEG` / `SPRAY_SD_DEG`, 30/31/39) within sampling noise before anything else changes; if it cannot, the instrument is wrong. Paste the baseline into this document.

**Stage 1. The collision module, unwired.** `bat_ball_collision.py` and `tests/test_bat_ball_collision.py`. No caller yet, so the suite stays green and the module is reviewed on its own.

**Stage 2. Pose and wiring, together.** The new pose under the old remap would send every ball 49° toward the opposite field, so these land as one change:
- `bat_path`: bearing rule, `SPINE_DEPTH_FT`, reach bound, clamp removed, pivot retired.
- `bat_contact`: `Contact` carries the exit direction; `spray_deg` and `launch_deg` read it.
- `spray`, `ball_flight`, `hit_outcome_manager`, `hit_animation`, `swing_record`: the retirements above.
- Tests rewritten to the new geometry with provisional constants.

**Stage 3. Calibrate (rule 5).** Run `python -m strikefactor.data.reset_tracking` first. Then, in this order, because each step moves the next:
1. Pose constants, so an on-time swing is fair at every zone location for both hands and the middle pitch leaves at the league mean.
2. The launch mix. Find why the population sits under the squared-up launch angle before adding anything. Candidate levers, most honest first: the vertical datum `aim_at_pitch` centres the bat on; `ATTACK_ANGLE_DEG` (a stated assumption, 10°); `keep`.
3. `FOUL_QUALITY_THRESHOLD`, to restore the whiff/foul/fair split. The direction limb is larger now, so the threshold probably comes down.
4. `contact_audio.EV_CALIBRATION`, then `QUALITY_QUANTILES`, `QUALITY_BY_SHAPE`, `LAUNCH_ANGLE_QUANTILES`, `SPRAY_MEAN_DEG` / `SPRAY_SD_DEG` and `BATTED_BALL_MIX` in `tools/sim.py`, then their mirrors in `tests/test_infield_hit_verdict.py`.
5. `uv run python -m tools.calibrate_defense --n 2500 --by-shape` and the n = 10000 error row. Update the measured table in CLAUDE.md. Do not change a Monte Carlo test's `n`.

**Stage 4. Replay and documentation.**
- The overhead ray needs no code change (it draws `flight_path`), but its docstring and `spray`'s module docstring describe the remap and must be rewritten.
- Depth readouts and the framed depth range accept negative depth.
- Optional: a faint tick for the bat's face normal beside the ray, so the 1.6× relationship is legible; the SIDE view can draw the launch direction for the same reason.
- CLAUDE.md: the swing-and-contact section, the batted-ball module list, rule 5's list of anchors, and the `bat_path` and `pitch_physics` notes.

## Tests

Expected to be deleted or rewritten, by name:

- `tests/test_bat_path.py`: `test_pivots_match_the_hit_outcome_manager`, `test_the_whole_bat_projects_onto_the_hands_to_cursor_line`, `test_the_depth_lead_is_bounded_by_the_geometry_not_by_a_cap`, `test_contact_depth_varies_with_location_the_way_real_contact_does` (new numbers), `test_the_solved_exponent_never_rails` (new range), `test_even_an_absurd_aim_keeps_the_bat_on_a_body` (now the reach bound).
- `tests/test_spray.py`: `test_the_bat_answers_the_aim_wherever_it_can_reach_the_ball`, `test_a_ball_the_hitter_has_to_reach_for_still_lands_fair`, `test_the_flat_spot_starts_where_the_bat_runs_out_of_reach`, and the three population bands.
- `tests/test_bat_contact.py`: `test_early_meets_the_ball_off_the_end_and_late_on_the_handle` (timing now shows first as direction), `test_contact_depth_moves_with_timing`, `test_contact_depth_also_moves_with_location`, `test_quality_peaks_at_dead_on_and_falls_off_both_sides`.
- `tests/test_batted_ball_type.py`, `tests/test_ball_flight.py`, `tests/test_swing_replay.py`: every use of `ball_flight.launch_angle_deg(offset)` and its constants (`test_batted_ball_type.py` is built on `CONTACT_NORMAL_RADIUS_IN`), and anything in the replay tests that assumes positive depth.

New, each for both hands (rule 9) and each on the extreme deterministic case, not a sample (rule 10):

- The on-time bat is within 10° of square on a middle-middle pitch.
- An on-time swing is fair at every strike-zone location.
- The hands stay within the reach bound and on the plate side of the body at every aim, however absurd.
- Collision: a horizontal square bat turns a vertical offset into launch angle and no spray; a barrel-down bat sends an undercut ball toward the opposite field; a bat over the ball never produces a fly ball; a stationary bat reflects the ball near the mirror direction.
- Ball direction turns between 1.3° and 1.9° per ms of residual timing error, measured as a rate.
- `test_the_spray_remap_is_gone`, `test_the_launch_angle_fit_is_gone`, `test_the_pixel_pivot_is_gone`.
- The replay's drawn ray is the bearing the animation flew, and on an on-time middle pitch it lies within 10° of the drawn bat's face normal.

## Acceptance

Measured with `tools/calibrate_contact.py` at AMATEUR under the canonical player model, both hands:

| Quantity | Target |
|---|---|
| Bat bearing, middle-middle, on time | within 10° of square |
| Contact depth, middle-middle, on time | 0.3 to 1.0 ft in front of the plate |
| On-time spray across the zone | fair everywhere, at least 4° inside each line |
| Ball direction per ms of timing error | 1.3° to 1.9°, with no gain constant in the code |
| Whiff / foul / fair | within 3 points of 30 / 31 / 39 |
| Batted-ball mix | within 3 points of MLB's 42 / 24 / 27 / 7 |
| Fair spray thirds | no further from 40 / 35 / 25 than today's 32 / 43 / 25 |
| Difficulty ladder | contact and foul rates monotone ROOKIE to HALL_OF_FAME |
| Home-run rate, LEAGUE harness | 4.0% to 5.0% |
| BABIP and per-shape rates | reported, not tuned; CLAUDE.md table updated |
| Sweep cost | `test_the_sweep_is_cheap_enough_to_run_on_an_input_frame` still passes |

`uv run pytest` and `uv run ruff check .` green.

## Risks and open decisions

1. **The launch mix has no identified lever yet** (finding 4). If the cause turns out to be the swing plane, this collides with the vertical-bat-angle follow-up and stage 3 may need a stopgap constant, stated in inches or degrees and flagged as temporary.
2. **Timing feel changes.** The on-time datum is the ball reaching the barrel's depth, which moves about 1.6 ft closer to the plate: roughly 13 ms later. Recorded swings run about 19 ms late, so this moves on-time toward where players already swing, but it is a change players will feel. Check the batter sprite's contact frame still lines up.
3. **The foul mix shifts toward direction.** That is the realistic source, but the difficulty ladder reaches fouls through `foul_threshold` on the quality limb. Confirm HALL_OF_FAME is still harder than ROOKIE by the same margin once the threshold moves.
4. **`aim_at_pitch` corrects less.** The barrel meets the ball 0.6 ft out, not 2.25 ft, so the depth correction shrinks. Good, but the tests of the translation carry numbers from the old depth.
5. **Outfield calibration moves.** The spray distribution is a BABIP dial (`spray.py` says so). Report the change; fold it into the existing two-variable alignment fit, not into this branch.
6. **Follow-up, named so it is not forgotten:** a tilted swing plane with hands at a realistic height. It is what would give the real 25–30° barrel-down bat and, per finding 6, the grounders-pulled pattern.

## What was built

Everything here is from `tools/calibrate_contact.py` (the canonical player: aim scatter 0.75 ft per axis, timing N(+19, 48) ms, AMATEUR, right-handed, seed 17, n = 13,000) unless it says otherwise.

### Baseline (stage 0, code on `main`)

The harness reproduced the documented anchors before anything changed, which is what says the instrument is right: 30.0 / 32.1 / 37.9 against the documented 30 / 31 / 39, quality quantiles within 0.005 of `QUALITY_QUANTILES`, and the mix, launch quantiles and spray within sampling noise of `tools/sim.py`.

| | `main` | This branch |
|---|---|---|
| Whiff / foul / fair | 30.0 / 32.1 / 37.9 | 30.4 / 30.6 / 39.1 |
| Fouls, share of contact | 45.8% | 43.9% |
| …by direction / by quality / both | 20.2 / 40.6 / 14.9 | 31.9 / 38.0 / 26.0 |
| Fair quality, p10 / p25 / p50 / p75 / p90 / p99 | .649 / .715 / .804 / .882 / .941 / .988 | .755 / .796 / .846 / .927 / .968 / .994 |
| Launch, p05 / p25 / p50 / p75 / p95 | −20.4 / −0.7 / +15.0 / +31.1 / +53.2 | −24.2 / −1.7 / +14.1 / +29.9 / +51.6 |
| Mix, GB / LD / FB / PU | 41.7 / 24.1 / 27.3 / 6.8 | 43.0 / 24.8 / 26.4 / 5.9 |
| Fair spray, mean ± sd | +1.7° ± 21.1 | +1.5° ± 21.5 |
| Fair spray, pull / centre / oppo | 30.8 / 45.1 / 24.1 | 29.6 / 45.3 / 25.1 |
| Bat bearing, middle pitch, on time | 48.9° past square | 2.8° |
| Contact depth, middle pitch | +2.25 ft | +0.52 ft |
| On-time spray across the zone | −34° to +30° | −21.6° to +40.7° |
| Ball direction per ms of timing error | 1.84° (0.77° × the 2.4 gain) | 1.53°, no gain |
| Fair, ROOKIE / AMATEUR / PRO / ALL_STAR / HOF | 57.8 / 37.9 / 12.4 / 7.1 / 4.2 | 54.0 / 39.1 / 8.5 / 5.1 / 3.2 |

A left-handed run mirrors the whole pitch and agrees: 30.2 / 30.7 / 39.1 and 43.4 / 24.3 / 27.4 / 5.0, with the on-time table identical to the last digit. At n = 52,000 (the run the anchors were taken from) the branch reads 30.0 / 30.9 / 39.1 and 42.3 / 24.4 / 27.7 / 5.6.

### Against the acceptance table

| Quantity | Target | Result |
|---|---|---|
| Bat bearing, middle-middle, on time | within 10° of square | 2.8° |
| Contact depth, middle-middle, on time | 0.3 to 1.0 ft out front | 0.52 ft |
| On-time spray across the zone | fair, at least 4° inside each line | fair everywhere; tightest is the high inside corner, 4.3° inside |
| Ball direction per ms of timing error | 1.3° to 1.9°, no gain constant | 1.53° |
| Whiff / foul / fair | within 3 of 30 / 31 / 39 | 30.4 / 30.6 / 39.1 |
| Batted-ball mix | within 3 of 42 / 24 / 27 / 7 | 43.0 / 24.8 / 26.4 / 5.9 |
| Fair spray thirds | no further from 40 / 35 / 25 than `main` | **level, not closer**: 29.6 / 45.3 / 25.1 against 30.8 / 45.1 / 24.1 |
| Difficulty ladder | contact and foul share monotone | monotone; see the note on the hard end below |
| Home-run rate, LEAGUE harness | 4.0% to 5.0% | 4.28% (n = 2500), 4.68% (n = 10,000) |
| BABIP and per-shape rates | reported, not tuned | below |
| Sweep cost | the cost test still passes | passes |
| `pytest`, `ruff` | green | 1486 passed, clean |

`tools.calibrate_defense --n 2500 --seed 808 --by-shape`, LEAGUE:

| | HR% | BABIP | ERR% | GB-hit% | IF-hit% | 2B/1B | GROUNDER | LINER | FLY | POP_UP |
|---|---|---|---|---|---|---|---|---|---|---|
| `main` | 4.08 | .246 | 1.08 | 27.4 | 6.3 | 0.23 | .274 | .482 | .061 | .000 |
| This branch | 4.28 | .247 | 1.34 | 29.4 | 6.8 | 0.19 | .294 | .438 | .051 | .000 |

Across the ladder BABIP runs .342 / .281 / .247 / .209 and ERR% 3.14 / 1.63 / 1.34 / 0.71 (3.61 / 2.14 / 1.59 / 0.69 at n = 10,000). Grounders are hit harder than they were and line drives a little softer, which is where GB-hit% and the LINER rate moved. None of it was tuned; it belongs to the outfield-alignment item.

### Where the implementation departed from the plan

1. **Finding 4 has a cause, and it is two things.** The fair population sat under the squared-up launch angle because (a) a mistimed bat is above its own contact height on both sides of the swing — the barrel's path curves up through contact, from +4° of attack eight milliseconds before the contact pose to +16° eight after — so mistimed contact is topped; and (b) the window of offsets that stay fair is centred on dead centre, and dead centre launches at +8°, the top of the ground-ball band. The lever is the one the plan ranked first: `bat_contact.SWING_UNDERCUT_FT` (0.045 ft, 0.54 in), the vertical datum `aim_at_pitch` centres the bat on. It replaces `ZERO_OFFSET_LAUNCH_DEG`. Not flagged temporary: real hitters do contact the ball slightly under centre, and the tilted-swing-plane follow-up would not remove the need for it.
2. **The launch spread needed squarer contact, which the plan did not anticipate.** The collision turns an inch of bat position into about 30° of launch; the fitted model gave 18°. With the same fair contact the mix read 59 / 16 / 18 / 8. No setting of the undercut and the foul threshold alone reaches both the split and the mix, because a narrow enough window of fair offsets leaves too few fair balls. So **AMATEUR's `aim_assist` went 0.80 → 0.88** and **`FOUL_QUALITY_THRESHOLD` went 0.59 → 0.71** (up, where the plan expected down). The other four difficulty rows were not touched.
3. **`keep` stays at 5/7**, without the check against Cross and Nathan's data the plan asked for; I had no access to it. The reasoning is in `bat_ball_collision.py`. `q` and `keep` were not used as dials.
4. **The load pose was not a constant of the stance** once the hands moved (finding 7 missed this): it was the contact position turned back through the swing, so an inside pitch and an outside one started the swing 1.5 ft apart. `bat_path` now states it (`LOAD_HANDS_IN_FT`, `LOAD_HANDS_BACK_FT`) and each swing solves the path to its own contact pose. `HAND_RADIUS_B` and `HAND_LEAD_DEG` are retired.
5. **The top three `EV_CALIBRATION` rows went 99.5 / 103 / 108 → 101 / 106 / 111**, as well as being re-anchored. A ball lifted into the home-run band has the bat further under it than the fit allowed, so fly balls are struck less hard and home runs fell to 2.8% on the old rows.
6. **The collision treats the bat's rounded ends as spheres** (`end_cap`), which the plan's formula did not cover. A ball off the very end of the bat goes where the end sends it.
7. **`HitAnimation` lost its `vertical_offset` parameter.** The plan offered "pass the launch angle in, or delete the fallback"; `_pick_shape` now takes the launch angle and nothing reads the offset.
8. **A foul's landing is brought on screen along its bearing** (`hit_animation._pull_onto_screen`). 64% of fouls now leave behind the plate, because a ball the bat only tipped carries on back, and the old per-axis clamp put a liner fouled back up to 49° from the ray the replay draws.
9. **Stage 4's optional drawings were not done** (the face-normal tick on the overhead view, the launch direction on the side view).
10. **`reset_tracking` was not run.** It would archive and clear 6,308 recorded pitches and 431 games from the player data directory, and nothing in the calibration needed it.
11. The harness gained `--set MODULE.NAME=X` and `--aim-assist X`, for trying a constant without editing it.

Tried and reverted: centring `Contact.centre_score` on the undercut as well, so that a perfectly aimed swing scores 1.00. It breaks the plan's own "quality and its three scores do not change", and it made fly balls as well struck as line drives: home runs at 7.9% of fair contact against 5.8% on `main` (both measured over the joint population, not the samplers). Quality peaks at dead centre, so a perfectly aimed swing scores about 0.975.

### Open, for a decision

- **The hard end of the ladder got harder** as a side effect of the threshold: fair at PROFESSIONAL 12.4% → 8.5%, ALL_STAR 7.1 → 5.1, HALL_OF_FAME 4.2 → 3.2, and ROOKIE 57.8 → 54.0. `FOUL_THRESHOLD_SPAN` barely moves these (direction carries the verdict up there) and ROOKIE's response to `aim_assist` is saturated. Buying the hard end back means raising its `aim_assist` rows.
- **Spray thirds did not improve.** Half of all contact is on time after the assist, so its direction is the pitch's location alone, and the gain that would spread it fouls the high inside corner. That corner is tight because the bat is barrel-up on a high pitch, which is the low-hands artefact the swing-plane follow-up removes.
- **Timing datum.** On-time is the ball reaching the barrel's depth, which is 14 ms later on a middle pitch than it was. If players keep their habit in absolute terms they run about +5 ms late against the new datum and not +19; the harness then reads 30.5 / 28.9 / 40.6 and 41.7 / 24.7 / 27.2 / 6.4, so the calibration holds either way. Nobody has checked the batter sprite's contact frame by eye.
- Risk 6 stands: a tilted swing plane with hands at a realistic height.

