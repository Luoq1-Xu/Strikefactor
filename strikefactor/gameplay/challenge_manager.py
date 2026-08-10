from strikefactor.config import CHALLENGES_PER_SIDE


class ChallengeManager:
    """Tracks remaining ABS challenges per side.

    MLB rule: each team gets a fixed number of challenges per game and
    retains the challenge if it succeeds.
    """

    def __init__(self, per_side: int = CHALLENGES_PER_SIDE,
                 sides: tuple = ("home", "away")):
        self._per_side = per_side
        self._sides = sides
        self._remaining = {side: per_side for side in sides}
        self._unlimited = False

    def set_unlimited(self, unlimited: bool) -> None:
        """When True (e.g. sandbox mode), challenges are never consumed."""
        self._unlimited = bool(unlimited)

    def is_unlimited(self) -> bool:
        return self._unlimited

    def remaining(self, side: str) -> int:
        if self._unlimited:
            return self._per_side
        return self._remaining.get(side, 0)

    def can_challenge(self, side: str) -> bool:
        if self._unlimited:
            return True
        return self.remaining(side) > 0

    def consume(self, side: str, successful: bool) -> None:
        if self._unlimited or successful:
            return
        if side in self._remaining and self._remaining[side] > 0:
            self._remaining[side] -= 1

    def reset_all(self) -> None:
        for side in self._remaining:
            self._remaining[side] = self._per_side

    @property
    def per_side(self) -> int:
        return self._per_side
