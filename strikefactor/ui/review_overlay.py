"""One modal review workspace: independent focus, comparison and playback."""

import pygame

from strikefactor.gameplay.review_record import scope_for
from strikefactor.key_binding_manager import KeyAction
from strikefactor.ui import gameday_theme as gdt
from strikefactor.ui.review_views import FieldingView, PitchView, SwingView

# Pitch flight (T) is deliberately absent: it is the quick standalone view,
# `VisualizationState`, and PitchViz is the analytical one that lives here.
VIEWS = ("zone", "swing", "fielding")
VIEW_NAMES = ("PITCHVIZ", "SWING", "FIELDING")
VIEW_ACTIONS = (KeyAction.VIEW_PITCHES, KeyAction.SWING_REPLAY, KeyAction.FIELDING_REPLAY)


def view_for_key(bindings, key):
    return next((view for view, action in zip(VIEWS, VIEW_ACTIONS)
                 if bindings.get_key_for_action(action) == key), None)


class ReviewOverlay:
    def __init__(self, game):
        self.game = game
        self._fonts = None
        self._generation = None
        self._active = False
        self.focus_id = None
        self.selected = set()
        self._known_ids = set()
        self.filter_type = "ALL"
        self.filter_scope = None
        self.view = "zone"
        self.sidebar = True
        self.scroll = 0
        self._dragging = False
        self._adapters = {}
        self._mouse_pos = (0, 0)

    @property
    def fonts(self):
        if self._fonts is None:
            self._fonts = gdt.load_fonts()
        return self._fonts

    @property
    def store(self):
        return self.game.review_store

    @property
    def focus(self):
        return self.store.get(self.focus_id)

    @property
    def filtered(self):
        return tuple(r for r in reversed(self.store.records)
                     if (self.filter_scope is None or r.scope == self.filter_scope)
                     and (self.filter_type == "ALL" or r.pitch_type == self.filter_type))

    def trigger(self, *, view="zone", record_id=None):
        if self._generation != self.store.generation:
            self._generation = self.store.generation
            self.selected.clear()
            self._known_ids.clear()
            self.filter_type = "ALL"
            self.filter_scope = scope_for(self.game)
            self.focus_id = None
            self._adapters.clear()
        latest = (self.store.get(record_id) if record_id is not None else
                  self.store.latest(view if view in ("swing", "fielding") else None))
        if record_id is not None and latest is None:
            self.focus_id = None
        elif latest is not None:
            self.focus_id = latest.review_id
            # A latest-swing shortcut may target a previous inning. Show its
            # row rather than presenting an invisible selection as this inning.
            if self.filter_scope is not None and latest.scope != self.filter_scope:
                self.filter_scope = latest.scope
            if self.filter_type not in ("ALL", latest.pitch_type):
                self.filter_type = "ALL"
        elif view in ("swing", "fielding"):
            last = self.store.latest()
            self.focus_id = last.review_id if last else None
        new_ids = {r.review_id for r in self.filtered} - self._known_ids
        self.selected.update(new_ids)
        self._known_ids.update(r.review_id for r in self.store.records)
        self.view = view
        self.sidebar = view == "zone"
        self.scroll = 0
        self._ensure_focus_visible()
        self._active = True
        self._dragging = False

    def is_active(self):
        return self._active

    def dismiss(self):
        self._active = False
        self._dragging = False
        # Drop renderer/record references so the store's fielding budget is a
        # real bound, not undermined by an invisible old adapter retaining clips.
        self._adapters.clear()

    def switch_view(self, view):
        self.view = view
        self._dragging = False

    def focus_pitch(self, review_id):
        self.focus_id = review_id
        self._ensure_focus_visible()

    def _ensure_focus_visible(self):
        ids = [r.review_id for r in self.filtered]
        if self.focus_id in ids:
            i = ids.index(self.focus_id)
            rows = max(1, self._list_rect().height // 54)
            self.scroll = max(0, min(self.scroll, i))
            if i >= self.scroll + rows:
                self.scroll = i - rows + 1

    def adapter(self):
        if self.view == "zone":
            records = tuple(r for r in self.store.records if r.review_id in self.selected and r.points)
            if not records:
                return None
            key = (self.view, tuple(r.review_id for r in records))
        else:
            if self.focus is None or self.focus.unavailable(self.view):
                return None
            key = (self.view, self.focus_id)
        if key not in self._adapters:
            # Retain one subject per view, not a full-sized render surface for
            # every combination of comparison checkboxes the user has tried.
            self._adapters = {k: v for k, v in self._adapters.items() if k[0] != self.view}
            if self.view == "zone":
                adapter = PitchView(self.game, records, self.focus)
            else:
                adapter = {"swing": SwingView, "fielding": FieldingView}[self.view](self.game, self.focus)
            self._adapters[key] = adapter
        adapter = self._adapters[key]
        if isinstance(adapter, PitchView):
            adapter.focus = self.focus  # changing the batter must not restart comparison
        return adapter

    def update(self, dt_ms):
        if self._active and (adapter := self.adapter()) is not None:
            adapter.playback.update(dt_ms)

    def _content_rect(self):
        x = 304 if self.sidebar else 24
        return pygame.Rect(x, 102, self.game.internal_width - x - 24, self.game.internal_height - 230)

    def _list_rect(self):
        return pygame.Rect(24, 207, 260, self.game.internal_height - 371)

    def _history_caption_rect(self):
        return pygame.Rect(24, self._list_rect().bottom + 8, 260, 24)

    def _playback_caption_rect(self):
        return pygame.Rect(24, self.game.internal_height - 121, self.game.internal_width - 48, 22)

    def _timeline(self):
        return pygame.Rect(24, self.game.internal_height - 96, self.game.internal_width - 48, 14)

    def _buttons(self):
        w, h = self.game.internal_width, self.game.internal_height
        specs = [("close", "CLOSE", pygame.Rect(w - 106, 15, 82, 28)),
                 ("sidebar", "HISTORY" if not self.sidebar else "HIDE LIST", pygame.Rect(24, 57, 112, 28))]
        x = 156
        for view, name, action in zip(VIEWS, VIEW_NAMES, VIEW_ACTIONS):
            bindings = self.game.key_binding_manager
            key_name = bindings.get_key_name(bindings.get_key_for_action(action))
            label = f"{name} [{key_name}]"
            width = self.fonts['micro'].size(label)[0] + 20
            specs.append((view, label, pygame.Rect(x, 57, width, 28)))
            x += width + 10
        if self.sidebar:
            specs += [("filter", f"TYPE: {self.filter_type} >", pygame.Rect(24, 102, 260, 28)),
                      ("scope", f"SCOPE: {self.filter_scope or 'ALL SESSION'} >", pygame.Rect(24, 136, 260, 28)),
                      ("all", "SELECT FILTERED", pygame.Rect(24, 171, 159, 28)),
                      ("clear", "CLEAR", pygame.Rect(191, 171, 93, 28))]
        adapter = self.adapter()
        if adapter is not None:
            p = adapter.playback
            x = 24
            controls = [("play", "PLAY" if p.paused else "PAUSE", 80), ("restart", "RESTART", 90),
                        ("prev", "PREV EVENT", 116), ("next", "NEXT EVENT", 116)]
            controls += [(f"speed{i}", label, 72) for i, label in enumerate(adapter.speed_labels)]
            controls += [("loop", "LOOP ON" if p.loop else "LOOP OFF", 95)]
            if isinstance(adapter, SwingView):
                controls += [("camera", "SIDE / OVERHEAD", 164)]
            for action, label, width in controls:
                specs.append((action, label, pygame.Rect(x, h - 66, width, 28)))
                x += width + 8
        return specs

    def _activate(self, action):
        if action in VIEWS:
            self.switch_view(action)
        elif action == "close":
            self.dismiss()
        elif action == "sidebar":
            self.sidebar = not self.sidebar
        elif action == "filter":
            types = ["ALL"] + sorted({r.pitch_type for r in self.store.records})
            self.filter_type = types[(types.index(self.filter_type) + 1) % len(types)]
            self.scroll = 0
        elif action == "scope":
            scopes = [None] + list(dict.fromkeys(r.scope for r in self.store.records))
            index = scopes.index(self.filter_scope) if self.filter_scope in scopes else -1
            self.filter_scope = scopes[(index + 1) % len(scopes)]
            self.scroll = 0
        elif action == "all":
            self.selected.update(r.review_id for r in self.filtered)
        elif action == "clear":
            self.selected.clear()
        elif (adapter := self.adapter()) is not None:
            p = adapter.playback
            if action == "play":
                p.toggle()
            elif action == "restart":
                p.restart()
            elif action in ("prev", "next"):
                p.step_event(adapter.events, -1 if action == "prev" else 1)
            elif action.startswith("speed"):
                p.speed = adapter.speeds[int(action[-1])]
            elif action == "loop":
                p.loop = not p.loop
            elif action == "camera" and isinstance(adapter, SwingView):
                adapter.toggle_camera()

    def _seek_at(self, x, snap=False):
        adapter = self.adapter()
        if adapter is None:
            return
        timeline = self._timeline()
        duration = max(1.0, adapter.playback.duration_ms)
        if snap:
            nearest = min(adapter.events, key=lambda e: abs(timeline.x + e[0] / duration * timeline.width - x),
                          default=None)
            if nearest is not None and abs(timeline.x + nearest[0] / duration * timeline.width - x) <= 8:
                adapter.playback.seek(nearest[0])
                return
        adapter.playback.seek((x - timeline.x) / timeline.width * duration)

    def handle_event(self, event):
        if not self._active:
            return False
        if hasattr(event, 'pos'):
            self._mouse_pos = event.pos
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.dismiss()
            elif (view := view_for_key(self.game.key_binding_manager, event.key)) is not None:
                self.switch_view(view)
            elif event.key == pygame.K_SPACE:
                self._activate("play")
            elif event.key == pygame.K_TAB:
                self._activate("camera")
            elif event.key in (pygame.K_UP, pygame.K_DOWN):
                ids = [r.review_id for r in self.filtered]
                if ids:
                    i = ids.index(self.focus_id) if self.focus_id in ids else 0
                    self.focus_pitch(ids[max(0, min(len(ids) - 1, i + (-1 if event.key == pygame.K_UP else 1)))])
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                self._activate(f"speed{event.key - pygame.K_1}")
            elif event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_HOME, pygame.K_END):
                if (adapter := self.adapter()) is not None:
                    p = adapter.playback
                    target = {pygame.K_HOME: 0, pygame.K_END: p.duration_ms,
                              pygame.K_LEFT: p.time_ms - adapter.step_ms,
                              pygame.K_RIGHT: p.time_ms + adapter.step_ms}[event.key]
                    p.seek(target)
        elif event.type == pygame.MOUSEWHEEL and self.sidebar and self._list_rect().collidepoint(self._mouse_pos):
            rows = max(1, self._list_rect().height // 54)
            self.scroll = max(0, min(max(0, len(self.filtered) - rows), self.scroll - event.y * 3))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for action, _, rect in self._buttons():
                if rect.collidepoint(event.pos):
                    self._activate(action)
                    return True
            if self.sidebar and self._list_rect().collidepoint(event.pos):
                i = self.scroll + (event.pos[1] - self._list_rect().y) // 54
                if i < len(self.filtered):
                    record = self.filtered[i]
                    if event.pos[0] < self._list_rect().x + 32:
                        self.selected.symmetric_difference_update({record.review_id})
                    else:
                        self.focus_pitch(record.review_id)
            elif self._timeline().inflate(0, 12).collidepoint(event.pos):
                self._dragging = True
                self._seek_at(event.pos[0], snap=True)
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            self._seek_at(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        return True  # modal: no click/key falls through to Continue or gameplay

    def _text(self, screen, text, rect, *, color=gdt.FG, font='micro'):
        previous = screen.get_clip()
        screen.set_clip(rect)
        gdt.blit_text(screen, text, self.fonts[font], rect.topleft, color)
        screen.set_clip(previous)

    def render(self, screen):
        if not self._active:
            return
        w, h = self.game.internal_width, self.game.internal_height
        screen.fill(gdt.BG)
        self._text(screen, "REVIEW", pygame.Rect(24, 20, 96, 24), font='small')
        record = self.focus
        if record:
            balls, strikes, outs = record.count
            title = (f"#{record.number} · {record.pitcher} · {record.pitch_type} {record.speed_mph:.0f} MPH"
                     f" · {record.outcome} · {balls}-{strikes}, {outs} OUT · {record.scope}")
            self._text(screen, title, pygame.Rect(132, 22, w - 254, 22))
        if self.sidebar:
            previous = screen.get_clip()
            area = self._list_rect()
            screen.set_clip(area)
            for i, rec in enumerate(self.filtered[self.scroll:]):
                y = area.y + i * 54
                if y >= area.bottom:
                    break
                row = pygame.Rect(area.x, y, area.width, 52)
                if rec.review_id == self.focus_id:
                    pygame.draw.rect(screen, (30, 30, 30), row)
                check = pygame.Rect(area.x + 5, y + 10, 18, 18)
                pygame.draw.rect(screen, gdt.DIM, check, 1)
                if rec.review_id in self.selected:
                    pygame.draw.rect(screen, gdt.FG, check.inflate(-6, -6))
                gdt.blit_text(screen, f"#{rec.number} {rec.pitch_type} {rec.speed_mph:.0f} MPH",
                              self.fonts['small'], (area.x + 36, y + 4), gdt.FG)
                gdt.blit_text(screen, rec.outcome, self.fonts['micro'], (area.x + 36, y + 28), gdt.DIM)
            screen.set_clip(previous)
            self._text(screen, f"{len(self.filtered)} SHOWN · {len(self.selected)} COMPARED",
                       self._history_caption_rect(), color=gdt.DIM)
        adapter = self.adapter()
        content = self._content_rect()
        if adapter is not None:
            adapter.draw(screen, content)
            p = adapter.playback
            timeline = self._timeline()
            pygame.draw.line(screen, gdt.DIM_SOFT, timeline.midleft, timeline.midright, 2)
            duration = max(1.0, p.duration_ms)
            for t, _ in adapter.events:
                x = timeline.x + t / duration * timeline.width
                pygame.draw.line(screen, (190, 165, 85), (x, timeline.y), (x, timeline.bottom), 2)
            x = timeline.x + p.time_ms / duration * timeline.width
            pygame.draw.circle(screen, gdt.FG, (round(x), timeline.centery), 5)
            event_label = next((label for t, label in reversed(adapter.events) if t <= p.time_ms), "")
            self._text(screen, f"{p.time_ms / 1000:.2f} / {p.duration_ms / 1000:.2f} S · "
                       f"{adapter.clock_label} · {event_label}", self._playback_caption_rect(), color=gdt.DIM)
        else:
            message = ("No pitches to review yet." if not self.store.records else
                       "Select pitches using the history checkboxes." if self.view == "zone" else
                       record.unavailable(self.view) if record else "No pitch selected.")
            gdt.blit_text(screen, message, self.fonts['small'], content.center, gdt.DIM, align='center')
        for action, label, rect in self._buttons():
            selected = action == self.view
            if adapter is not None and action.startswith("speed"):
                selected = adapter.playback.speed == adapter.speeds[int(action[-1])]
            if adapter is not None and action == "camera":
                label = "SIDE" if adapter.camera == 0 else "OVERHEAD"
            pygame.draw.rect(screen, gdt.FG if selected else gdt.DIVIDER, rect, 0 if selected else 1)
            self._text(screen, label, rect.inflate(-12, -8), color=gdt.BG if selected else gdt.FG)
        hints = [("SPACE PLAY/PAUSE", (pygame.K_SPACE,)),
                 ("LEFT/RIGHT SCRUB", (pygame.K_LEFT, pygame.K_RIGHT)),
                 ("UP/DOWN PITCH", (pygame.K_UP, pygame.K_DOWN)),
                 ("1/2/3 SPEED", (pygame.K_1, pygame.K_2, pygame.K_3)),
                 ("TAB CAMERA", (pygame.K_TAB,))]
        hint = " · ".join(label for label, keys in hints
                          if all(view_for_key(self.game.key_binding_manager, k) is None for k in keys))
        self._text(screen, hint + " · ESC CLOSE", pygame.Rect(24, h - 27, w - 48, 22), color=gdt.DIM)
