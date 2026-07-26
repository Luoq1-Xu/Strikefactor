"""Named pitch-location archetypes, loaded from data/pitch_locations.json.

An archetype is one recognisable way a pitch gets used — a back-foot slider,
a backdoor slider and a get-me-over slider are the same pitch aimed at three
completely different places. Before this, location was "pick a random zone
edge", which is why every slider from a given pitcher traced the same arc.

Lookup order for (pitcher, pitch type, platoon):
    pitchers[<pitcher>][<pitch>][<platoon>]  → per-pitcher signature pitch
    defaults[<pitch>][<platoon>]             → per-pitch-type baseline
    None                                     → caller falls back to generic geometry
"""

import json
import os

_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'pitch_locations.json')

VALID_INTENTS = {'zone', 'edge', 'chase', 'waste'}
_REQUIRED = ('name', 'intent', 'weight', 'in_away', 'height', 'spread_x', 'spread_z')


def _validate(archetypes, where):
    """Drop malformed archetypes rather than crashing mid-game on bad data."""
    clean = []
    for a in archetypes:
        missing = [k for k in _REQUIRED if k not in a]
        if missing:
            print(f"[WARNING] pitch_locations {where}: archetype "
                  f"{a.get('name', '?')} missing {missing}, skipped")
            continue
        if a['intent'] not in VALID_INTENTS:
            print(f"[WARNING] pitch_locations {where}: archetype {a['name']} "
                  f"has unknown intent '{a['intent']}', skipped")
            continue
        clean.append(a)
    return clean


def _load():
    try:
        with open(_PATH, 'r') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARNING] Could not load pitch_locations.json ({e}); "
              f"falling back to generic pitch targeting")
        return {}, {}

    def clean_group(group, label):
        out = {}
        for pitch, platoons in group.items():
            if pitch.startswith('_'):
                continue
            out[pitch] = {
                pl: _validate(arch, f"{label}/{pitch}/{pl}")
                for pl, arch in platoons.items() if not pl.startswith('_')
            }
        return out

    defaults = clean_group(raw.get('defaults', {}), 'defaults')
    pitchers = {
        name: clean_group(pitches, name)
        for name, pitches in raw.get('pitchers', {}).items()
        if not name.startswith('_')
    }
    return defaults, pitchers


DEFAULT_LOCATIONS, PITCHER_LOCATIONS = _load()


def get_archetypes(pitcher_key, pitch_type, platoon):
    """Archetypes for one (pitcher, pitch, platoon), or [] if none defined.

    A per-pitcher entry that only defines one platoon still falls back to the
    defaults for the other, so a signature pitch can be tuned for just the
    matchup that matters.
    """
    by_pitch = PITCHER_LOCATIONS.get(pitcher_key, {}).get(pitch_type)
    if by_pitch and by_pitch.get(platoon):
        return by_pitch[platoon]
    return DEFAULT_LOCATIONS.get(pitch_type, {}).get(platoon, [])
