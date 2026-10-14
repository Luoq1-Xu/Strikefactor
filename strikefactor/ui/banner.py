"""The outcome banner: STRIKEOUT, HOME RUN, WALK-OFF WIN!, typed across the top.

This was the one ``pygame_gui`` widget on screen during play, a ``UILabel``
with the library's typing effect. It is drawn here instead, and it is meant to
be the *same banner*: same font and size, same outline, same place, same
typing rhythm. The constants below are that widget's, measured from frames of
it rather than read off ``theme.json``, which asked for bold italic and never
got it (the theme named only a regular font file, and the library does not
synthesise a style it has no file for).

**The typing rule is the library's, kept exactly.** Time accumulates; when it
reaches ``time_per_letter`` one letter appears and that much is taken back
off. At most one letter per update, so a stall (a modal that paused the game)
resumes the typing where it was instead of dumping the rest of the word.

**Letters appear where they will end up.** The line is laid out for the whole
string and revealed left to right, so nothing slides as it types.

The method names are the ones the widget's owner had (``show_banner``,
``schedule_banner``, ``hide_banner``), because the callers and a dozen test
stubs already speak them.
"""

import pygame

from strikefactor.config import get_path

_FONT_PATH = "ui/font/8bitoperator_jve.ttf"


class OutcomeBanner:
    RECT = pygame.Rect(150, 0, 980, 100)
    FONT_SIZE = 80
    COLOR = (255, 255, 255)
    # A one-pixel outline in this gray, all the way round, which is what makes
    # the letters read as heavier than the bare font.
    OUTLINE_COLOR = (0x77, 0x77, 0x77)
    _OUTLINE_PX = 1
    _SCREEN_MARGIN_PX = 16
    _OUTLINE_OFFSETS = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                             if (dx, dy) != (0, 0))

    def __init__(self, screen):
        self.screen = screen
        # Its own Fonts, not ones from `gameday_theme.load_fonts()`: 80 is not
        # a size any other screen uses.
        self._fonts = {}
        self._font = self._font_at(self.FONT_SIZE)
        self._text = ""
        self._visible = False
        self._time_per_letter = 0.1
        self._letters = 0
        self._acc = 0.0
        self._origin = (0, 0)
        # {'text', 'typing_speed', 'show_time'} or None. `review_modal`
        # pushes `show_time` back by however long a modal paused the game.
        self._pending_banner = None

    def _font_at(self, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(get_path(_FONT_PATH), size)
        return self._fonts[size]

    def _font_fitting(self, text):
        """The banner font, or a smaller one if ``text`` would leave the screen.

        A line wider than RECT simply runs past it, centred: the widget
        clipped at RECT's right edge, which cut "... · OUT ADVANCING" off the
        longest calls. Only a line wider than the screen itself is shrunk.
        """
        limit = self.screen.get_width() - 2 * self._SCREEN_MARGIN_PX
        font = self._font_at(self.FONT_SIZE)
        width = font.size(text)[0]
        if width > limit:
            font = self._font_at(max(8, self.FONT_SIZE * limit // width))
        return font

    # --- control ---

    def show_banner(self, text, typing_speed=0.1):
        """Start typing ``text``, ``typing_speed`` seconds per letter."""
        self._text = text
        self._time_per_letter = typing_speed
        self._letters = 0
        self._acc = 0.0
        self._visible = True
        self._font = self._font_fitting(text)
        width, height = self._font.size(text)
        # The line box is centred in RECT and the glyphs sit one outline
        # width down inside it, as the widget laid them out.
        self._origin = (self.RECT.centerx - width // 2,
                        self.RECT.centery - height // 2 + self._OUTLINE_PX)

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        """Show a banner ``delay`` ms from now, to land on the umpire's call."""
        self._pending_banner = {
            'text': text,
            'typing_speed': typing_speed,
            'show_time': pygame.time.get_ticks() + delay,
        }

    def hide_banner(self):
        """Take the banner down. A scheduled one still arrives."""
        self._visible = False

    # --- per frame ---

    def update(self, time_delta):
        pending = self._pending_banner
        if pending is not None and pygame.time.get_ticks() >= pending['show_time']:
            self._pending_banner = None
            self.show_banner(pending['text'], pending['typing_speed'])
        if self._visible and self._letters < len(self._text):
            self._acc += time_delta
            if self._acc >= self._time_per_letter:
                self._acc -= self._time_per_letter
                self._letters += 1

    def draw(self):
        if not self._visible or self._letters == 0:
            return
        shown = self._text[:self._letters]
        x, y = self._origin
        outline = self._font.render(shown, True, self.OUTLINE_COLOR)
        for dx, dy in self._OUTLINE_OFFSETS:
            self.screen.blit(outline, (x + dx, y + dy))
        self.screen.blit(self._font.render(shown, True, self.COLOR), (x, y))
