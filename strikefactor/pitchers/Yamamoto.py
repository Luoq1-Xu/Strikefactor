from .pitcher import Pitcher
import random
import pygame


class Yamamoto(Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) - 52, (screen.get_height() / 3) + 183),
                         screen,
                         'Yoshinobu Yamamoto',
                         1100,
                         6.5,
                         command=0.75)
        self.load_img(loadfunc, 'assets/images/yamamoto/', 14)
        self.add_pitch_type(self.FB, "FF")
        self.add_pitch_type(self.yamamotoSplitter, "FS")
        self.add_pitch_type(self.yamamotoCurve, "CB")

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 250:
            self.draw(self.screen, 1)
        elif current_time > start_time + 250 and current_time <= start_time + 350:
            self.draw(self.screen, 2, -6, 0)
        elif current_time > start_time + 350 and current_time <= start_time + 400:
            self.draw(self.screen, 3, -6, 0)
        elif current_time > start_time + 400 and current_time <= start_time + 550:
            self.draw(self.screen, 4, -13, -1)
        elif current_time > start_time + 550 and current_time <= start_time + 700:
            self.draw(self.screen, 5, -20, 1)
        elif current_time > start_time + 700 and current_time <= start_time + 800:
            self.draw(self.screen, 6, -26, 2)
        elif current_time > start_time + 800 and current_time <= start_time + 900:
            self.draw(self.screen, 7, -11, 3)
        elif current_time > start_time + 900 and current_time <= start_time + 975:
            self.draw(self.screen, 8, -3, 4)
        elif current_time > start_time + 975 and current_time <= start_time + 1000:
            self.draw(self.screen, 9, 8, 4)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 10, 5, 4)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 11, -8, 11)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 12, -24, 1)
        elif current_time > start_time + 1110 and current_time <= start_time + 1120:
            self.draw(self.screen, 13, 5, 12)
        elif current_time > start_time + 1120:
            self.draw(self.screen, 14, -33, 19)

    def FB(self, simulation_func):
        speed_mph = random.gauss(96.0, 1.0)
        pfx_x = random.gauss(6.0, 1.0)
        pfx_z = random.gauss(14.0, 1.0)
        target_x, target_y = self.get_pitch_target('FF')
        simulation_func(self.release_point, 'Yamamoto', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FF')

    def yamamotoCurve(self, simulation_func):
        speed_mph = random.gauss(73.0, 1.0)
        pfx_x = random.gauss(-5.0, 1.0)
        pfx_z = random.gauss(-12.0, 1.0)
        target_x, target_y = self.get_pitch_target('CB')
        simulation_func(self.release_point, 'Yamamoto', speed_mph, pfx_x, pfx_z, target_x, target_y, 'CB')

    def yamamotoSplitter(self, simulation_func):
        speed_mph = random.gauss(89.0, 1.0)
        pfx_x = random.gauss(10.0, 2.0)
        pfx_z = random.gauss(2.0, 1.0)
        target_x, target_y = self.get_pitch_target('FS')
        simulation_func(self.release_point, 'Yamamoto', speed_mph, pfx_x, pfx_z, target_x, target_y, 'FS')
