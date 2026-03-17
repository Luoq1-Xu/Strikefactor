from .pitcher import Pitcher
import random
import pygame


class Mcclanahan(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) + 28, (screen.get_height() / 3) + 193),
                         screen,
                         'Shane Mcclanahan',
                         1200,
                         7.0,
                         command=0.72)
        self.load_img(loadfunc, 'assets/images/mcclanahan/', 17)
        self.add_pitch_type(self.CB, "CB")
        self.add_pitch_type(self.SLD, "SLD")
        self.add_pitch_type(self.CH, "CH")
        self.add_pitch_type(self.FFI, "FFI")
        self.add_pitch_type(self.FFU, "FFU")

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 200:
            self.draw(self.screen, 1)
        elif current_time > start_time + 200 and current_time <= start_time + 300:
            self.draw(self.screen, 2, 14, 0)
        elif current_time > start_time + 300 and current_time <= start_time + 400:
            self.draw(self.screen, 3, 14, 0)
        elif current_time > start_time + 400 and current_time <= start_time + 500:
            self.draw(self.screen, 4, 15, 1)
        elif current_time > start_time + 500 and current_time <= start_time + 750:
            self.draw(self.screen, 5, 16, 2)
        elif current_time > start_time + 750 and current_time <= start_time + 850:
            self.draw(self.screen, 6, 16, 5)
        elif current_time > start_time + 850 and current_time <= start_time + 1000:
            self.draw(self.screen, 7, 14, 8)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 8, 11, 20)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 9, 6, 24)
        elif current_time > start_time + 1100 and current_time <= start_time + 1140:
            self.draw(self.screen, 10, 5, 19)
        elif current_time > start_time + 1140 and current_time <= start_time + 1180:
            self.draw(self.screen, 11, 0, 20)
        elif current_time > start_time + 1180 and current_time <= start_time + 1200:
            self.draw(self.screen, 12, 0, 24)
        elif current_time > start_time + 1200 and current_time <= start_time + 1220:
            self.draw(self.screen, 13, 2, 15)
        elif current_time > start_time + 1220 and current_time <= start_time + 1240:
            self.draw(self.screen, 14, 3, 30)
        elif current_time > start_time + 1240 and current_time <= start_time + 1280:
            self.draw(self.screen, 15, 3, 28)
        elif current_time > start_time + 1280 and current_time <= start_time + 1320:
            self.draw(self.screen, 16, -8, 28)
        elif current_time > start_time + 1320:
            self.draw(self.screen, 17, -3, 25)

    def FFU(self, simulation_func):
        speed_mph = random.gauss(97.0, 0.5)
        pfx_x = random.gauss(-12.0, 1.0)
        pfx_z = random.gauss(16.0, 1.0)
        target_x, target_y = self.get_pitch_target('FF')
        simulation_func(self.release_point, 'shanemcclanahan', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FF')

    def FFI(self, simulation_func):
        speed_mph = random.gauss(97.0, 0.5)
        pfx_x = random.gauss(-12.0, 1.0)
        pfx_z = random.gauss(16.0, 1.0)
        target_x, target_y = self.get_pitch_target('FF')
        simulation_func(self.release_point, 'shanemcclanahan', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FF')

    def SLD(self, simulation_func):
        speed_mph = random.gauss(83.0, 1.0)
        pfx_x = random.gauss(3.0, 0.5)
        pfx_z = random.gauss(0.0, 0.5)
        target_x, target_y = self.get_pitch_target('SLD')
        simulation_func(self.release_point, 'shanemcclanahan', speed_mph, pfx_x, pfx_z, target_x, target_y, 'SL')

    def CB(self, simulation_func):
        speed_mph = random.gauss(78.0, 1.0)
        pfx_x = random.gauss(6.0, 1.0)
        pfx_z = random.gauss(-12.0, 1.0)
        target_x, target_y = self.get_pitch_target('CB')
        simulation_func(self.release_point, 'shanemcclanahan', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CB')

    def CH(self, simulation_func):
        speed_mph = random.gauss(87.0, 0.5)
        pfx_x = random.gauss(-16.0, 1.0)
        pfx_z = random.gauss(8.0, 1.0)
        target_x, target_y = self.get_pitch_target('CH')
        simulation_func(self.release_point, 'shanemcclanahan', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CH')
