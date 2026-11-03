# Ball and fielding replay — proposed implementation

Status: implemented, then superseded by the unified review workspace — see
[unified-review.md](unified-review.md), which is authoritative. This document is
kept for the capture model (`FieldingRecorder`, the frame budget, the event
markers), all of which is live. Its **presentation** half is not: step 3's
`ui/fielding_replay_overlay.py` was deleted once `ReviewOverlay` + `FieldingView`
owned the transport, and step 4's dedicated modal loop is now `request_review`.

Implementation notes:

- Fielding Replay defaults to **F**, is remappable, and is available as an on-screen action between pitches and on the completed-play screen.
- `FieldingRecorder` copies immutable presentation frames after live updates. `HitAnimation.draw` and the replay share `ui/fielding_renderer.py`.
- Event markers use the first observed source frame for exact seeking. Motion holds across event boundaries instead of interpolating through collisions. The record retains the fixed field projection's source surface dimensions.
- Capture is limited to 7,200 frames (120 seconds at 60 FPS, 60 seconds at 120 FPS). Overflow withholds the clip. A local headless measurement used approximately 16.5 MiB at the limit, about 7 microseconds per presentation snapshot, and 1.4 ms per replay render at 1280×720; these are development measurements, not hardware-independent guarantees.
- The clip ends at simulation completion. Home-run distance also appears in replay metadata because the live distance annotation can fade in after completion.
- The batter and existing runners are recorded around the whole diamond, including rounding, holding, returning, sliding, scoring and retirement. Base contacts, return throws, relay exchanges and tags have exact event frames. Runner interpolation continues across ball possession events.
- Saved clips, audio, and additional cameras remain outside this version.

First-base resolution now uses `infield_timing.schedule_first_base` and
`timed_verdict`: the batter is out only when a defender has possession at
the actual bag before the runner's foot contacts it. Exact ties are safe.
Coverage delays, bobbles and unassisted carry motion are included before the
call; the clean schedule for error scoring reuses the same runner and inputs
with the misplay removed. The former probabilistic first-base verdict remains
available to analysis callers, but is no longer used for the visible race.
`runner_motion` supplies the batter's fitted arrival and defenders' analytic
approaches in real feet and seconds. Presentation pacing scales the whole
race together.

Live fielding now runs at real-time pacing (`PRESENTATION_TIME_SCALE = 1.0`),
so a fitted 4.3-second run takes 4.3 seconds on screen. A groundout outside
the existing 0.15-second close-play band allows key/click continuation once
possession at the bag has actually occurred. Skipping records the current
terminal pose and finalizes the result once; it does not fast-forward or
invent the runner reaching first. Close plays retain both arrivals. Fouls
keep the blue batter marker stationary in the handedness-appropriate box
and existing runners visible on their starting bases, including in replay.

Extra-base play uses `CircuitRun` in `runner_motion`: committed route segments
remain unchanged, and each decision replaces only the unplayed tail. Coaches
forecast retrieval, coverage and a return throw before sending a runner; a
hold may be reconsidered while the ball is loose. A released throw keeps its
destination. Cover goes to the available receiver who can reach the bag
first. Long returns use a cutoff only when that fielder can meet a timely
throw; otherwise the return is direct, without waiting for a midpoint to
be staffed. Every receiver must physically arrive before reception. Beyond first,
possession alone is insufficient: a glove sweep must reach the approaching
runner before foot contact. There is no independent safe/out roll or automatic
double for a wall ball. A runner may retreat to an unoccupied safe base after
a throw commits. Full rundown chains and throwing errors are not modelled.

Return targets follow active, contestable runners. The defense does not send
the ball home just because a preceding runner is holding third or has already
scored; when a lead runner cannot be caught, it protects the batter's next
base. Each leg commits at its own release. A cutoff which receives the ball
after the home-plate threat disappears can redirect the unthrown relay while
preserving the OF throw. Runner forecasts account for that possibility and
never add a fictitious second transfer when the ball is already going to
their proposed destination.

With fewer than two outs, clean catches offer each existing runner one tag-up
advance, starting after a short reaction at the catch. The decision reads the
actual catch position and current defenders before the return is committed. It does not treat a
future relay destination as current possession, or permit the runner to
round another base while that return is in flight. Dropped balls remain live
and retain ordinary multi-base decisions and error scoring.

With two outs, runners break on fair contact for every ball shape and keep
rounding while the ball is airborne. Once it lands, ordinary defensive races
govern further advances; drops preserve the head start. A catch ends the inning
at its actual time, freezes runner positions and permits immediate continuation
without scheduling a return throw. Earlier physical base/home contacts remain
in replay, but no run counts on the caught batter's third out. Fouls keep runners
on their starting bases regardless of the out count.

`RunningResult` separates the credited hit, actual final occupancy, per-runner
contacts and running outs. A double followed by a tag at third remains a
double and adds an out. `ScoreKeeper.update_running_play` applies those
movements rather than advancing everyone by the credited hit length. Runs
before a tag third out count; a force or caught-batter third out cancels all runs.
Pitcher responsibility and error reconstruction remain attached to the original
runners. GameDay logs and pitcher innings include running outs. Schema v13
adds nullable running-result JSON, running-out count, batter final base and
tag margin; historical rows remain unknown.

A successful extra base conceded by a throw to a preceding runner is stored
in `RunnerMovement.on_throw_bases` and does not increase hit credit. The
ordinary defense to each base is frozen at pickup for this scoring judgment,
without another RNG draw. For example, a batter can finish on second after a
single: the banner and GameDay annotation say `SINGLE · TO 2B ON THROW`, hit
statistics count one base, and the scorer preserves actual second-base
occupancy and earned-run position. The existing result JSON includes these
contacts; older GameDay events default to no on-throw annotation.

Clear settled extra-base plays permit continuation after the return and all
surviving runners settle, or immediately after a third out. Home-run banners
appear as the ball clears the yard, with immediate key/click continuation;
watching the rest of the circuit is optional. Banner delivery and terminal
clip publication have separate once-only guards. Opening review also settles
the optional tour and publishes its observed clip before opening. Replay
ends at the observed pose if skipped, without inventing later contacts.

The original design follows.

## Player experience

Add a **Fielding Replay** action that reviews the most recent completed ball-in-play animation, from bat contact through the end of the play. Include hits, outs, home runs, errors, and animated fouls. Start with the current full-field view and visual style.

- Open with a remappable shortcut and an on-screen replay action. Choose the default key after checking gameplay-specific bindings, not just KeyBindingManager.
- Play automatically at 0.5× the original animation speed. Offer 0.25×, 0.5×, and 1×; these are playback rates, not a claim that the original animation uses real-time physics.
- Space pauses/resumes, Left/Right scrub, and a visible Restart button returns to contact. At the end, Space restarts, matching swing replay.
- A clickable timeline marks available events: contact, bounce, wall impact, misplay, ball secured, throw release, and throw arrival. Selecting a marker pauses there.
- Hold the final frame until dismissed. Escape returns to the exact game state from which the replay opened.
- Show the original result, exit velocity, launch angle, and involved fielder when available. Do not synthesize missing values.
- Preserve the latest completed clip until another completed clip replaces it or the game session resets. Identify its play/pitch so a subsequent take or whiff cannot make it look like a replay of the current pitch.
- If there is no recorded animation, show “NO FIELDING PLAY TO REVIEW.” Do not reconstruct a play when animations were disabled.

Initially permit opening between pitches and from the completed play's continue screen. Opening during a live pitch/play is outside the first version. The replay shortcut must take priority over “press any key to continue.”

## Why record the original play

`HitAnimation` integrates ball and fielder movement incrementally. It draws random reaction times, movement attributes, runner speeds, and misplays, including draws made during the play. Its completion callback also finalizes gameplay outcomes. Constructing a new animation for replay could change the result or apply game effects again.

Record presentation state during the original simulation. Replay reads immutable data and never calls `HitAnimation.update`, outcome callbacks, random generators, or game-stat persistence. A seeded rerun is insufficient because timestep changes and random-call ordering also affect behavior.

## Data and rendering

Introduce `gameplay/fielding_record.py` with an immutable `FieldingRecord`, timestamped frames, and timestamped events. A short-lived recorder collects data during live playback and freezes the record when the play completes.

Record:

- Clip metadata: play identity, original result and metrics, field geometry/projection context, dimensions, and the original presentation time scale.
- Each frame: elapsed animation time, ball and shadow positions, ball visibility/occlusion, all nine fielder draw positions, and the visual state needed for gloves, errors, and home-run annotations.
- Events: event type, time, involved role, and position where relevant. Capture timestamps from the simulation's existing transition times when available; otherwise use the frame where the transition occurred.
- The initial and terminal frames explicitly. Stop collecting at simulation completion, before the player's unbounded wait on the continue screen.

Use the existing field coordinate system for the first version and retain its projection context so resizing does not change recorded geometry. Do not attempt a world-coordinate migration as part of replay.

Extract a shared, read-only field renderer from `HitAnimation.draw`. Both live playback and replay supply a presentation frame to this renderer. Include idle sway and transient annotation state in that frame; drawing must not depend on the wall clock or current difficulty settings. Keep the live continue prompt and replay controls in their respective owners.

Capture after each original update, after field containment and phase overrides. Interpolate continuous positions for smooth slow motion; keep discrete state changes at their recorded timestamps. Split interpolation at event boundaries to avoid blending a ball through a glove, wall collision, or change of possession. Preserve the original samples even when a slow source frame limits interpolation accuracy.

Keep only one completed clip plus any current recording in memory. Measure frame sizes and long-play memory use before setting a sample budget. If a recording exceeds that budget, mark it incomplete and withhold it rather than presenting a silently truncated clip as the complete play. No video capture or disk persistence in version one.

## Integration sequence

1. **Extract the presentation frame and renderer.** Preserve current live visuals, including wall occlusion, glove positioning, errors, and distance labels. Validate this separately before adding replay controls.
2. **Capture a complete play.** Attach the recorder at the hit and foul animation creation paths in `PitchSimulation`. Capture the initial frame and post-update frames; freeze the record at completion after the final classification is available. Store it as `Game.last_fielding_play`. Publish once, independently of repeated banner frames.
3. **Build `ui/fielding_replay_overlay.py`.** Implement a local playback clock, pure frame sampling, speed controls, pause/scrub/restart, event navigation, and a final-frame hold. Reuse the shared field renderer.
4. **Wire access and lifecycle.** Add `KeyAction.FIELDING_REPLAY`, its settings label and controls, and a modal replay loop following swing replay. Ensure Escape and window-close work, existing HUD controls stay behind the panel, and the continue screen consumes replay input correctly. Refresh relevant clocks on return so time spent reviewing cannot advance gameplay.
5. **Verify representative plays and performance.** Review real captures and run the regression checks below before considering optional cameras or diagnostics.

## Acceptance checks

- At recorded timestamps, replay reproduces the original ball, shadow, defenders, occlusion, and annotations. Shared-renderer image checks cover representative frames.
- Replaying or seeking a clip repeatedly gives identical frames and the same original result, even after settings changes.
- Scrubbing backward and forward across a catch, wall impact, error, and throw never leaves stale possession or visual state.
- Replay leaves scores, outs, bases, pitch count, database writes, gameplay callbacks, and global random state unchanged.
- Recording itself leaves the live outcome and random state unchanged when comparing runs with identical inputs and timesteps.
- Cover flyouts, groundouts with throws, unassisted outs, infield hits, extra-base hits, wall rebounds, home runs, errors, and animated fouls, plus empty and incomplete recordings.
- Pause, speed changes, timeline endpoints, resize, restart, Escape, window-close, and reopening from the continue screen behave consistently.
- Measure capture overhead and memory on long plays; replay should stay responsive at the existing 60 FPS target.

## Follow-up scope

A ball-following camera, zoom around close plays and optional fielder routes can follow. Audio replay and saved/shareable clips are also deferred.
