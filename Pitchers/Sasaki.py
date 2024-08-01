from helper import pitcher
import random
import pygame

class Sasaki(pitcher.Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 180,
                         pygame.Vector2((screen.get_width() / 2) - 42, (screen.get_height() / 3) + 164),
                         screen,
                         'Roki Sasaki')
        self.load_img(loadfunc, 'Sasaki/', 14)
        self.add_pitch_type(self.sasakiSplitter, "FS")

    def sasakiSplitter(self, main_simulation):
        sampley = random.uniform(-5,20)
        samplex = random.uniform(-10,20)
        horizontalBreak = random.uniform(-0.01, 0.01)
        main_simulation(self.release_point, 'rokisasaki', horizontalBreak, 0.05, samplex, sampley, 450, 'FS')

    def draw_pitcher(self, start_time, current_time):
        if current_time == 0 and start_time == 0:
            self.draw(self.screen, 1)
        if current_time <= start_time + 250:
            self.draw(self.screen, 1)
        elif current_time > start_time + 250 and current_time <= start_time + 350:
            self.draw(self.screen, 2, -4, -4)
        elif current_time > start_time + 350 and current_time <= start_time + 400:
            self.draw(self.screen, 3, -37, -4)
        elif current_time > start_time + 400 and current_time <= start_time + 550:
            self.draw(self.screen, 4, -31, -4)
        elif current_time > start_time + 550 and current_time <= start_time + 700:
            self.draw(self.screen, 5, -6, -5)
        elif current_time > start_time + 700 and current_time <= start_time + 800:
            self.draw(self.screen, 6, 0, -5)
        elif current_time > start_time + 800 and current_time <= start_time + 900:
            self.draw(self.screen, 7, -17, -3)
        elif current_time > start_time + 900 and current_time <= start_time + 975:
            self.draw(self.screen, 8, -24, 4)
        elif current_time > start_time + 975 and current_time <= start_time + 1000:
            self.draw(self.screen, 9, -5, 4)
        elif current_time > start_time + 1000 and current_time <= start_time + 1050:
            self.draw(self.screen, 10, 14, -3)
        elif current_time > start_time + 1050 and current_time <= start_time + 1100:
            self.draw(self.screen, 11, 2, -5)
        elif current_time > start_time + 1100 and current_time <= start_time + 1110:
            self.draw(self.screen, 12, -14, -15)
        elif current_time > start_time + 1110 and current_time <= start_time + 1120:
            self.draw(self.screen, 13, 5, 12)
        elif current_time > start_time + 1120:
            self.draw(self.screen, 14, -9, 12)

    def sasakiSplitter(self, main_simulation):
        sampley = random.uniform(-5,20)
        samplex = random.uniform(-10,20)
        horizontalBreak = random.uniform(-0.01, 0.01)
        main_simulation(self.release_point, 'rokisasaki', horizontalBreak, 0.05, samplex, sampley, 450, 'FS')
    def sasakiFastball(self, main_simulation):
        sampley = random.uniform(-5,15)
        samplex = random.uniform(-10,20)
        main_simulation(self.release_point, 'rokisasaki', -0.015, 0.01, samplex, sampley, 370, 'FF')
    def sasakiLowFastball(self, main_simulation):
        sampley = random.uniform(20,35)
        samplex = random.uniform(0,45)
        main_simulation(self.release_point, 'rokisasaki', -0.02, 0.015, samplex, sampley, 370, 'FF')
    def sasakiFastball2(self, main_simulation):
        sampley = random.uniform(-5,5)
        samplex = random.uniform(0, 15)
        main_simulation(self.release_point, 'rokisasaki', -0.005, 0.055, samplex, sampley, 370, 'FF')
    def sasakiFastball3(self, main_simulation):
        sampley = random.uniform(-5,5)
        samplex = random.uniform(-25, 25)
        ivb = random.uniform(0.005, 0.095)
        ihb = random.uniform(-0.005, 0.005)
        main_simulation(self.release_point, 'rokisasaki', ihb, ivb, (ihb*50), (ivb*5), 380, 'SI')



