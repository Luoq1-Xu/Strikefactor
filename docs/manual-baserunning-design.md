# Auto and manual baserunning design

Auto controls all running algorithmically. Manual gives runners at most one automatic advance and requires an explicit Send for each further base. Send and Retreat remain available throughout running, with another 2.5 seconds to decide after runners and possession settle. The field identifies the controlled runner and shows the current destination, any queued destination, and the exact destination each available button will choose.

## Modes and destinations

Persist `baserunning_mode` as `auto` or `manual`, defaulting to Auto. Snapshot it when the ball is put in play. It is independent of batting difficulty, defense strength, and Arcade, GameDay, or Sandbox.

In Manual, the batter runs to first. Existing runners take their normal required or safely justified first advance. They stop after that advance, including with two outs, until the player sends them farther. A held runner can also be sent on their first optional advance when the ordinary policy would hold. Legal tag-ups, forces, occupied bases, and the inning ending still govern every movement. Fouls have no manual controls. Home runs use the normal airborne-ball controls and running until the ball clears the fence; confirmation closes controls, cancels pending commands, and sends every runner home from their current position.

On ground balls, a batter finishing the first-base leg always runs through
the bag, whether safe or out and regardless of the margin. Continue and play
completion wait for that sprint, including after an inning-ending out. An
out still retires the batter at its original timestamp; the continued run
awards no legal contacts or advances after the out. Live and recorded frames
show the same motion. A later Send starts from the runner's actual position
and momentum beyond first, and the settled decision window starts after the
run-through. An intentional advance toward second keeps its running route.

Sandbox has unlimited outs: its cumulative out total never enables two-out contact running or ends a running play. Uncommanded runners wait on airborne balls; Manual can send them early. Runners must tag up on catches and can continue after any batter or running out. Outs still count in session statistics.

The most advanced live runner is highlighted by default, preserving baseball order through their starting base and stable play ID. **Tab**, remappable as Select Next Runner, cycles through controllable runners and retains that selection until the runner is no longer controllable. A premature home touch remains controllable while a catch is possible or a retouch is owed. Pending commands belong to their original runner and are cancelled rather than transferred when selection changes.

## Send and Retreat

**G**, remappable as Send Selected Runner, queues exactly the displayed next base. From a batter going to first, it queues second. Once the second-base leg begins, another G can queue third. A pending command has a fixed destination and cannot be consumed at some different future stopping point. One pending advance is allowed at a time; held keys and key repeat never create additional commands.

Execute the queued leg at the existing rounding decision near the current bag, or immediately from a held bag when legal. Use the runner's actual position and momentum. An unresolved first-base force remains authoritative; an early request for second waits for the force to resolve. Sending a runner onward cannot cancel an intermediate tag.

**D**, remappable as Retreat Selected Runner, cancels any queued advance and returns a moving runner toward their last touched base. It cannot return the batter home before first or send a runner into an occupied or reserved base. An initial forced runner must complete that force unless the force has been removed, such as by retiring the batter. A runner already holding a bag can also return to correct an airborne departure, as described below.

If retreating is illegal but an extra advance is queued, D cancels the queue and holds at the current destination. The prompt explicitly says HOLD AT in this case. For example, D can cancel a batter's queued second-base attempt while preserving the required run to first.

When every runner and the ball have settled, D also confirms HOLD AT the current bag and closes the decision window immediately. The key is still consumed, so confirming Hold does not accidentally start the next pitch.

G during a retreat turns the runner back toward the displayed next bag. `CircuitRun.return_to` and `resume_to` replace only the unplayed route tail. Past positions, base contacts, and released throws remain intact. Changes of direction have real acceleration costs. In Manual, retreat decisions belong to the player; the automatic escape behavior remains in Auto.

## Airborne departures and retouch appeals

In Manual, Send opens after the normal contact reaction, including on liners, flies and popups while the ball is airborne. Runners do not know the eventual outcome. An early departure uses the ordinary initial advance allowance; landing, returning, or completing a retouch never grants another automatic advance. A fresh Send can start another attempt. Auto retains its existing airborne policy.

If a fair ball lands or is dropped, retain the actual head start and enforce any resulting force obligations. If it is caught, runners who were off their original bag at the first fielder touch owe a retouch. First touch and catch confirmation are distinct facts even though today's clean catches produce them at the same instant.

A catch never automatically returns a Manual runner. Committed motion and explicit forward commands remain risks the player chose. Show a persistent orange **NEEDS TAG AT 1B** warning, mark each owed bag, and keep the offending runner selectable even after a premature home touch. G can continue or interrupt a return without forgiving the obligation. D starts the correction from the actual position, including from a held advanced bag, through all passed intermediate bases in reverse order. The heading shows those intermediate bags while returning. Before a catch, D can also start a precautionary return. A following runner scoring closes the opportunity to correct under Rule 5.09(c)(2).

The defense chooses retouch appeals alongside ordinary tags and forces. A held advanced bag or a home touch does not remove an appeal target. The out requires possession and actual contact with the original bag, or the applicable physical runner tag. The ball holder can carry to the bag for an unassisted appeal. A retouch tying the reception is safe. Refresh an appeal race when a command changes the planned correction; released throws remain unchanged.

Retouch appeals are time plays, with the additional runner-order consequences of Rule 5.09(d). A third-out appeal on a preceding runner annuls following runs. Runner motion freezes at the apparent third out, but a useful subsequent appeal may still remove a surviving run. Such an advantageous appeal is recorded with `official=false` and never adds a fourth official inning out. A two-out catch still annuls all runs immediately. Sandbox has no inning-ending third out.

Physical touches remain in history. A withdrawn early home touch earns no run; a corrected return followed by another home touch uses the later scoring time. Appeals must resolve before Continue, scorekeeping and replay publication. Replay retains both the frozen runner poses and any later physical appeal sequence.

These rules cover the existing fair-ball simulation. Live caught-foul plays and infield-fly declarations remain separate integrations. Rule references: [2026 Official Baseball Rules](https://mktg.mlbstatic.com/mlb/official-information/2026-official-baseball-rules.pdf), catch definition and Rules 5.06(b)(1), 5.08, 5.09(c)–(d).

## Control feedback and time

Show a ring around the controlled runner and two short lines above the field:

- Current movement, such as TO 2B, AT 2B, or RETURNING TO 1B.
- Available commands, such as G SEND TO 3B and D RETURN TO 1B.

A queued advance adds THEN 3B to the current movement line. Show HOLD AT for cancellation of a queued advance. Hide unavailable actions. Use the actual remapped key names, and keep the overlay in recorded frames so Fielding Review shows the same intent as live play.

Open controls at the runner's legal departure opportunity, even when the runner is holding. Keep them open while any runner or the ball is still moving. After every active route and throw settles, start a 2.5-second decision timer. A new Send or Retreat makes the play live again and the next settlement provides another decision window. Show the countdown only during this settled window. No extra physics integration step is introduced solely for the UI timer.

Process command timestamps before advancing the host frame and before Continue handling. Reject a command at or after window closure. Both command keys are consumed even when unavailable, including on completed plays, so a late command cannot accidentally continue to the next pitch. Keyup releases each command's independent latch; precontact presses are not buffered into the play.

Finish and publish scorekeeping and replay only after movement, defensive follow-up, and the final decision window settle. Inning-ending outs cancel controls immediately.

## Defense and possession

Use the same defensive model in both modes. React to visible movement changes, including MANUAL ADVANCE and MANUAL RETURN, after the defense profile's reaction delay. Hidden pending input alone does not trigger a response.

Keep retrieval and ball backup assignments, while free defenders prepare the threatened bag and useful backup. Use actual positions and exclusive assignments. Direct and cutoff previews use the same release, flight, cover, and exchange timing as execution.

Choose useful plays against live runners, charging for other advances conceded behind a throw. Include a runner retreating toward a previously touched base, including first. A return to a previously touched bag requires actual physical contact to be safe; the old touch cannot immunize a runner against a tag while they are off the bag.

An unreleased throw may redirect with a setup cost and hysteresis. A released throw preserves its origin, destination, and timing. After cutoff or base reception, the holder may throw at another threat, including the return base. Track retirement times per runner and preserve the completed glove-contact frame before a follow-up transfer. Every out still requires the physical reception and tag; planning estimates do not adjudicate outcomes.

Retreat does not guarantee safety. An early retreat can beat a return throw; a late retreat can be tagged at its destination. After repeated direction changes, a receiver holding the ball pursues the runner instead of restarting a base-to-base throw exchange. The carrier retains velocity, accelerates and brakes through turns, and slows near the runner; another defender guards the escape bag. A tag requires possession and actual glove reach after the tag sweep, with continuous contact checks between simulation poses. A runner can escape by reaching a safe bag. Rapid commands cannot keep postponing an already pending defensive reaction. Throwing errors remain outside this feature.

`HitAnimation.update()` advances the entire elapsed interval in steps of at most 16 ms, splitting earlier at scheduled race events and physical rundown tags. A host-frame stutter cannot jump an entire ordinary catch window. These bounded steps do not promise bit-for-bit results across different frame schedules; strict determinism would require fixed simulation ticks. Replay retains event and collision poses without recording every internal physics step.

## Implementation and records

`baserunning_control.py` owns the selected runner, explicit pending base, command history, opening, and settlement deadline in contact-relative seconds. `HitAnimation` applies legality and occupancy, controls routes, and keeps first-base timing authoritative. `runner_motion.py` owns continuous forward, return, resume motion and base-contact intervals. `rundown.py` owns continuous carrier pursuit, direction-change detection, base protection, and physical tag contact without pygame or random draws. `tag_up.py` reads retouch obligations from those routes and the first-touch time. `return_play.py` previews physical throws and evaluates defensive choices without pygame or random draws. `RunningResult.counts_run` centralizes appeal scoring for both defensive choices and the scorekeeper.

`PitchSimulation` snapshots mode and bound key names, handles Send and Retreat before Continue, and persists the control snapshot with the final `RunningResult`. Settings and key-binding panels scroll rather than shrinking rows. Adding a default command must preserve existing custom keys and reserve the swing and fullscreen keys.

Hit credit, final occupancy, and running outs remain distinct. A single followed by a tag at second or on a retreat to first remains a single plus a running out. Successful advances conceded by another throw retain their existing scoring treatment. Third-out timing and earned-run reconstruction use actual movements and retirement times.

Ground balls with a runner on first can produce a force at second and a relay
to first. `force_play.py` shares live force obligations between Auto, Manual,
and defensive races. A retired following runner removes the force on runners
ahead; touching the required bag discharges it. Forced runners cannot retreat
to escape a feed. On an uncaught liner or a dropped fly, the occupied chain
must advance after landing or the drop, even when the throw will win. A
provisional hold, risk estimate, or Manual's optional-base limit cannot veto
that required movement. Auto and Manual share the same return-base legality.
The free middle infielder prepares second during fielding.
`infield_play.py` compares the direct first-base play against a turn using the
same sampled pickup transfer and the forecast positions of covering defenders.
Each reception resolves its own out before a subsequent throw is chosen.
Beating the relay is a fielder's choice; no hit or error is inferred from the
batter reaching first. A ground double play earns no RBI, and an inning-ending
force cancels all runs on the play. Sandbox counts both outs without ending
the running play. A choice preserves the replaced runner's pitcher responsibility.

Database schema 14 has the nullable `baserunning_mode` column. Running-play JSON schema 5 retains the command ledger, retirements and fielding sequence from schema 4 and adds first-touch time, retouch records, the appeal out kind and official-out flags. Double-play labels derive from the actual official putouts; they do not replace the batter's canonical outcome. Historical rows remain unknown; no old record is rewritten. First-base and tag margins retain their existing meanings and remain null when that race was not played. Presentation frames include current destination, command hints, selection hints and retouch warnings, while the renderer continues to accept the earlier five-field Send overlay.

## Acceptance scenarios

| Scenario | Required behavior |
| --- | --- |
| Manual with no input | No runner touches more than one new base, across all profiles, shapes, hands, and out counts |
| One Send on an otherwise safe deep hit | Explicitly attempt second and stop there |
| A second Send | Queue third with the destination visible and no implicit advance to home |
| Held or repeated command key | No repeated sends and no accidental Continue |
| Late command after initial takeoff | Accept during running or the 2.5-second settled window |
| Queued second before first | Preserve the first-base force; allow D to cancel second without reversing home |
| Retreat and Send during return | Preserve every already observed position and touch |
| Early retreat | Reach the old bag before a physical return throw |
| Late retreat | Allow a tag at the return bag, despite its prior touch |
| Reserved return bag or unresolved force | Reject an illegal retreat and preserve the current route |
| New threat during a released throw | Preserve that throw and react through subsequent possession |
| Cutoff and follow-up plays | Consider existing runners as well as the batter and record each actual tag |
| Third out or scored runner | End or hand off controls without transferring a pending command |
| Recorded manual play | Live calls, replay, hit credit, running outs, and saved command history agree |
| Early airborne Send, then landing or drop | Preserve the head start and initial advance allowance |
| Early airborne Send, then catch | Warn persistently; require player Retreat and a physical defensive appeal |
| Correction from beyond an intermediate bag | Retouch each passed bag in reverse order without rewriting history |
| Premature home touch or multiple runners needing correction | Keep each runner selectable with Tab |
| Third-out appeal or advantageous subsequent appeal | Apply runner-order scoring and record only the official inning outs |

Run race and retreat scenarios at normal and coarse frame intervals. Auto retains its complete algorithmic running policy and ignores both manual commands.
