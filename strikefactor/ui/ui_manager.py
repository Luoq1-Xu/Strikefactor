"""What is left of the widget manager: a handle on the outcome banner.

Every screen draws and handles its own buttons (ui/widgets.py), so nothing
here creates, shows or routes a widget. The class survives one more commit
only so that step can be a pure rename of ``game.ui_manager``.
"""

from strikefactor.ui.banner import OutcomeBanner


class UIManager:
    def __init__(self, screen):
        self.screen = screen
        self.banner = OutcomeBanner(screen)

    def show_banner(self, text, typing_speed=0.1):
        self.banner.show_banner(text, typing_speed)

    def schedule_banner(self, text, delay=450, typing_speed=0.1):
        self.banner.schedule_banner(text, delay, typing_speed)

    def hide_banner(self):
        self.banner.hide_banner()

    @property
    def _pending_banner(self):
        return self.banner._pending_banner

    @_pending_banner.setter
    def _pending_banner(self, value):
        self.banner._pending_banner = value

    def update(self, time_delta):
        self.banner.update(time_delta)

    def draw(self):
        self.banner.draw()
