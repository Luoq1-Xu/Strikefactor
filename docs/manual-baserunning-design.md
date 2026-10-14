# Auto and manual baserunning design

Auto controls all running algorithmically. Manual gives runners at most one automatic advance and requires an explicit Send for each further base. Send and Retreat remain available throughout running, with another 2.5 seconds to decide after runners and possession settle. The field identifies the controlled runner and shows the current destination, any queued destination, and the exact destination each available button will choose.

## Modes and destinations

Persist `baserunning_mode` as `auto` or `manual`, defaulting to Auto. Snapshot it when the ball is put in play. It is independent of batting difficulty, defense strength, and Arcade, GameDay, or Sandbox.

In Manual, the batter runs to first. Existing runners take their normal required or safely justified first advance. They stop after that advance, including with two outs, until the player sends them farther. A held runner can also be sent on their first optional advance when the ordinary policy would hold. Legal tag-ups, forces, occupied bases, and the inning ending still govern every movement. Fouls have no manual controls. Home runs use the normal airborne-ball controls and running until the ball clears the fence; confirmation closes controls, cancels pending commands, and sends every runner home from their current position.

The most advanced live runner is highlighted, preserving baseball order through their starting base and stable play ID. A home-bound runner can still be controlled with Retreat when it is legal. When the runner scores or is retired, controls move to the next live runner. Pending commands belong to their original runner and are cancelled rather than transferred.

## Send and Retreat

**G**, remappable as Send Lead Runner, queues exactly the displayed next base. From a batter going to first, it queues second. Once the second-base leg begins, another G can queue third. A pending command has a fixed destination and cannot be consumed at some different future stopping point. One pending advance is allowed at a time; held keys and key repeat never create additional commands.

Execute the queued leg at the existing rounding decision near the current bag, or immediately from a held bag when legal. Use the runner's actual position and momentum. An unresolved first-base force remains authoritative; an early request for second waits for the force to resolve. Sending a runner onward cannot cancel an intermediate tag.

**D**, remappable as Retreat Lead Runner, cancels any queued advance and returns a moving runner toward their last touched base. It cannot return the batter home before first or send a runner into an occupied or reserved base. An initial forced runner must complete that force unless the force has been removed, such as by retiring the batter. A runner already holding a bag has no further backward movement available.

If retreating is illegal but an extra advance is queued, D cancels the queue and holds at the current destination. The prompt explicitly says HOLD AT in this case. For example, D can cancel a batter's queued second-base attempt while preserving the required run to first.

When every runner and the ball have settled, D also confirms HOLD AT the current bag and closes the decision window immediately. The key is still consumed, so confirming Hold does not accidentally start the next pitch.

G during a retreat turns the runner back toward the displayed next bag. `CircuitRun.return_to` and `resume_to` replace only the unplayed route tail. Past positions, base contacts, and released throws remain intact. Changes of direction have real acceleration costs. In Manual, retreat decisions belong to the player; the automatic escape behavior remains in Auto.

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

Retreat does not guarantee safety. An early retreat can beat a return throw; a late retreat can be tagged at its destination. Full chasing rundowns and throwing errors remain outside this feature.

## Implementation and records

`baserunning_control.py` owns the selected runner, explicit pending base, command history, legal opening, and settlement deadline in contact-relative seconds. `HitAnimation` applies legality and occupancy, controls routes, and keeps first-base timing authoritative. `runner_motion.py` owns continuous forward, return, and resume motion. `return_play.py` previews physical throws and evaluates defensive choices without pygame or random draws.

`PitchSimulation` snapshots mode and bound key names, handles Send and Retreat before Continue, and persists the control snapshot with the final `RunningResult`. Settings and key-binding panels scroll rather than shrinking rows. Adding a default command must preserve existing custom keys and reserve the swing and fullscreen keys.

Hit credit, final occupancy, and running outs remain distinct. A single followed by a tag at second or on a retreat to first remains a single plus a running out. Successful advances conceded by another throw retain their existing scoring treatment. Third-out timing and earned-run reconstruction use actual movements and retirement times.

Database schema 14 has the nullable `baserunning_mode` column. Running-play JSON schema 3 adds a command ledger with action, runner, destination, input time, execution time, status, and cancellation reason. Historical rows remain unknown; no old record is rewritten. Presentation frames include current destination and both command hints, while the renderer continues to accept the earlier five-field Send overlay.

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

Run race and retreat scenarios at normal and coarse frame intervals. Auto retains its complete algorithmic running policy and ignores both manual commands.
