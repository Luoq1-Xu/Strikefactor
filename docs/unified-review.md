# Unified Review

Implemented in the working tree. One workspace hosts PitchViz, swing analysis,
and original ball/fielding playback.

Pitch flight (T) was moved back **out** of the workspace. It is the quick glance
— one keypress swaps to the full-screen `VisualizationState` and the same key
swaps back — while PitchViz is the analytical, configurable view that lives
here. T is therefore not a Review shortcut: it neither opens the workspace nor
switches its view, and the workspace has no Pitch Flight tab.

## Interaction contract

V, R and F (or their remapped keys) enter the workspace at the corresponding
view. V opens history; R/F find the latest eligible swing/recorded play. The
three keys on the completed-play screen instead target **that pitch**, including when its
fielding recording is unavailable. Inside Review the keys only change the view,
never the pitch. Escape/Enter close without advancing gameplay.

History rows focus a pitch; checkboxes independently select comparison pitches.
Type and inning/session filters affect the list, not existing checkmarks. Select
Filtered is additive; Clear is global. Up/Down navigate the filtered list; the
mouse wheel scrolls it. Hide List gives the active view the full content column.
Missing recordings are explained, not replaced with the latest unrelated clip.
The focused pitch number, pitcher, type, velocity, result and pre-pitch count
remain visible above every view.

Shared transport: play/pause, restart, seekable timeline with event snapping,
previous/next event, three view-specific speeds and loop. Space restarts from a
finished clip. Left/Right scrub in source-time increments, Home/End seek to the
boundaries, 1/2/3 choose the labelled speed. Tab or the camera button toggles
Swing's side/overhead view without resetting playback. Remapped view shortcuts
win over local transport shortcuts (except close); conflicting local hints are
suppressed and all those controls remain available as buttons.

Each view retains its own playback position, speed and loop state when switching
away and back. Changing the focused pitch does not restart a trajectory
comparison. Reopening the workspace starts fresh playback; closing releases
adapter references so they cannot defeat recording eviction.

## Data ownership

- `gameplay/review_record.py`: frozen `ReviewRecord` and timestamped `PitchPoint`.
  Metadata includes the committed hand, count, bases and inning/session scope.
  Payloads are the existing pitch trajectory object, optional `SwingRecord`, and
  optional `FieldingRecord`—not copies of their physical models.
- `gameplay/review_store.py`: session-local identity, publication, latest-eligible
  lookup, ABS metadata revisions and fielding retention. IDs are allocated before
  the pitch is played, as `(session generation, sequence)`. They are independent
  of database IDs, list offsets and the old fielding-only play counter.
- `PitchSimulation._publish_review()`: builds once after the result settles.
  Animated plays publish immediately after their one completion callback, before
  Continue; unanimated results publish at cleanup. Calling it again is a no-op.
  It never calls cleanup, scores a play, trains AI, draws randomness or logs a
  database row. Cleanup still owns those effects. The old `last_swing` and
  `last_fielding_play` values are compatibility aliases, not join keys.
- Taken pitches still retain their pitch trajectory. Fouls retain their own
  swing metrics without widening any existing database column's meaning. No
  database migration, replay persistence or historical reconstruction is added.
- ABS revisions replace the matching review entry's outcome metadata; they do
  not recolor/rebuild the captured geometry. Both pitch renderers derive color
  from the revised outcome vocabulary.

Pitch timestamps name the ball position sampled, not the later wall-clock time
at which the trail is appended. `_update_pitch_trajectory` runs before that
frame's ball update, so timestamping with its `current_time` would be one source
frame wrong. `_update_ball_position` stamps `_ball_sample_ms`; every trace append
captures it. Duplicate times collapse in the snapshot, and the first labelled
endpoint ends the replayable trail. Call/banner hold frames are not flight.

Session history spans GameDay innings; filtering defaults to the current inning.
Fielding capture remains bounded by the recorder's per-play limit and the
store's 14,400-frame / eight-clip cache. Eviction removes only fielding payloads,
leaving a visible reason and all pitch/swing metadata. The most recent complete
clip is pinned. A new session, resume or session teardown clears review data;
resuming saved GameDay state does not claim to restore unsaved replay clips.

## Rendering and clocks

`ui/review_overlay.py` owns chrome, focus, comparison, history and input.
`ui/review_playback.py` is the local transport. `ui/review_views.py` adapts:

| View | Source | Clock / default |
| --- | --- | --- |
| PitchViz | Original screen samples, re-centred on the zone | Release-aligned pitch milliseconds; 0.25×; loop with a 400 ms source-time endpoint hold |
| Swing | Existing `SwingRecord` and `SwingReplayOverlay` geometry/diagnostics | Swing-window pitch milliseconds; 1/12× |
| Fielding | Existing immutable frames and `fielding_renderer.draw_frame` | Original-animation milliseconds; 0.5× |

Pitch and Swing speed labels are literal fractions of real pitch time. A
0.41-second flight takes 0.41 seconds at 1× and 1.64 seconds at the 0.25× pitch
default. Swing keeps its 1/12× default for its shorter contact window. The modal
shows its opening frame before advancing playback and resets the shared clock
after that frame is displayed, excluding pre-modal time and initial renderer/font
setup from playback.

PitchViz compares the checked pitches over one release-aligned cycle: a shorter
flight holds while the longest finishes. Fielding
samples its original collision/possession boundaries and does not interpolate
through them. Swing embeds its original renderer without the old modal chrome;
its projection is re-fitted isotropically when the history sidebar changes width.
Seeking to the endpoint also completes the diagnostic ghost fade.

There is **no** continuous cross-view timeline or automatic pitch-to-field cut.
Source times are explicit and never inferred from display FPS or normalized
slider percentages. The pitch model, scored closest approach, replay surface
entry and fielding presentation clock have different boundaries. Linking those
is future work, not a reason to move the bat or rerun a fielding play.

## Modal lifecycle

`ui/review_modal.run_modal` is the single host, also used by the one surviving
compatibility wrapper, `_run_swing_replay_loop`. `Game.request_review` gates it to safe moments:
between pitches, completed-play screens and result screens. A live pitch or
unfinished fielding play cannot open it.

Only the review handles input. Mouse coordinates cross from the window to the
internal surface once. Resize, fullscreen and QUIT remain operational. Background
pygame_gui widgets are neither drawn nor sent input. Close leaves the actual
underlying state object in place—no `exit()`/`enter()` reconstruction, no menu
routing and no repeated inning/walk-off transitions.

A `finally` block compensates animation start time, ABS review deadlines,
state transition/celebration timestamps and scheduled banners. The shared clock
and held-key set are refreshed on return. Both the main loop and completed-play
loop discard the remainder of the batch that originally opened Review; otherwise
a click queued beside the review key could become Continue immediately on close.

Legacy `StatSwing`, `ViewPitchesState` and `_run_swing_replay_loop` remain
compatibility surfaces. No normal button or hotkey enters those states/windows;
the visible sidebar has one REVIEW action. `VisualizationState` is the exception
— it is live again as the T view (`Game.toggle_track`).

A compatibility surface may keep an entry point alive; it may not keep a second
renderer alive. `_run_swing_replay_loop` costs nothing because it drives the same
`SwingReplayOverlay` object that `SwingView` wraps. Fielding had no such object —
`ui/fielding_replay_overlay.py` was a second implementation of the transport, the
fielding view and the overlay chrome, and is deleted along with
`Game._run_fielding_replay_loop`. Its `play_label` header moved into
`FieldingView`'s stats row. Every behaviour its tests pinned is pinned against the
live stack in `tests/test_review.py`: local deterministic seeking and layout
containment (`test_views_seek_deterministically_and_layout_contains_controls`),
timeline snap and drag clamping (`test_timeline_drag_snaps_to_original_event_and_clamps`),
the empty clip (`test_live_play_is_gated_and_empty_or_incomplete_record_is_explained`)
and the modal's wall-clock compensation
(`test_modal_restores_clocks_consumes_close_batch_and_does_not_reenter_state`).

## Verification

`tests/test_review.py` covers identity and publication timing, frozen data,
retention, ABS revisions, take/foul/empty clips, focus vs comparison, remapping,
view-state preservation, deterministic seeking, source timestamps, FPS-independent
transport, isotropic swing layout, modal return/QUIT/error handling, and event
batch isolation. Existing swing and fielding geometry/rendering tests remain in
place. Headless visual previews were also checked with the list both open and
closed; the history count and playback caption have separate layout bounds.

```bash
pytest -n0 tests/test_review.py tests/test_swing_replay.py tests/test_fielding_replay.py
pytest
ruff check .
```

Out of scope: disk/video export, audio replay, new cameras or runner paths,
reconstructing old database plays, and seamless full-play playback.
