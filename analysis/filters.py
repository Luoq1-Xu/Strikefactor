"""Mode / difficulty / defense / handedness filtering, shared by both analysis scripts."""

from dataclasses import dataclass

MODE_CHOICES = ("arcade", "gameday", "sandbox")
DIFFICULTY_CHOICES = ("rookie", "amateur", "professional", "all_star", "hall_of_fame")

# Defense strength (schema v10). NULL on rows written before the setting
# existed, and those rows are not "league" — they are unknown, and they carry a
# structurally zero error rate because errors did not exist then. So filtering
# on a level deliberately excludes them rather than lumping them in.
DEFENSE_CHOICES = ("sandlot", "minors", "league", "gold_glove")

MODE_LABEL = {"arcade": "Arcade", "gameday": "GameDay", "sandbox": "Sandbox"}
DEFENSE_LABEL = {
    "sandlot": "Sandlot",
    "minors": "Minors",
    "league": "League",
    "gold_glove": "Gold Glove",
}
DIFFICULTY_LABEL = {
    "rookie": "Rookie",
    "amateur": "Amateur",
    "professional": "Professional",
    "all_star": "All-Star",
    "hall_of_fame": "Hall of Fame",
}


@dataclass(frozen=True)
class Filter:
    """A slice of the pitch log. Empty tuple on any axis means 'no filter'."""

    modes: tuple = ()
    difficulties: tuple = ()
    defenses: tuple = ()       # defense_strength values (schema v10)
    hands: tuple = ()          # batter handedness, subset of ("L", "R")
    pitchers: tuple = ()       # pitcher_name values as stored in the DB

    @property
    def label(self):
        m = ", ".join(MODE_LABEL[x] for x in self.modes) if self.modes else "All modes"
        d = (", ".join(DIFFICULTY_LABEL[x] for x in self.difficulties)
             if self.difficulties else "All difficulties")
        h = ", ".join(f"{x}HB" for x in self.hands) if self.hands else "Both hands"
        parts = [m, d, h]
        if self.defenses:
            parts.append(", ".join(DEFENSE_LABEL[x] for x in self.defenses) + " defense")
        if self.pitchers:
            from .theme import pitcher_display
            parts.append(", ".join(pitcher_display(p) for p in self.pitchers))
        return " · ".join(parts)

    @property
    def slug(self):
        """Filesystem-safe key — one output subfolder per filter slice."""
        parts = (list(self.modes) + list(self.difficulties)
                 + [f"def_{x}" for x in self.defenses]
                 + [f"{x}HB" for x in self.hands] + list(self.pitchers))
        return "__".join(parts) if parts else "all"

    @property
    def is_empty(self):
        return not (self.modes or self.difficulties or self.defenses
                    or self.hands or self.pitchers)

    def replace(self, **kw):
        from dataclasses import replace
        return replace(self, **kw)

    def apply(self, df):
        """Return the subset of a pitches DataFrame matching this filter."""
        mask = None

        def _and(m):
            nonlocal mask
            mask = m if mask is None else (mask & m)

        if self.modes:
            _and(df["game_mode"].isin(self.modes))
        if self.difficulties:
            _and(df["difficulty"].isin(self.difficulties))
        if self.defenses:
            _and(df["defense_strength"].isin(self.defenses))
        if self.hands:
            _and(df["batter_hand"].isin(self.hands))
        if self.pitchers:
            _and(df["pitcher_name"].isin(self.pitchers))
        return df if mask is None else df[mask]


# Accepts short aliases on the CLI so you don't have to type "shanemcclanahan".
PITCHER_ALIASES = {
    "sale": "chrissale",
    "degrom": "jacobdegrom",
    "mcclanahan": "shanemcclanahan",
    "sasaki": "rokisasaki",
    "yamamoto": "Yamamoto",
}


def resolve_pitcher(token):
    """Map a CLI token to the pitcher_name stored in the DB."""
    key = token.strip().lower()
    if key in PITCHER_ALIASES:
        return PITCHER_ALIASES[key]
    return token.strip()


def add_filter_args(parser):
    """Attach the shared --mode/--difficulty/--handedness/--pitcher options."""
    parser.add_argument(
        "--mode", choices=list(MODE_CHOICES) + ["all"], default="gameday",
        help="Game mode to include (default: gameday). 'all' = no mode filter.")
    parser.add_argument(
        "--difficulty", choices=list(DIFFICULTY_CHOICES) + ["all"],
        default="hall_of_fame",
        help="Difficulty to include (default: hall_of_fame). 'all' = no filter.")
    parser.add_argument(
        "--defense", choices=list(DEFENSE_CHOICES) + ["all"], default="all",
        help="Defense strength to include (default: all). Rows recorded before "
             "the setting existed have this NULL and are excluded by any "
             "concrete choice.")
    parser.add_argument(
        "--handedness", choices=["L", "R", "all"], default="all",
        help="Batter handedness (default: all). Split L/R to avoid smearing "
             "inside/outside in location plots.")
    parser.add_argument(
        "--pitcher", default=None,
        help="Limit to one pitcher (accepts sale/degrom/mcclanahan/sasaki/yamamoto).")
    return parser


def filter_from_args(args):
    pitchers = ()
    if getattr(args, "pitcher", None):
        pitchers = (resolve_pitcher(args.pitcher),)
    return Filter(
        modes=() if args.mode == "all" else (args.mode,),
        difficulties=() if args.difficulty == "all" else (args.difficulty,),
        defenses=() if getattr(args, "defense", "all") == "all" else (args.defense,),
        hands=() if args.handedness == "all" else (args.handedness,),
        pitchers=pitchers,
    )
