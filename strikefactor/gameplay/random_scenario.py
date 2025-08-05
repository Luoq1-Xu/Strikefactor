"""
Random scenario generator for StrikeFactor baseball simulator.
Generates random game situations with different pitchers, counts, runners, and outs.
"""

import random
from typing import Dict, List


class RandomScenarioGenerator:
    """Generates random game scenarios for the baseball simulator."""
    
    def __init__(self):
        self.pitcher_list = ['sale', 'degrom', 'yamamoto', 'sasaki', 'mcclanahan']
        self.scenario_types = [
            'clutch_hitting',      # High pressure situations
            'early_game',          # Early in at-bat scenarios
            'two_strike_battle',   # 2-strike counts
            'full_count',          # 3-2 counts
            'runners_in_scoring',  # Runners on 2nd/3rd
            'bases_loaded',        # Bases loaded scenarios
            'pressure_situation'   # Random high-pressure situations
        ]
        
    def generate_random_scenario(self) -> Dict:
        """Generate a completely random scenario."""
        scenario_type = random.choice(self.scenario_types)
        return self._generate_scenario_by_type(scenario_type)
        
    def _generate_scenario_by_type(self, scenario_type: str) -> Dict:
        """Generate a scenario based on the specified type."""
        pitcher = random.choice(self.pitcher_list)
        
        if scenario_type == 'clutch_hitting':
            return self._generate_clutch_scenario(pitcher)
        elif scenario_type == 'early_game':
            return self._generate_early_game_scenario(pitcher)
        elif scenario_type == 'two_strike_battle':
            return self._generate_two_strike_scenario(pitcher)
        elif scenario_type == 'full_count':
            return self._generate_full_count_scenario(pitcher)
        elif scenario_type == 'runners_in_scoring':
            return self._generate_scoring_position_scenario(pitcher)
        elif scenario_type == 'bases_loaded':
            return self._generate_bases_loaded_scenario(pitcher)
        elif scenario_type == 'pressure_situation':
            return self._generate_pressure_scenario(pitcher)
        else:
            return self._generate_basic_scenario(pitcher)
            
    def _generate_clutch_scenario(self, pitcher: str) -> Dict:
        """Generate a clutch hitting scenario."""
        # High pressure: 2 outs, runners in scoring position
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': 2,
            'runners': self._get_scoring_position_runners(),
            'description': f"Clutch situation! 2 outs with runners in scoring position vs {pitcher.title()}"
        }
        
    def _generate_early_game_scenario(self, pitcher: str) -> Dict:
        """Generate an early at-bat scenario."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 1),
            'runners': self._get_random_runners(max_runners=1),
            'description': f"Early in the at-bat against {pitcher.title()}"
        }
        
    def _generate_two_strike_scenario(self, pitcher: str) -> Dict:
        """Generate a two-strike battle scenario."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 2),
            'runners': self._get_random_runners(),
            'description': f"Two-strike battle! Protect the plate vs {pitcher.title()}"
        }
        
    def _generate_full_count_scenario(self, pitcher: str) -> Dict:
        """Generate a full count scenario."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 2),
            'runners': self._get_random_runners(),
            'description': f"Full count showdown against {pitcher.title()}!"
        }
        
    def _generate_scoring_position_scenario(self, pitcher: str) -> Dict:
        """Generate a scenario with runners in scoring position."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 2),
            'runners': self._get_scoring_position_runners(),
            'description': f"Runners in scoring position vs {pitcher.title()}"
        }
        
    def _generate_bases_loaded_scenario(self, pitcher: str) -> Dict:
        """Generate a bases loaded scenario."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 2),
            'runners': [1, 2, 3],  # All bases loaded
            'description': f"BASES LOADED against {pitcher.title()}!"
        }
        
    def _generate_pressure_scenario(self, pitcher: str) -> Dict:
        """Generate a random high-pressure scenario."""
        scenarios = [
            self._generate_clutch_scenario(pitcher),
            self._generate_full_count_scenario(pitcher),
            self._generate_bases_loaded_scenario(pitcher)
        ]
        return random.choice(scenarios)
        
    def _generate_basic_scenario(self, pitcher: str) -> Dict:
        """Generate a basic random scenario."""
        return {
            'pitcher': pitcher,
            'balls': 0,
            'strikes': 0,
            'outs': random.randint(0, 2),
            'runners': self._get_random_runners(),
            'description': f"Random scenario against {pitcher.title()}"
        }
        
    def _get_random_runners(self, max_runners: int = 3) -> List[int]:
        """Get a random configuration of runners on base."""
        possible_bases = [1, 2, 3]
        num_runners = random.randint(0, min(max_runners, 3))
        
        if num_runners == 0:
            return []
        
        return sorted(random.sample(possible_bases, num_runners))
        
    def _get_scoring_position_runners(self) -> List[int]:
        """Get runners specifically in scoring position (2nd/3rd base)."""
        scoring_bases = [2, 3]
        num_runners = random.randint(1, 2)
        runners = random.sample(scoring_bases, num_runners)
        
        # Sometimes add a runner on first too
        if random.random() < 0.4:
            runners.append(1)
            
        return sorted(runners)
        
    def get_scenario_description(self, scenario: Dict) -> str:
        """Get a formatted description of the scenario."""
        balls = scenario['balls']
        strikes = scenario['strikes']
        outs = scenario['outs']
        runners = scenario['runners']
        pitcher = scenario['pitcher'].title()
        
        base_desc = f"Count: {balls}-{strikes}, {outs} out{'s' if outs != 1 else ''}"
        
        if not runners:
            runner_desc = "Bases empty"
        elif len(runners) == 3:
            runner_desc = "Bases loaded"
        elif set(runners) == {2, 3}:
            runner_desc = "Runners on 2nd and 3rd"
        elif set(runners) == {1, 3}:
            runner_desc = "Runners on 1st and 3rd"
        elif set(runners) == {1, 2}:
            runner_desc = "Runners on 1st and 2nd"
        elif runners == [1]:
            runner_desc = "Runner on 1st"
        elif runners == [2]:
            runner_desc = "Runner on 2nd"
        elif runners == [3]:
            runner_desc = "Runner on 3rd"
        else:
            bases = [f"{base}{'st' if base == 1 else 'nd' if base == 2 else 'rd'}" for base in runners]
            runner_desc = f"Runners on {' and '.join(bases)}"
            
        return f"Facing {pitcher}: {base_desc}, {runner_desc}"