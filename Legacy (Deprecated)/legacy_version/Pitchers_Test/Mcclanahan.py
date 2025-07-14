from helper import pitcher
import random
import pygame

class Mcclanahan(pitcher.Pitcher):

    def __init__(self, screen, loadfunc) -> None:
        super().__init__((screen.get_width() / 2) - 30,
                         (screen.get_height() / 3) + 175,
                         pygame.Vector2((screen.get_width() / 2) + 28, (screen.get_height() / 3) + 193),
                         screen,
                         'Shane Mcclanahan', 
                         1200)
        self.load_img(loadfunc, 'Mcclanahan Test/', 17)
        self.add_pitch_type(self.CB, "CB")
        self.add_pitch_type(self.SLD, "FFU")
        self.add_pitch_type(self.CHD, "CHD")
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
            sampley = random.uniform(-25,15)
            samplex = random.uniform(-25,10)
            simulation_func(self.release_point, 'shanemcclanahan', 0.015, 0.010, samplex, sampley, 375, 'FF')

    def FFI(self, simulation_func):
            sampley = random.uniform(-15,0)
            samplex = random.uniform(-45,0)
            simulation_func(self.release_point, 'shanemcclanahan', 0.005, 0.010, samplex, sampley, 375, 'FF')

    def SLD(self, simulation_func):
            sampley = random.uniform(-10, 15)
            samplex = random.uniform(-25,15)
            simulation_func(self.release_point, 'shanemcclanahan', -0.01, 0.0350, samplex, sampley, 440, 'SL')

    def CHD(self, main_simulation):
        sampley = random.uniform(-5,15)
        samplex = random.uniform(-20,10)
        main_simulation(self.release_point, 'shanemcclanahan', 0.015, 0.0275, samplex, sampley, 420, 'CH')

    def CB(self, simulation_func):
            sampley = random.uniform(-25, 5)
            samplex = random.uniform(-25,15)
            simulation_func(self.release_point, 'shanemcclanahan', -0.01, 0.0450, samplex, sampley, 470, 'CB')

