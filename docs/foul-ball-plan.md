# Foul balls: real flights, a backstop, and foul outs

Status: phases 0-4 implemented, and three of phase 5's four extras — the
catch sound, the net thud and the ball growing with height. Foul tips and
"let it drop" are not started. The plan below is kept as written. Where the
build went differently:

- **Decisions taken.** The backstop is at the bottom edge of the screen
  (`park.BACKSTOP_FT = 45`). With the foul animation off, a live foul is still
  played, out of sight and with the runners on Auto, and only its result is
  shown (`PitchSimulation._resolve_foul_out_of_sight`).
- **Calibration.** `tools/calibrate_fouls.py` is the phase-0 report. The
  dial turned out to be how far the rail pinches in at the poles:
  `park.FOUL_GROUND_AT_POLE_FT = 40` gives 2.3% / 2.5% of fouls caught
  (RHB / LHB, 26,000 swings a hand) against MLB's ~2.5%. Catches split
  3B / 1B / C, weighted to the pull side. Fair-ball fielding is bit-identical:
  `tools.calibrate_defense --by-shape` prints the same table before and after.
- **One fix upstream, in `spray.foul_departure_deg`.** Every pop-up was sent
  behind the plate, including the half the bat had already pointed past a
  line. Those were the catchable fouls (the pop by the dugout), and they all
  came down in the seats behind the net, so foul outs were 0.6%. A pop the
  bat sent foul now flies the bat's own bearing, like every other shape; only
  a pop it merely tipped goes back over the catcher. Which contacts are fair is
  unchanged, so CLAUDE.md rule 5 does not apply.
- **One column, not two.** `foul_result` (schema v16) holds `GROUND`,
  `BACKSTOP`, `STANDS`, `LANDED`, `MUFFED` or `CAUGHT` (`outcomes.FOUL_RESULTS`).
  A caught foul is recorded as the out it was, with `batted_ball_type` set;
  `foul_result = CAUGHT` is what tells it from a fair one.
- **A dropped foul fly** shows the "!" over the fielder and records `MUFFED`,
  but is not added to the box score's error count: box-score errors are still
  counted only from REACHED ON ERROR results.
- **Runners cannot be sent while a foul is in the air.** They hold, and Send
  opens at the catch for the tag-up.
- **A dead foul can be skipped** with any key from contact (the prompt still
  waits for the banner).
- **Sounds are cues, not playback.** `HitAnimation` records `(cue, gain)`
  pairs (`take_sound_cues`) and only the play on screen plays them
  (`PitchSimulation._play_animation_sounds` -> `SoundManager.play_cue`), so a
  foul resolved out of sight, a replay and every calibration sweep are silent.
  A foul catch reuses the glove pop, quieter the further from the plate; fair
  catches are still silent, as before.
- **The net thud is synthesized** by `tools/make_net_thud.py` into
  `assets/sounds/net/thud.mp3` — a low thump with a short rustle, pitched at
  110-220 Hz so laptop speakers can play it. Replace the file with a
  recording to change it.
- **The ball grows only above 15 ft**, a pixel of radius per 30 ft up to 6 px,
  because every fence-drawing guarantee is stated at the 3 px ball. It
  applies to every batted ball and to replays.

## The problem

A foul today is a scripted, cosmetic flight (`HitAnimation._setup_foul` /
`_update_foul`). The count is charged at contact (`PitchSimulation._handle_foul_ball`)
and the animation only decorates it. Three things make it look canned:

1. **Everything behind the plate is squeezed into one strip.** The camera shows
   about 50 px (≈45 ft) below home. `_pull_onto_screen` pulls every landing back
   onto that apron (`FOUL_APRON_MAX_Y_PX = 712`, ≈38 ft), so a liner into the
   screen, a pop-up and a topped chopper all end in the same spot by the catcher.
2. **Depth and time are made up, not flown.** Pop-ups land a random 15-50 ft back
   (`FOUL_POP_BACK_FT`) over a fixed 2.7 s (`FOUL_FLIGHT_MS`), then sit for a
   fixed 700 ms (`FOUL_HOLD_MS`). The exit velocity and launch angle the contact
   already produced are ignored (only the "foul home run" branch uses them).
3. **Nobody can catch it.** The drift fielder is sent to a point 25 px short of the
   ball on purpose ("sells lets it drop foul"), and the catcher's range is
   `ROLE_MAX_INTERCEPT_DIST_FT["C"] = 17` ft, the crouched-catcher limit for balls
   in play. On a pop straight back the ball goes up the screen toward the mound
   and drops behind a catcher who never moves.

### What fouls actually are in this game

12,000 swings by the model player (`tools.calibrate_contact`, amateur, RHB), 3,688 fouls:

| Shape    | Share of fouls | Where it goes                                     |
|----------|---------------:|---------------------------------------------------|
| GROUNDER | 73.0%          | 43.1% straight back (≥135°), 26.5% wide, 3.4% between |
| POP_UP   | 13.5%          | all behind the plate (120°-165° by `FOUL_POP_BACK_DEG`) |
| FLY      | 9.1%           | mostly wide, down the lines                       |
| LINER    | 4.4%           | mostly wide                                       |

**The most common foul by far is a topped or glanced ball going straight back**,
so that is the one most worth getting right.

If every airborne foul flew its real carry (`ball_flight.carry_distance_ft`) along
its real bearing (`spray.foul_departure_deg`), with foul ground 45 ft deep behind
the plate and 45 ft wide beside the lines:

| Destination                        | Share of all fouls |
|------------------------------------|-------------------:|
| grounder (dead where it lands)     | 73.0%              |
| into the stands                    | 20.7%              |
| into the backstop net              | 3.4%               |
| comes down in playable foul ground | 2.9%               |

MLB had about 1.4 foul outs per game in 2019 against about 54 foul balls per game,
so roughly **2.5% of fouls are caught**, about 1.8% of plate appearances. The real
flights land in playable ground at a rate in that range, so foul outs can come out
of the physics without a probability table.

## Goals

- Every foul flies its own flight, from the exit velocity, launch angle and bearing
  the contact already produced. The same contact always draws the same foul (rule 2).
- Balls fouled straight back go into the backstop, which sits at the bottom edge of
  the screen. They leave the frame at their real speed.
- Airborne fouls that come down in playable foul ground are live. A fielder who gets
  there catches them for an out, and runners can tag up and advance at their own risk.
- Fouls that land untouched, or go into the net or the stands, are dead balls and a
  strike, as now.

## Design

### Foul ground is part of the park (`park.py`)

The wall is a real-feet ellipse in `park.py`; foul ground goes there too.

- `BACKSTOP_FT ≈ 45`: the bottom edge of the screen is at 45.5 ft behind home
  (`HOME` y = 670, 1.10 px/ft, 720 px tall). Real backstops are 45-60 ft back, so
  putting the net at the screen edge keeps every catchable foul on screen and
  makes "leaves the bottom of the screen" mean "into the net".
- `FOUL_GROUND_WIDTH_FT`: how far the stands rail sits from each foul line. Defined
  as distance from fair territory, so one number gives a rail parallel to each
  line and a 45 ft arc behind home that meets the backstop. It may taper toward
  the poles.
- `foul_ground_verdict(x_ft, y_ft)` → `PLAYABLE` / `BACKSTOP` / `STANDS`, and a
  helper for where a flight crosses the boundary. This is the single answer the
  animation, the fielders and the catch gate all read (rules 1 and 3).
- `fielding_renderer.draw_field` draws the rail as a faint line, so the player can
  see where a ball becomes uncatchable. The backstop is the screen edge.

### Every foul flies, and ends where its flight ends (`hit_animation.py`)

Replace `FOUL_LANDING_FT`, `FOUL_POP_BACK_FT`, `FOUL_FLIGHT_MS` and
`_pull_onto_screen` with the real flight, as the foul home run already does:
carry from `ball_flight.carry_distance_ft(launch, ev)`, hang time from
`ball_flight.hang_time_s`, and the path from `_configure_flight_path`. Then end each
foul by where its flight goes:

- **Into the backstop.** The ball keeps going and leaves the bottom of the screen.
  A liner gets there in about half a second. Mark the exit point with a short
  net-ripple mark and cut the dead-ball hold to about 400 ms. The catcher flinches
  and turns.
- **Into the stands.** The ball crosses the rail and disappears when it lands, as a
  home run does behind the wall. The nearest fielder runs to the rail and pulls up.
- **Topped or glanced grounders back (43% of all fouls).** The ball hits the dirt
  within a few feet of the plate and kicks back: a high hop off the plate into the
  net, a skip off the catcher's gear (he picks it up), or a hard skip under the
  screen. Choose the variant from the ball's own launch angle, exit velocity and
  bearing, not from a new random draw.
- **Wide grounders.** Roll up the line in foul ground at real speed. The corner
  infielder lets it go or picks it up.
- **Fielders react to every foul.** The catcher comes out of the crouch on anything
  in the air behind him, and corner infielders break on pops near their line. Remove
  the "stop 25 px short" drift.

This part changes only what a foul looks like. The count, the stats and the
whiff/foul/fair split are unchanged.

### Catchable fouls are live (`pitch_simulation.py`, `hit_animation.py`)

**Which fouls are live:** airborne fouls (POP_UP, FLY, LINER) whose landing point
is `PLAYABLE`. Grounders and balls into the net or stands stay dead, and their
strike is charged at contact as today.

**At contact.** `_handle_foul_ball` still records the pitch (`strikes`,
`pitchnumber`), but for a live foul it **defers the count**: `currentstrikes`, the
FOUL display and `new_entry['foul']` wait for the result. It then starts a live-foul
animation whose `on_complete` is a new `_finalize_live_foul`.

**In the animation.** A new `_setup_live_foul` reuses the airborne machinery fair
balls already use: `_assign_in_play_targets`, `_check_in_flight_intercept`,
`_roll_misplay`, `_trigger_in_flight_intercept`, `_claim_retouches` and
`_begin_return_play`. Only foul-ground fielders are eligible: C, 1B and 3B,
LF and RF on deep flies down the lines, and the middle infielders rarely.

- **Catcher range on pop-ups.** The 17 ft cap is right for a crouched catcher on a
  ball in play, not for a pop with 4-5 s of hang time (our foul pops hang 4.3-5.0 s
  at p10-p90). For airborne fouls, give the catcher a real range (around 90 ft,
  limited by sprint speed) and a mask-off reaction of about 0.6 s instead of 0.32 s.
- **The rail and the net are walls for fielders.** Contain them the way
  `_contain_fielders` handles the outfield wall, and allow no catches past the rail.

**Three endings:**

1. **Caught.** `classified_outcome` is the existing word (`POP UP`, `FLYOUT` or
   `LINEOUT` from `_caught_outcome`) plus a `caught_in_foul_ground` flag. Don't add
   an outcome string (rule 7); every group and stat that already handles a pop out
   keeps working. The batter is out. Runners must retouch, and with fewer than two
   outs they can tag and advance at their own risk through the existing
   send/retreat controls (manual mode) or the coach logic (auto mode). A runner
   scoring on a caught foul fly is a sacrifice fly, which `helpers` already credits
   for `FLYOUT` with a run scored. `_finalize_live_foul` routes this through the
   same bookkeeping as `_finalize_batted_ball`: outs, count reset, at-bat or
   sacrifice fly, GameDay record and walk-off check. A walk-off sacrifice fly on a
   foul pop is possible.
2. **Drops untouched.** Dead ball. `classified_outcome = "FOUL"`, runners return to
   their bases, and the deferred strike is applied (only when below two strikes).
3. **Dropped (muff).** Dead ball and a strike, plus an error charged to the fielder,
   which is the MLB scoring for a muffed foul fly that extends the at-bat.

**Display.** Show "FOUL OUT" on the banner, adding "SAC FLY" when it was one. Do
this at the display seam (`_format_display_outcome` / `outcomes.play_display_name`),
not in the recorded value. The scorebug must not show the strike while the ball is
in the air.

### Records, replay and settings

- **DB (rule 8).** Add nullable columns rather than widening existing ones, and
  bump `SCHEMA_VERSION` from 15 to 16 with a migration in `PitchDB._migrate`:
  - `foul_destination` on foul pitches: `GROUND` / `BACKSTOP` / `STANDS` /
    `PLAYABLE`.
  - `caught_in_foul_ground` on batted-ball outs.
- **AI reward.** No change needed. A caught foul records as `POP UP`/`FLYOUT`
  (worth 1.5 to the pitcher), and a dropped one stays `'foul'` (0.3).
- **Swing replay.** Label a caught foul "FOUL OUT" instead of "FOUL"
  (`swing_replay_overlay`, where it reads `made_contact == "fouled"`).
- **Fielding replay / review.** A live foul is recorded by `FieldingRecorder` like
  any other play, so it is covered automatically.
- **`foul_animation_enabled` toggle.** Dead fouls can still be skipped. A live
  foul's result comes out of the simulation, so with the toggle off, run it
  headless (the update loop without drawing, as the tests do) and show only the
  result.

## Phases

Each phase can ship on its own. Phases 1-2 change only the picture and are low
risk. Phase 3 is the rules change.

| # | What | Size | Main files |
|---|------|------|------------|
| 0 | Foul calibration report: shape × destination, caught share, foul outs per PA | S | `tools/calibrate_contact.py` (or a new `tools/calibrate_fouls.py`) |
| 1 | Foul ground in the park, and the rail drawn on the field | S | `park.py`, `ui/fielding_renderer.py` |
| 2 | Real flights for every foul; backstop exits, stands, grounder caroms, fielder reactions | M | `hit_animation.py` (`_setup_foul`, `_update_foul`), `tests/test_foul_animation.py` |
| 3 | Live fouls: deferred count, catches, tag-ups, muffs, banner | L | `pitch_simulation.py`, `hit_animation.py`, `outcomes.py` (display only) |
| 4 | DB columns, swing-replay label, toggle behaviour | S | `data/pitch_database.py`, `ui/swing_replay_overlay.py`, `gameplay/review_record.py` |
| 5 | Optional polish (below) | — | — |

### Phase 5: optional, each its own change

- **Ball grows slightly with height.** Sells a ball coming back toward the camera,
  but it affects every batted ball, so ship it separately.
- **Sounds.** A net thud for backstop fouls (new asset; the package-data already
  ships `.mp3`), and the existing `mitt/*.mp3` pop on a foul-out catch.
- **Foul tips.** A barely-nicked ball that carries on into the catcher's mitt is a
  strike and a live ball, and strike three with two strikes. This moves the
  strikeout rate, so measure it with the harness first.
- **"Let it drop."** Late in a close game, with a runner on third and fewer than two
  outs, a fielder lets a deep foul fly drop rather than give up the winning
  sacrifice fly.

## Calibration and tests

**Targets**

- Caught share of all fouls ≈ 2.5%, foul outs ≈ 1.5-2% of plate appearances.
- The levers are the size of foul ground, the catcher's pop-up range and reaction,
  and, if pops behind the plate catch too rarely, the pop deflection band
  `spray.FOUL_POP_BACK_DEG`. That band only moves where a foul goes, not which
  contacts are fair or how quality is distributed, so rule 5's re-derivation does
  not apply.
- Don't add a second flight model for foul pops. If they carry too far back, change
  the deflection, not the physics (rule 2).

**Must not move**

- The whiff/foul/fair split.
- Every fair-ball rate in `tools.calibrate_defense --by-shape` (rule 6): fouls
  never touch a fair ball's fielding.

**Tests to update.** `tests/test_foul_animation.py` currently pins "a foul is
cosmetic and never becomes a live ball". Split that in two:

- Dead fouls stay cosmetic.
- A live foul resolves only to `FOUL` or a caught out, never a hit or a
  reached-on-error.

**New tests**

- Deterministic: the same contact draws the same foul twice.
- A ball over the backstop leaves through the bottom edge of the screen.
- A ball into the stands is never caught.
- A caught foul with a runner on third and fewer than two outs: the runner can tag
  and score, and it is credited as a sacrifice fly.
- The same caught foul with two outs ends the inning with no run.
- A dropped foul with two strikes leaves the count at two strikes.
- Each directional case runs for both batting hands (rule 9).

## Decisions needed

1. **Backstop distance.** At the screen edge, about 45 ft (recommended: everything
   catchable stays on screen), or an MLB-typical 55-60 ft, where some catches would
   happen just off-screen.
2. **Foul-animation toggle off.** Resolve live fouls instantly in the background
   (recommended), or always show live fouls.
3. **Foul tips as strike three** (phase 5): yes or no.
