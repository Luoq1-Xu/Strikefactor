"""Baserunning and scoring for a half-inning: `Runner` and `ScoreKeeper`.

The `ScoreKeeper` is also the half-inning's official scorer. Besides who is on
base and how many runs are in, it rules on three things the Official Baseball
Rules settle per play, and that used to be approximated downstream:

  * **Is the run earned** (Rule 9.16). Every run was charged as earned, so a
    two-out error followed by a home run put two earned runs on a pitcher who
    should have been in the dugout. The rule is a reconstruction — the inning
    as it would have gone had every fielding chance been taken — and that is
    kept here as a second position on every runner (`Runner.clean_base`) and a
    count of the outs the defense should have had (`missed_outs`).
  * **Whose run it is** (Rule 9.16(g)). A run belongs to the pitcher who put
    the runner on, not to whoever is on the mound when he scores.
  * **What the batter is credited with** (Rules 9.04, 9.08(d)): runs batted
    in, and whether a fly ball was a sacrifice and so no at-bat.

The reconstruction moves runners with the same rules the real inning uses
(`_out_advance`, the forced chain of a walk) rather than a second copy of
them. It can therefore never have a runner further along than he really is,
and an earned run can never outnumber the runs.

Outs are passed in, not counted: `Game.currentouts` and
`GameDayManager.current_outs` already count them, a strikeout never comes
through here, and a scenario can open the half-inning with two down.
"""

import copy
import random
from typing import NamedTuple

from strikefactor import outcomes


class Play(NamedTuple):
    """What the scorer writes down against the batter for one plate appearance."""

    runs: int = 0                 # runners who crossed the plate on it
    rbi: int = 0                  # of those, the batter's (Rule 9.04)
    sacrifice_fly: bool = False   # Rule 9.08(d): no at-bat is charged


def _out_advance(outcome, base):
    """Bases a runner standing on `base` moves up when the batter makes this out.

    The one statement of it. The real inning and the reconstructed one both
    read it, and so does the run batted in on an error: all three are the same
    question — what does this out do to that runner.
    """
    if outcome == outcomes.GROUNDOUT:
        return 1
    if outcome == outcomes.FLYOUT:
        return 1 if base in (2, 3) else 0
    return 0


def _forced(by_base):
    """The runners a walk pushes along: the unbroken chain up from first."""
    chain, base = [], 1
    while base in by_base:
        chain.append(by_base[base])
        base += 1
    return chain


# Runner class
class Runner:

    # 0 = Home plate, 1 = First base, 2 = Second base, 3 = Third base
    onBase = False
    base = 0

    def __init__(self, hit_type, pitcher=None, reached_on_error=False):
        self.base = hit_type
        if hit_type == 4:
            self.onBase = False
            self.scored = True
        else:
            self.onBase = True
            self.scored = False
        self.speed = random.randint(1, 3)
        # Who put him on, and so who is charged if he scores (Rule 9.16(g)).
        self.pitcher = pitcher
        # Where he would be standing had every fielding chance been taken.
        # None for a batter who reached on the error itself: errorless play
        # retires him, so no reconstruction can bring him home (9.16(b)).
        self.clean_base = None if reached_on_error else hit_type

    def walk(self):
        self.base += 1
        if self.base > 3:
            self.scored = True
            self.onBase = False

    def advance(self, hit):
        self.base += hit
        if self.base > 3:
            self.scored = True
            self.onBase = False

# Scorekeeper class
class ScoreKeeper:

    def __init__(self):
        self.reset()

    def reset(self):
        self.runners = []
        self.bases = ['white', 'white', 'white']
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        self.score = 0
        # Runs the reconstruction has also brought home. Never more than
        # `score`, and it can trail it for a few batters: see `_settle`.
        self.earned = 0
        # Who the next batter is charged to. None when nobody has said, which
        # is one unnamed pitcher for the whole half-inning.
        self.pitcher = None
        # Errors that should have been outs this half-inning (Rule 9.16(a)).
        self.missed_outs = 0
        # pitcher -> `missed_outs` when he came in. Rule 9.16(i): a reliever
        # gets no benefit from chances that were missed before he arrived.
        self._entered_at = {}
        # Runners who are home in fact and still on base in the
        # reconstruction. Their runs are unearned until it catches up.
        self._home_early = []
        # pitcher -> [runs, earned], charged and not yet collected.
        self._charges = {}
        self.last_play = Play()

    def restore_from(self, other):
        """Become a copy of `other`, in place.

        One deep copy of the whole state, so the same `Runner` stays the same
        object in `runners`, `basesfilled` and `_home_early`. Copying the
        fields one at a time is how a new field gets left behind.
        """
        self.__dict__.update(copy.deepcopy(other.__dict__))

    def set_pitcher(self, pitcher):
        """Name who is pitching to the batters from here on."""
        if pitcher != self.pitcher:
            self.pitcher = pitcher
            self._entered_at[pitcher] = self.missed_outs

    def _rebuild_base_state(self):
        self.basesfilled = {1: 0, 2: 0, 3: 0}
        basesFilled = ['white', 'white', 'white']
        surviving_runners = []
        for runner in self.runners:
            if runner.scored:
                continue
            if 1 <= runner.base <= 3:
                self.basesfilled[runner.base] = runner
                basesFilled[runner.base - 1] = 'yellow'
                surviving_runners.append(runner)
        self.runners = surviving_runners
        self.bases = basesFilled
        return basesFilled

    def _reconstructed(self):
        """Everyone on base in the errorless inning, home in fact or not."""
        return [r for r in self._home_early + self.runners
                if r.clean_base is not None]

    def _clean_outs(self, pitcher, outs):
        """Outs `pitcher` should have, counting the chances his defense missed."""
        return outs + self.missed_outs - self._entered_at.get(pitcher, 0)

    def _settle(self, outs_after):
        """Count the runs this play scored, and rule on each one. Returns the count.

        A run is charged to the pitcher who put the runner on. It is earned
        when the reconstruction brings that runner home too, before the third
        out that pitcher should have had (Rule 9.16(a)).

        The two can happen on different plays. A runner an error moved up can
        score before the errorless inning would have scored him, and whether
        he would have got home anyway depends on what the next batters do
        (Rule 9.16(d)). He waits in `_home_early`, and his run counts as
        unearned unless the reconstruction scores him before the half-inning
        ends. So `earned` can rise on a play that scored nobody.
        """
        home = [r for r in self._reconstructed()
                if r.scored and r.clean_base > 3]
        scored = [r for r in self.runners if r.scored]
        for runner in scored:
            self.runners.remove(runner)
            self.score += 1
            self._charges.setdefault(runner.pitcher, [0, 0])[0] += 1
            if runner.clean_base is not None and runner not in home:
                self._home_early.append(runner)
        for runner in home:
            if runner in self._home_early:
                self._home_early.remove(runner)
            if self._clean_outs(runner.pitcher, outs_after) < 3:
                self.earned += 1
                self._charges.setdefault(runner.pitcher, [0, 0])[1] += 1
        return len(scored)

    # Takes in hit_type, then returns tuple of (bases, score)
    def update_hit_event(self, hit_type, bases=1, outs=0, clean_outcome=None):
        """Apply a batted ball. Returns `(bases, runs)`; the scoring is `last_play`.

        `outs` is how many were out before the play. An out that makes three
        advances nobody, in fact or in the reconstruction.

        `bases` and `clean_outcome` describe a REACHED ON ERROR and are
        ignored otherwise. `bases` is how far the batter got. `clean_outcome`
        is the out the play would have been (`HitAnimation.error_out`), which
        is where the runners stand in the reconstruction. Left as None, they
        hold: Rule 9.16(f) gives the pitcher the benefit of the doubt.
        """
        # The inverse of outcomes.HIT_BASES, derived rather than restated so
        # the two cannot disagree about what a three-base hit is called.
        hit_map = {n: o for o, n in outcomes.HIT_BASES.items()}
        outcome = (hit_type if isinstance(hit_type, str)
                   else hit_map.get(hit_type, outcomes.SINGLE))
        is_out = outcome in outcomes.BATTED_OUT_OUTCOMES
        is_error = outcome == outcomes.REACHED_ON_ERROR

        on_base = self.runners[:]
        reconstructed = self._reconstructed()
        # Third outs. The reconstruction's can come sooner than the real one,
        # and it is taken off the current pitcher's count, the last to reach
        # three; `_settle` holds every other pitcher to his own.
        third_out = is_out and outs >= 2
        clean_third_out = self._clean_outs(self.pitcher, outs) >= 2
        rbi = None

        if outcome in outcomes.HIT_OUTCOMES:
            advance = outcomes.HIT_BASES[outcome]
            self.runners.append(Runner(advance, self.pitcher))
            for runner in on_base:
                runner.advance(advance)
            for runner in reconstructed:
                runner.clean_base += advance
        elif is_out:
            if not third_out:
                for runner in on_base:
                    runner.advance(_out_advance(outcome, runner.base))
            if not clean_third_out:
                for runner in reconstructed:
                    runner.clean_base += _out_advance(outcome, runner.clean_base)
        elif is_error:
            # The batter reached; nobody is out. Written explicitly rather
            # than left to the fallback below, which happened to do the right
            # thing for one base — an outcome quietly relying on a fallback
            # is the silent-miscount shape tests/test_outcome_names.py exists
            # to prevent, and it could not express a two-base error at all.
            advance = max(1, min(3, bases))
            # Rule 9.04(a)(3): the batter drives in only the run that would
            # have scored on the out, and only with fewer than two down —
            # with two down the out ends the inning instead.
            rbi = 0 if outs >= 2 else sum(
                1 for r in on_base
                if r.base + _out_advance(clean_outcome, r.base) > 3)
            self.runners.append(
                Runner(advance, self.pitcher, reached_on_error=True))
            for runner in on_base:
                runner.advance(advance)
            # In the reconstruction this was an out.
            self.missed_outs += 1
            if not clean_third_out:
                for runner in reconstructed:
                    runner.clean_base += _out_advance(clean_outcome,
                                                      runner.clean_base)
        else:
            self.runners.append(Runner(1, self.pitcher))
            for runner in on_base:
                runner.advance(1)
            for runner in reconstructed:
                runner.clean_base += 1

        scored = self._settle(outs + (1 if is_out else 0))
        if rbi is None:
            rbi = scored
        # Rule 9.08(d): a fly ball that scores a runner with fewer than two
        # out, caught or dropped. The third out scores nobody, so `scored`
        # already carries the outs condition.
        sacrifice_fly = ((outcome == outcomes.FLYOUT and scored > 0)
                         or (is_error and clean_outcome == outcomes.FLYOUT
                             and rbi > 0))
        self.last_play = Play(scored, rbi, sacrifice_fly)

        basesFilled = self._rebuild_base_state()
        return (basesFilled, scored)

    def update_walk_event(self, outs=0):
        """Put the batter on first and push along whoever that forces.

        The reconstruction forces its own chain off its own bases. They can
        differ from the real ones: a runner an error moved to second is not
        forced by a walk, but he is in the inning where he is still on first.
        """
        for runner in _forced({r.clean_base: r for r in self._reconstructed()}):
            runner.clean_base += 1
        for runner in _forced({r.base: r for r in self.runners}):
            runner.walk()
        self.runners.append(Runner(1, self.pitcher))
        scored = self._settle(outs)
        self.last_play = Play(scored, scored)
        self._rebuild_base_state()

    def take_charges(self):
        """Runs charged since the last call, as `(pitcher, runs, earned)`.

        `earned` can be charged with no run beside it: a run the
        reconstruction only now brought home (see `_settle`).
        """
        charges = [(pitcher, runs, earned)
                   for pitcher, (runs, earned) in self._charges.items()]
        self._charges = {}
        return charges

    def get_bases(self):
        return self.bases

    def isRunnerOnBase(self, base):
        return self.basesfilled[base] != 0

    def get_score(self):
        return self.score

    def get_earned_runs(self):
        return self.earned

    def get_runners_on_base(self):
        return len(self.runners)
