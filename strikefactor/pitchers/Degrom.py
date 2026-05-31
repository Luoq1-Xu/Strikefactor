from .pitcher import Pitcher
import random
import pygame


class Degrom(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 45, (screen.get_height() / 3) + 187),
                         screen,
                         'Jacob deGrom',
                         1100,
                         6.7,
                         command=0.82)
        self.load_img(loadfunc, 'assets/images/degrom/RIGHTY', 9)
        self.add_pitch_type(self.CB, "CB")
        self.add_pitch_type(self.FF, "FF")
        self.add_pitch_type(self.SL, "SL")
        self.add_pitch_type(self.CH, "CH")

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 300:
            self.draw(self.screen, 1)
        elif current_time > start_time + 300 and current_time <= start_time + 500:
            self.draw(self.screen, 2, -10, 0)
        elif current_time > start_time + 500 and current_time <= start_time + 700:
            self.draw(self.screen, 3, -13, 0)
        elif current_time > start_time + 700 and current_time <= start_time + 900:
            self.draw(self.screen, 4, -27, 5)
        elif current_time > start_time + 900 and current_time <= start_time + 1000:
            self.draw(self.screen, 5, -33, 12)
        elif current_time > start_time + 1000 and current_time <= start_time + 1100:
            self.draw(self.screen, 6, 12, 13)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 7, -20, 7)
        elif current_time > start_time + 1110 and current_time <= start_time + 1140:
            self.draw(self.screen, 8, 0, 27)
        elif current_time > start_time + 1140:
            self.draw(self.screen, 9, -11, 25)

    def CB(self, simulation_func):
        speed_mph = random.gauss(81.0, 1.0)
        pfx_x = random.gauss(-6.0, 1.0)
        pfx_z = random.gauss(-10.0, 1.0)
        target_x, target_y = self.get_pitch_target('CB')
        simulation_func(self.release_point, 'jacobdegrom', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CB')

    def FF(self, simulation_func):
        speed_mph = random.gauss(100.0, 1.0)
        pfx_x = random.gauss(8.0, 1.0)
        pfx_z = random.gauss(16.0, 1.0)
        target_x, target_y = self.get_pitch_target('FF')
        simulation_func(self.release_point, 'jacobdegrom', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FF')

    def SL(self, simulation_func):
        speed_mph = random.gauss(91.0, 1.0)
        pfx_x = random.gauss(-2.0, 0.5)
        pfx_z = random.gauss(1.0, 0.5)
        target_x, target_y = self.get_pitch_target('SL')
        simulation_func(self.release_point, 'jacobdegrom', speed_mph, pfx_x, pfx_z, target_x, target_y, 'SL')

    def CH(self, simulation_func):
        speed_mph = random.gauss(89.0, 1.5)
        pfx_x = random.gauss(13.0, 1.0)
        pfx_z = random.gauss(8.0, 1.0)
        target_x, target_y = self.get_pitch_target('CH')
        simulation_func(self.release_point, 'jacobdegrom', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CH')
