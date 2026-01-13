from .pitcher import Pitcher
from utils.physics import calculate_travel_time
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
                         7.0)  # arm_extension in feet
        self.load_img(loadfunc, 'assets/images/mcclanahan/', 17)
        self.add_pitch_type(self.CB, "CB")
        self.add_pitch_type(self.SLD, "SLD")
        self.add_pitch_type(self.CH, "CH")
        self.add_pitch_type(self.FFI, "FFI")
        self.add_pitch_type(self.FFU, "FFU")
        #self.add_pitch_type(self.CHI, "CHI")
        #self.add_pitch_type(self.CBO, "CBO")
        #self.add_pitch_type(self.FFO, "FFO")

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
            sampley = random.uniform(-25,20)
            samplex = random.uniform(-25,10)
            speed_mph = 97.0
            travel_time = calculate_travel_time(speed_mph, self.arm_extension)
            simulation_func(self.release_point, 'shanemcclanahan', 0.015, 0.010, samplex, sampley, travel_time, 'FF')

    def FFI(self, simulation_func):
        sampley = random.uniform(-15,15)
        samplex = random.uniform(-30,-35)
        speed_mph = 97.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        simulation_func(self.release_point, 'shanemcclanahan', 0.005, 0.010, samplex, sampley, travel_time, 'FF')

    def FFO(self, simulation_func):
        sampley = random.uniform(10,25)
        samplex = random.uniform(8,10)
        speed_mph = 97.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        simulation_func(self.release_point, 'shanemcclanahan', 0.005, 0.010, samplex, sampley, travel_time, 'FF')

    def SLD(self, simulation_func):
            sampley = random.uniform(-10, 15)
            samplex = random.uniform(-25,15)
            speed_mph = 83.0
            travel_time = calculate_travel_time(speed_mph, self.arm_extension)
            simulation_func(self.release_point, 'shanemcclanahan', -0.01, 0.0350, samplex, sampley, travel_time, 'SL')

    def CHD(self, main_simulation):
        sampley = random.uniform(-5,15)
        samplex = random.uniform(-20,10)
        speed_mph = 87.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        main_simulation(self.release_point, 'shanemcclanahan', 0.015, 0.0275, samplex, sampley, travel_time, 'CH')

    def CB(self, simulation_func):
            sampley = random.uniform(-25, 5)
            samplex = random.uniform(-25,15)
            speed_mph = 78.0
            travel_time = calculate_travel_time(speed_mph, self.arm_extension)
            simulation_func(self.release_point, 'shanemcclanahan', -0.01, 0.0450, samplex, sampley, travel_time, 'CB')

    def CBO(self, simulation_func):
            sampley = random.uniform(-20, 5)
            samplex = random.uniform(10,15)
            speed_mph = 78.0
            travel_time = calculate_travel_time(speed_mph, self.arm_extension)
            simulation_func(self.release_point, 'shanemcclanahan', -0.01, 0.0450, samplex, sampley, travel_time, 'CB')

    def CH(self, simulation_func):
        sampley = random.uniform(-10, 20)
        samplex = random.uniform(-45, 0)
        speed_mph = 87.0
        travel_time = calculate_travel_time(speed_mph, self.arm_extension)
        simulation_func(self.release_point, 'shanemcclanahan', 0.015, 0.0275, samplex, sampley, travel_time, 'CH')