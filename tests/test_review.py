"""One pitch, four views; review must never become a second play."""

import random
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pygame
import pytest
from test_swing_replay import _FakeSim, make_record

from strikefactor.gameplay.fielding_record import FieldingEvent, FieldingFrame, FieldingRecord
from strikefactor.gameplay.review_record import PitchPoint, ReviewRecord, from_simulation
from strikefactor.gameplay.review_store import ReviewStore
from strikefactor.key_binding_manager import KeyAction
from strikefactor.ui.review_modal import can_review, run_modal
from strikefactor.ui.review_overlay import ReviewOverlay
from strikefactor.ui.review_playback import Playback
from strikefactor.ui.review_views import FieldingView, PitchView, SwingView


class Bindings:
    def __init__(self):
        self.keys = dict(zip((KeyAction.VIEW_PITCHES, KeyAction.TOGGLE_TRACK,
                              KeyAction.SWING_REPLAY, KeyAction.FIELDING_REPLAY),
                             (pygame.K_v, pygame.K_t, pygame.K_r, pygame.K_f)))
        self.pressed_keys = set()

    def get_key_for_action(self, action):
        return self.keys.get(action)

    def get_key_name(self, key):
        return pygame.key.name(key).upper()


@pytest.fixture
def game():
    return SimpleNamespace(
        internal_width=1280, internal_height=720,
        screen=pygame.Surface((1280, 720)), review_store=ReviewStore(),
        key_binding_manager=Bindings(), gameday_manager=None,
        state_manager=SimpleNamespace(current_state=SimpleNamespace(last_time=1000)),
        clock=SimpleNamespace(tick_busy_loop=lambda fps: 16, tick=lambda: None),
        flip_display=lambda: None, _translate_mouse_event=lambda e: e,
        pending_challenge={'opened_at': 1500},
        ui_manager=SimpleNamespace(_pending_banner={'show_time': 2000}),
    )


def field_clip(n=3):
    frames = tuple(FieldingFrame(i * 100, (640 + i, 600 - i), (640 + i, 610 - i),
                                 True, True, ()) for i in range(n))
    return FieldingRecord(frames, (FieldingEvent(0, 'CONTACT'), FieldingEvent(100, 'BALL SECURED')),
                          'PLAY', 'GROUNDOUT', exit_velocity_mph=93, launch_angle_deg=5)


def publish(store, *, swing=None, fielding=None, pitch_type='FF', scope='SESSION'):
    rec = ReviewRecord(store.allocate_id(), 'deGrom', pitch_type, 99, 'GROUNDOUT' if fielding else 'BALL',
                       'R', (1, 2, 0), scope,
                       (PitchPoint(0, 640, 280, 4), PitchPoint(200, 630, 420, 7),
                        PitchPoint(400, 620, 490, 11)), swing=swing, fielding=fielding)
    store.publish(rec)
    return rec


def key(view, code):
    view.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code))


def click(view, action):
    rect = next(rect for name, _, rect in view._buttons() if name == action)
    view.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))


def test_ids_survive_scope_changes_and_reject_late_publication():
    store = ReviewStore()
    a = publish(store, scope='INNING 1')
    b = publish(store, scope='INNING 2')
    assert a.review_id != b.review_id
    store.clear()
    c = publish(store)
    assert c.review_id != a.review_id
    store.publish(a)
    assert store.records == (c,)


def test_fielding_cache_bounds_frames_and_clips_but_pins_latest():
    store = ReviewStore()
    store.MAX_FIELDING_FRAMES = 5
    a = publish(store, swing=make_record(), fielding=field_clip())
    b = publish(store, fielding=field_clip())
    assert store.get(a.review_id).fielding is None
    assert store.get(a.review_id).swing is a.swing
    assert 'no longer retained' in store.get(a.review_id).unavailable('fielding')
    assert store.latest('fielding') == b
    store.MAX_FIELDING_CLIPS = 1
    c = publish(store, fielding=field_clip(6))
    assert store.latest('fielding') == c  # sole clip is never evicted
    assert store.get(b.review_id).fielding is None
    assert len(store.records) == 3


def test_outcome_revision_replaces_metadata_not_trajectories_or_identity():
    store = ReviewStore()
    rec = publish(store)
    store.revise_outcome(rec.review_id, 'STRIKE')
    revised = store.get(rec.review_id)
    assert revised.review_id == rec.review_id
    assert revised.points is rec.points
    assert revised.outcome == 'STRIKE'
    assert rec.outcome == 'BALL'
    with pytest.raises(FrozenInstanceError):
        revised.outcome = 'WALK'


def snapshot_sim(game, *, take=False, foul=False):
    sim = _FakeSim(swing_type=0 if take else 1, made_contact='fouled' if foul else 'hit')
    sim.game = game
    game.batter = SimpleNamespace(get_handedness=lambda: 'L')  # changed AFTER commit
    game.last_pitch_information = [[640, 280, 4, (255, 255, 255), ''],
                                   [630, 420, 7, (255, 255, 255), ''],
                                   [620, 490, 11, (255, 255, 255), 'strike'],
                                   [620, 490, 11, (255, 255, 255), 'strike']]
    sim.review_id = game.review_store.allocate_id()
    sim._review_handedness = 'R'
    sim._review_count = (1, 2, 0)
    sim._review_scope = 'SESSION'
    sim._review_bases = ('yellow', 'white', 'white')
    sim._review_sample_times = [0, 200, 400, 400]
    sim._ball_sample_ms = 400
    sim._fielding_recorder = None
    sim.hit_animation = None
    sim.pitchername = 'deGrom'
    sim._get_outcome_display = lambda: sim.outcome
    return sim


@pytest.mark.parametrize('take,foul', [(True, False), (False, False), (False, True)])
def test_snapshot_is_detached_and_preserves_committed_inputs(game, take, foul):
    sim = snapshot_sim(game, take=take, foul=foul)
    rng = random.getstate()
    rec = from_simulation(sim)
    assert random.getstate() == rng
    assert rec.trajectory is sim.trajectory  # includes TAKES, not just swings
    assert rec.handedness == 'R'
    assert rec.bases[0] == 'yellow'
    assert len(rec.points) == 3  # no call/banner hold frames
    assert [p.time_ms for p in rec.points] == [0, 200, 400]
    game.last_pitch_information[-2][0] = -100
    assert rec.points[-1].x == 620
    assert (rec.swing is None) == take
    if not take:
        assert rec.swing.handedness == 'R'
    if foul:
        assert rec.swing.contact_quality == sim._foul_quality
        assert 'disabled' in rec.unavailable('fielding')


@pytest.mark.parametrize('code,view_name', [(pygame.K_v, 'zone'), (pygame.K_r, 'swing'),
                                           (pygame.K_f, 'fielding')])
def test_completed_play_publishes_all_views_before_continue(game, monkeypatch, code, view_name):
    from test_fielding_replay import play

    from strikefactor.gameplay.pitch_simulation import PitchSimulation

    anim, recorder = play()
    sim = snapshot_sim(game)
    sim.hit_animation, sim._fielding_recorder = anim, recorder
    sim._publish_review = lambda: PitchSimulation._publish_review(sim)
    calls = []
    anim.on_complete = lambda: calls.append('finalized')
    sim._finish_pitch = lambda: pytest.fail('Review advanced the pitch')
    game.ui_manager.update = lambda dt: None
    game.ui_manager.draw = lambda: None
    game._window_to_internal = lambda x, y: (x, y)
    game.last_swing = make_record(outcome='HOME RUN')  # previous, unrelated pitch
    game.last_fielding_play = None

    def open_review(**kw):
        rec = game.review_store.get(kw['record_id'])
        assert rec is not None and rec.swing is not None
        assert rec.swing.outcome == sim.outcome
        assert rec.fielding is recorder.record
        assert kw['view'] == view_name
        calls.append('review')

    game.request_review = open_review
    event = pygame.event.Event(pygame.KEYDOWN, key=code)
    monkeypatch.setattr(pygame.event, 'get', lambda: [event])
    PitchSimulation._handle_hit_animation_phase(sim, anim.start_time + anim._elapsed, 0.016)
    PitchSimulation._handle_hit_animation_phase(sim, anim.start_time + anim._elapsed + 16, 0.016)
    assert calls == ['finalized', 'review', 'review']
    assert len(game.review_store.records) == 1
    sim._publish_review()  # cleanup can publish safely without appending again
    assert len(game.review_store.records) == 1


def test_focus_and_comparison_are_independent_and_no_stale_replay(game):
    hit = publish(game.review_store, swing=make_record(), fielding=field_clip())
    take = publish(game.review_store, pitch_type='SL')
    panel = ReviewOverlay(game)
    panel.trigger(view='zone')
    selected = panel.selected.copy()
    panel.focus_pitch(hit.review_id)
    panel.switch_view('swing')
    swing = panel.adapter()
    swing.playback.seek(20)
    panel.switch_view('fielding')
    panel.adapter().playback.seek(100)
    panel.switch_view('swing')
    assert panel.adapter() is swing
    assert panel.adapter().playback.time_ms == 20
    panel.focus_pitch(take.review_id)
    assert panel.adapter() is None
    assert 'taken' in panel.focus.unavailable('swing')
    panel.switch_view('fielding')
    assert panel.adapter() is None
    assert panel.selected == selected
    panel.dismiss()
    assert not panel._adapters  # no hidden cache defeats store eviction
    panel.trigger(view='swing')
    assert panel.focus_id == hit.review_id  # outside R finds latest eligible pitch


def test_fielding_entry_after_whiff_names_older_pitch_but_tab_switch_never_does(game):
    old = publish(game.review_store, swing=make_record(), fielding=field_clip(), scope='INNING 1')
    new = publish(game.review_store, scope='INNING 2')
    game.gameday_manager = SimpleNamespace(current_inning=2)
    panel = ReviewOverlay(game)
    panel.trigger(view='fielding')
    assert panel.focus_id == old.review_id
    assert panel.filter_scope == 'INNING 1'
    panel.focus_pitch(new.review_id)
    assert panel.adapter() is None


def test_filters_only_filter_history_select_all_is_filtered_and_clear_is_global(game):
    a = publish(game.review_store)
    b = publish(game.review_store, pitch_type='SL')
    panel = ReviewOverlay(game)
    panel.trigger()
    click(panel, 'clear')
    click(panel, 'filter')
    assert panel.filter_type == 'FF'
    click(panel, 'all')
    assert panel.selected == {a.review_id}
    panel.filter_type = 'SL'
    click(panel, 'all')
    assert panel.selected == {a.review_id, b.review_id}
    click(panel, 'clear')
    assert not panel.selected
    assert panel.adapter() is None


def test_new_pitches_appear_after_empty_first_open_and_focus_does_not_restart_comparison(game):
    panel = ReviewOverlay(game)
    panel.trigger()
    panel.dismiss()
    a, b = publish(game.review_store), publish(game.review_store)
    panel.trigger(view='zone')
    adapter = panel.adapter()
    adapter.playback.seek(100)
    panel.focus_pitch(a.review_id)
    assert panel.adapter() is adapter
    assert panel.adapter().playback.time_ms == 100
    assert panel.selected == {a.review_id, b.review_id}


def test_shortcuts_honor_remappings_and_camera_toggle_keeps_time(game):
    rec = publish(game.review_store, swing=make_record(), fielding=field_clip())
    game.key_binding_manager.keys[KeyAction.SWING_REPLAY] = pygame.K_j
    panel = ReviewOverlay(game)
    panel.trigger(record_id=rec.review_id)
    key(panel, pygame.K_j)
    assert panel.view == 'swing'
    adapter = panel.adapter()
    key(panel, pygame.K_RIGHT)
    t = adapter.playback.time_ms
    key(panel, pygame.K_TAB)
    assert adapter.camera == 1
    assert adapter.playback.time_ms == t
    labels = [label for _, label, _ in panel._buttons()]
    assert 'SWING [J]' in labels
    key(panel, pygame.K_f)
    for code, speed in [(pygame.K_1, .25), (pygame.K_2, .5), (pygame.K_3, 1.)]:
        key(panel, code)
        assert panel.adapter().playback.speed == speed
    key(panel, pygame.K_END)
    key(panel, pygame.K_SPACE)
    assert panel.adapter().playback.time_ms == 0
    assert not panel.adapter().playback.paused


@pytest.mark.parametrize('hz', [30, 60, 120, 144])
def test_transport_is_display_fps_independent(hz):
    p = Playback(2000, speed=.5)
    for _ in range(hz):
        p.update(1000 / hz)
    assert p.time_ms == pytest.approx(500)
    p.seek(1900)
    assert p.paused
    p.toggle()
    p.update(1000)
    assert p.time_ms == 2000 and p.paused
    p.toggle()
    assert p.time_ms == 0 and not p.paused


@pytest.mark.parametrize('view_name,speed', [('zone', .25), ('swing', 1 / 12), ('fielding', .5)])
def test_review_opens_in_slow_motion_and_one_x_uses_source_time(game, view_name, speed):
    publish(game.review_store, swing=make_record(), fielding=field_clip())
    panel = ReviewOverlay(game)
    panel.trigger(view=view_name)
    panel.update(200)
    playback = panel.adapter().playback
    assert playback.time_ms == pytest.approx(200 * speed)
    assert not playback.paused
    key(panel, pygame.K_3)
    playback.restart()
    panel.update(100)
    assert playback.time_ms == pytest.approx(100)


def test_pitch_comparison_holds_each_endpoint_until_longest_and_shared_loop(game):
    a = publish(game.review_store)
    b = replace(publish(game.review_store), points=(PitchPoint(0, 640, 280, 4), PitchPoint(600, 620, 490, 11)))
    view = PitchView(game, (a, b), a)
    assert view.playback.duration_ms == 1000
    view.playback.seek(700)
    view.draw(game.screen, pygame.Rect(0, 0, 1280, 720))
    first = pygame.image.tobytes(game.screen, 'RGB')
    view.playback.seek(999)
    view.draw(game.screen, pygame.Rect(0, 0, 1280, 720))
    assert pygame.image.tobytes(game.screen, 'RGB') == first


@pytest.mark.parametrize('view_name', ['zone', 'swing', 'fielding'])
@pytest.mark.parametrize('sidebar', [False, True])
def test_views_seek_deterministically_and_layout_contains_controls(game, view_name, sidebar):
    rec = publish(game.review_store, swing=make_record(), fielding=field_clip())
    panel = ReviewOverlay(game)
    panel.trigger(view=view_name, record_id=rec.review_id)
    panel.sidebar = sidebar
    adapter = panel.adapter()
    rng = random.getstate()
    adapter.playback.seek(adapter.playback.duration_ms)
    panel.render(game.screen)
    first = pygame.image.tobytes(game.screen, 'RGB')
    adapter.playback.seek(0)
    panel.render(game.screen)
    adapter.playback.seek(adapter.playback.duration_ms)
    panel.render(game.screen)
    assert pygame.image.tobytes(game.screen, 'RGB') == first
    assert random.getstate() == rng
    assert not panel._history_caption_rect().colliderect(panel._playback_caption_rect())
    assert not panel._list_rect().colliderect(panel._history_caption_rect())
    buttons = panel._buttons()
    for i, (_, _, rect) in enumerate(buttons):
        assert game.screen.get_rect().contains(rect)
        assert not any(rect.colliderect(other) for _, _, other in buttons[i + 1:])
    if isinstance(adapter, SwingView):
        sx, sy = adapter.renderer._px_per_ft()
        assert sx == pytest.approx(sy)
        assert panel._content_rect().contains(adapter.renderer._view_rect())
    if isinstance(adapter, FieldingView):
        assert adapter.record is rec.fielding


def test_timeline_drag_snaps_to_original_event_and_clamps(game):
    publish(game.review_store, fielding=field_clip())
    panel = ReviewOverlay(game)
    panel.trigger(view='fielding')
    timeline = panel._timeline()
    panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=timeline.center))
    assert panel.adapter().playback.time_ms == 100
    assert panel.adapter().playback.paused
    panel.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(-100, timeline.centery)))
    assert panel.adapter().playback.time_ms == 0
    panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1))
    click(panel, 'next')
    assert panel.adapter().playback.time_ms == 100


def test_modal_restores_clocks_consumes_close_batch_and_does_not_reenter_state(game, monkeypatch):
    rec = publish(game.review_store, fielding=field_clip())
    panel = ReviewOverlay(game)
    panel.trigger(view='fielding', record_id=rec.review_id)
    state = game.state_manager.current_state
    state.enter = lambda: pytest.fail('Re-entered underlying state')
    state._celebration_start = 1200
    state.pitch_simulation = SimpleNamespace(running=True, hit_animation=SimpleNamespace(start_time=100))
    times = iter([2000, 2500])
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: next(times))
    monkeypatch.setattr(pygame.event, 'get', lambda: [pygame.event.Event(pygame.KEYDOWN, key=k)
                                                    for k in (pygame.K_ESCAPE, pygame.K_SPACE)])
    rng = random.getstate()
    run_modal(game, panel)
    assert game.state_manager.current_state is state
    assert state.last_time == 1500 and state._celebration_start == 1700
    assert state.pitch_simulation.hit_animation.start_time == 600
    assert game.pending_challenge['opened_at'] == 2000
    assert game.ui_manager._pending_banner['show_time'] == 2500
    assert game._review_returned
    assert game.review_store.get(rec.review_id) is rec
    assert random.getstate() == rng


@pytest.mark.parametrize('view_name', ['zone', 'swing', 'fielding'])
def test_modal_starts_at_zero_and_excludes_first_frame_setup_time(game, monkeypatch, view_name):
    publish(game.review_store, swing=make_record(), fielding=field_clip())
    panel = ReviewOverlay(game)
    panel.trigger(view=view_name)
    playback = panel.adapter().playback
    pending_ms = 3000  # time spent in gameplay before entering the modal

    def tick(*args):
        nonlocal pending_ms
        elapsed, pending_ms = pending_ms, 16
        return elapsed

    game.clock = SimpleNamespace(tick_busy_loop=tick, tick=tick)
    frames = []
    render = panel.render

    def render_frame(screen):
        nonlocal pending_ms
        render(screen)
        frames.append(playback.time_ms)
        if len(frames) == 1:
            pending_ms += 2500  # loading fonts/renderer for the first visible frame
        else:
            panel.dismiss()

    panel.render = render_frame
    monkeypatch.setattr(pygame.event, 'get', lambda: [])
    run_modal(game, panel)
    assert frames == pytest.approx([0, 16 * playback.speed])


def test_live_play_is_gated_and_empty_or_incomplete_record_is_explained(game):
    state = game.state_manager.current_state
    state.pitch_simulation = SimpleNamespace(running=True, hit_animation=None)
    assert not can_review(game)
    state.pitch_simulation.hit_animation = SimpleNamespace(banner_fired=False)
    assert not can_review(game)
    state.pitch_simulation.hit_animation.banner_fired = True
    assert can_review(game)
    publish(game.review_store, fielding=field_clip(0))
    panel = ReviewOverlay(game)
    panel.trigger(view='fielding')
    assert panel.adapter() is None
    assert 'complete' in panel.focus.unavailable('fielding')
    panel.render(game.screen)


def test_trace_timestamp_names_the_sampled_ball_not_the_append_time(game):
    from strikefactor.gameplay.pitch_simulation import PitchSimulation
    from strikefactor.utils.pitch_physics import DEFAULT_CAMERA

    sim = snapshot_sim(game)
    sim.camera = DEFAULT_CAMERA
    game.ball = [640, 280, 54]
    game.blitfunc = lambda *args: None
    game.last_pitch_information = []
    sim._review_sample_times = []
    PitchSimulation._update_ball_position(sim, sim.starttime + sim.windup + 123)
    PitchSimulation._append_pitch_trace(sim, [*game.ball[:2], 7, (255, 255, 255), 'strike'])
    rec = from_simulation(sim)
    assert rec.points[0].time_ms == pytest.approx(123)
    assert (rec.points[0].x, rec.points[0].y) == tuple(game.ball[:2])


def test_session_reset_clears_latest_pointers_and_cached_renderers(game):
    from strikefactor.main import Game

    rec = publish(game.review_store, swing=make_record(), fielding=field_clip())
    game.review_overlay = ReviewOverlay(game)
    game.review_overlay.trigger(view='fielding')
    game.review_overlay.adapter()
    game.last_fielding_play, game.last_swing = rec.fielding, rec.swing
    Game._reset_review(game)
    assert not game.review_store.records
    assert game.last_swing is None and game.last_fielding_play is None
    assert not game.review_overlay._adapters
    assert not game.review_overlay.is_active()


def test_modal_resize_fullscreen_and_quit_are_handled_locally(game, monkeypatch):
    panel = ReviewOverlay(game)
    panel.trigger()
    calls = []
    game._update_scaling = lambda: calls.append('resize')
    game.toggle_fullscreen = lambda: calls.append('fullscreen')
    events = [pygame.event.Event(pygame.WINDOWRESIZED),
              pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11), pygame.event.Event(pygame.QUIT)]
    monkeypatch.setattr(pygame.event, 'get', lambda: events)
    monkeypatch.setattr(pygame.event, 'post', lambda e: calls.append(e.type))
    times = iter([100, 300])
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: next(times))
    run_modal(game, panel)
    assert calls == ['resize', 'fullscreen', pygame.QUIT]
    assert not panel.is_active()
    assert game.pending_challenge['opened_at'] == 1700


def test_pause_bookkeeping_also_runs_when_rendering_raises(game, monkeypatch):
    panel = ReviewOverlay(game)
    panel.trigger()
    panel.render = lambda screen: (_ for _ in ()).throw(RuntimeError('render failed'))
    monkeypatch.setattr(pygame.event, 'get', lambda: [])
    times = iter([100, 300])
    monkeypatch.setattr(pygame.time, 'get_ticks', lambda: next(times))
    with pytest.raises(RuntimeError, match='render failed'):
        run_modal(game, panel)
    assert game.pending_challenge['opened_at'] == 1700
    assert game.state_manager.current_state.last_time == 1200
    assert not panel.is_active()


def test_comparison_changes_do_not_cache_an_unbounded_number_of_surfaces(game):
    records = [publish(game.review_store) for _ in range(20)]
    panel = ReviewOverlay(game)
    panel.trigger()
    for i in range(len(records)):
        panel.selected = {r.review_id for r in records[:i + 1]}
        panel.adapter()
        assert len(panel._adapters) == 1


@pytest.mark.parametrize('button', [True, False])
def test_main_loop_discards_the_pre_review_input_batch(game, monkeypatch, button):
    from strikefactor.main import Game

    game.settings_manager = SimpleNamespace(get_display_fps=lambda: 60)
    game.clock.tick = lambda *args: 16
    game._draw_active_hud = lambda screen: None
    game.cleanup = lambda: None
    game.ui_manager.update = lambda dt: None
    game.ui_manager.draw = lambda: None
    game._review_returned = False
    sm = game.state_manager
    sm.current_state_name = 'gameplay'
    sm.is_current_state = lambda name: False
    sm.update = lambda dt: None
    sm.render = lambda screen: None
    calls = []

    def handle_key(code):
        calls.append(code)
        game._review_returned = True
        return True

    def handle_event(event):
        calls.append('button')
        game._review_returned = True
        return True

    game.key_binding_manager.handle_key_down = handle_key
    sm.handle_event = handle_event
    first = pygame.event.Event(pygame.USEREVENT) if button else pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v)
    batches = iter([[first, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
                    [pygame.event.Event(pygame.QUIT)]])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(batches))
    Game.run(game)
    assert calls == ['button' if button else pygame.K_v]


@pytest.mark.parametrize('truth,count,result', [(False, (3, 2, 0), 'WALK'),
                                              (False, (1, 1, 0), 'BALL'),
                                              (True, (0, 2, 0), 'STRIKEOUT'),
                                              (True, (0, 1, 0), 'STRIKE')])
def test_abs_revises_the_same_review_pitch_including_terminal_calls(game, truth, count, result):
    from strikefactor.main import Game

    rec = replace(publish(game.review_store), count=count)
    game.review_store.publish(rec)
    game.pending_challenge = dict(snapshot={}, truth_strike=truth, original_call='ball' if truth else 'strike',
                                  pitchtype='FF', speed_mph=99, ball_xy=(630, 485), review_id=rec.review_id)
    game.restore_for_abs = lambda snap: None
    game.dispatch_ball_call = lambda *args, **kw: None
    game.dispatch_strike_call = lambda *args, **kw: None
    game.last_pitch_information = []
    Game._reverse_last_call(game)
    assert len(game.review_store.records) == 1
    assert game.review_store.get(rec.review_id).outcome == result


def test_all_old_entry_points_route_to_one_workspace(game):
    from strikefactor.main import Game

    calls = []
    game.request_review = lambda **kw: calls.append(kw['view'])
    Game.toggle_view_pitches(game)
    Game.request_swing_replay(game)
    Game.request_fielding_replay(game)
    assert calls == ['zone', 'swing', 'fielding']


def test_pitch_flight_is_not_a_review_view(game):
    from strikefactor.ui.review_overlay import view_for_key

    publish(game.review_store)
    panel = ReviewOverlay(game)
    panel.trigger()
    assert view_for_key(game.key_binding_manager, pygame.K_t) is None
    key(panel, pygame.K_t)
    assert panel.view == 'zone'
    assert not any('FLIGHT' in label for _, label, _ in panel._buttons())


def _track_game(state_name, *, inning_ended=False, gamemode='Sasaki'):
    from strikefactor.main import Game

    went = []
    sm = SimpleNamespace(current_state_name=state_name, change_state=went.append,
                         handle_menu_state_change=lambda s: went.append(('menu', s)))
    game = SimpleNamespace(state_manager=sm, inning_ended=inning_ended, current_gamemode=gamemode,
                           menu_state='visualise' if state_name == 'visualization' else gamemode,
                           request_review=lambda **kw: pytest.fail('T opened Review'))
    game.set_menu_state = lambda s: Game.set_menu_state(game, s)
    game._exit_track = lambda: Game._exit_track(game)
    return Game, game, went


@pytest.mark.parametrize('state_name', ['gameplay', 'sandbox_gameplay', 'inning_end'])
def test_t_enters_the_standalone_flight_view_without_review(state_name):
    Game, game, went = _track_game(state_name)
    Game.toggle_track(game)
    assert went == [('menu', 'visualise')]
    assert game.menu_state == 'visualise'


@pytest.mark.parametrize('inning_ended,gamemode,target,menu', [
    (False, 'Sasaki', 'gameplay', 'Sasaki'),
    (False, 'sandbox_gameplay', 'sandbox_gameplay', 'sandbox_gameplay'),
    (True, 'Sasaki', 'inning_end', 'inning_end'),
])
def test_t_again_returns_to_where_the_player_was(inning_ended, gamemode, target, menu):
    Game, game, went = _track_game('visualization', inning_ended=inning_ended, gamemode=gamemode)
    Game.toggle_track(game)
    assert went == [target]
    assert game.menu_state == menu


def test_remapped_tab_still_opens_its_view_and_camera_button_still_works(game):
    publish(game.review_store, swing=make_record())
    game.key_binding_manager.keys[KeyAction.SWING_REPLAY] = pygame.K_TAB
    panel = ReviewOverlay(game)
    panel.trigger()
    key(panel, pygame.K_TAB)
    assert panel.view == 'swing'
    click(panel, 'camera')
    assert panel.adapter().camera == 1
