"""The one pause/input boundary for review, including legacy overlay adapters."""

import pygame


def active_simulation(game, simulation=None):
    state = game.state_manager.current_state
    return simulation or getattr(state, 'pitch_simulation', None)


def can_review(game, simulation=None):
    sim = active_simulation(game, simulation)
    if sim is not None and sim.running:
        anim = getattr(sim, 'hit_animation', None)
        return anim is not None and anim.banner_fired
    return True


def run_modal(game, overlay, *, simulation=None, background=False):
    state = game.state_manager.current_state
    sim = active_simulation(game, simulation)
    started = pygame.time.get_ticks()
    first_frame = True
    try:
        while overlay.is_active():
            dt_ms = game.clock.tick_busy_loop(60)
            # Drain and consume the entire batch. A close key must not leave a
            # queued click to become Continue or a swing in the underlying loop.
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    overlay.dismiss()
                    pygame.event.post(event)
                    return
                if event.type in (pygame.VIDEORESIZE, pygame.WINDOWRESIZED):
                    game._update_scaling()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    game.toggle_fullscreen()
                else:
                    translate = getattr(game, '_translate_mouse_event', lambda e: e)
                    overlay.handle_event(translate(event))
            if background:
                game.screen.fill('black')
                if state is not None:
                    state.render(game.screen)
                game._draw_active_hud(game.screen)
            # Show the opening frame before advancing. The shared clock can
            # include time spent in gameplay before the modal was entered.
            overlay.update(0 if first_frame else dt_ms)
            overlay.render(game.screen)
            game.flip_display()
            if first_frame:
                # Lazy renderer/font setup must not consume the short clip
                # before the player has seen it either.
                game.clock.tick()
                first_frame = False
    finally:
        overlay.dismiss()
        paused_ms = pygame.time.get_ticks() - started
        if sim is not None and sim.running:
            anim = getattr(sim, 'hit_animation', None)
            if anim is not None and anim.start_time is not None:
                anim.start_time += paused_ms
        if getattr(game, 'pending_challenge', None) is not None:
            game.pending_challenge['opened_at'] += paused_ms
        for attr in ('last_time', '_celebration_start'):
            if getattr(state, attr, None) is not None:
                setattr(state, attr, getattr(state, attr) + paused_ms)
        pending = getattr(getattr(game, 'ui_manager', None), '_pending_banner', None)
        if pending is not None:
            pending['show_time'] += paused_ms
        game.clock.tick()
        bindings = getattr(game, 'key_binding_manager', None)
        if bindings is not None:
            bindings.pressed_keys.clear()
        game._review_returned = True
