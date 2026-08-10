# Pitch Analysis Refactor — Design Doc

Status: implemented
Date: 2026-07-26
Scope: `pitch_analysis.py`, `batting_analysis.py`, new `analysis/` package

---

## 1. Motivation

`pitch_analysis.py` grew to 1,333 lines as a single flat module. It works, but:

- Several metrics are **numerically wrong** (below), so the figures look authoritative while reporting bad values.
- It analyses roughly a third of the columns the game actually logs. The most
  informative signals — sequencing, trajectory tunneling, per-pitch run value —
  are recorded in the DB and never read.
- Figures are PNG-only. There is no way to get a quick read in a terminal.
- Metrics are computed inline inside figure functions, so nothing is reusable
  by a second renderer, and nothing is testable.
- ~150 lines (`Filter`, `parse_args`, `pw`, palettes) are duplicated verbatim in
  `batting_analysis.py`.

Runtime is **not** a motivation: a full run of the current script takes 3.2s
over 24k pitches. The N+1 query pattern gets cleaned up as a side effect of the
restructure, not as a goal.

### Dataset baseline (measured 2026-07-26)

| Table | Rows |
|---|---|
| `pitches` | 24,334 |
| `pitch_trajectories` | 486,680 (20/pitch, 100% coverage, uniform 54ft→0ft) |
| `at_bats` | 8,318 |
| `games` | 461 (38 GameDay with results) |
| `batter_profiles` | 15 |

Span: 2026-03-16 → 2026-07-26, 94 distinct days.

---

## 2. Correctness bugs (fix before redesign)

### 2.1 Whiff% / CSW% understated by ~40%

`pitcher_pitch_metrics()` defines a whiff as `swing_type > 0 AND on_time = 0`,
with a comment asserting that an outcome-based test would sweep in fouls. The
comment is wrong. Measured cross-tab over all swings:

| `on_time` | `outcome` | n |
|---|---|---|
| 0 | strike / strikeout | 5,130 |
| 1 | foul | 2,889 |
| 1 | strike / strikeout | 1,516 |
| 2 | strike / strikeout | 2,122 |
| 2 | in-play (SINGLE…LINEOUT, POP_UP) | 4,225 |

Fouls carry their own `outcome = 'foul'`. **No** swing that made contact ever
lands on `outcome IN ('strike','strikeout')`. `on_time` is a *timing-quality*
grade (0 mistimed / 1 foul-timing / 2 perfect), not a contact flag — a
perfectly-timed swing still misses if the bat is in the wrong place
(`pitch_simulation.py:253`).

**Fix:** `is_whiff := swing_type > 0 AND outcome IN ('strike','strikeout')`.

Dataset-wide impact: Whiff% 32.3% → 55.2%, CSW% 38.7% → 53.6%.

### 2.2 `POP_UP` missing from every outcome group

> **Naming note (schema v5, later):** this outcome is now recorded as `POP UP`,
> matching `HOME RUN`. `PitchDB._migrate` rewrote the existing rows, so the
> names below are historical — current code matches the spaced form. The
> trajectory-shape enum in `hit_animation.py` still uses `POP_UP`; it is a
> different namespace.


86 terminal at-bats (verified against `at_bats.final_outcome`) are absent from
`TERMINAL_OUTCOMES_TUPLE`, `TERMINAL_OUTCOMES_SQL`, `OUT_OUTCOMES`,
`IN_PLAY_OUTCOMES`, and fig4's `outcome_order`. They silently disappear from
PA, BF, outs, IP, K%, AVG denominators and from the outcome chart.

**Fix:** add `POP_UP` to all four groups. It is an out and a ball in play.

### 2.3 GameDay pitching line mixes denominators

`_gameday_runs_by_pitcher()` attributes a game's entire run total to whoever
threw its first pitch. IP/BF are counted across *all* appearances. A pitcher who
only ever relieved therefore shows innings and zero runs — Chris Sale renders as
39.1 IP, 197 BF, R 0, G 0, **ERA 0.00**.

**Fix:** attribute runs per pitch from `runs_scored_on_pitch` (already logged,
47.6% filled), falling back to the starter-attribution query only for rows
predating that column. Label the line explicitly when it falls back.

### 2.4 `FO` pitch type unmapped

Sasaki's forkball (235 pitches) is missing from `PITCH_COLORS` / `PITCH_NAMES`
and renders as a gray bar labelled "FO".

### 2.5 Table text clipped

`matplotlib` tables do not auto-size columns. The dashboard shows "Yoshinobu
Yama", "Jacob deGr", "Chris Sal". Fixed once in a shared table helper.

---

## 3. Under-used data

Measured non-null fill rates over `pitches`:

| Column | Fill | Unlocks |
|---|---|---|
| `prev_pitch_type` | 93.8% | Sequencing (53 observed pairs) |
| `pitch_trajectories` | 100% | Tunneling / commit-point separation |
| `runs_scored_on_pitch` | 47.6% | Per-pitch run value, correct ERA |
| `swing_timing_diff_ms` | 34.0% | Deception — timing distortion by pitch |
| `is_hit`, `swing_type` (1 vs 2) | 100% | Contact-swing vs power-swing splits |
| `ai_umpire_strike` / `truth_strike` | 13.6% | Umpire accuracy (167 miscalls) |
| `pitcher_fatigue`, `pitcher_pitch_count` | 12.0% | Fatigue / times-through-order |
| `contact_quality`, `vertical_offset_in` | 11.2% | Quality-of-contact distribution |
| `intent_*`, `miss_kind`, `command_sigma_in` | 1.2% | Command profile (new feature) |
| `created_at` | 100% | 94-day trend |
| `pitcher_hand` | 11.5% | Platoon splits — **backfillable** |

`pitcher_hand` is only populated on recent rows, but is fully derivable from
`PITCHER_HANDEDNESS` in `strikefactor/data/pitch_database.py`. The analysis
layer backfills it so platoon splits cover the whole dataset.

`abs_challenged` / `abs_overturned` are present but **all zero** — no challenge
has ever been logged. Any ABS panel must say "no challenges recorded" rather
than render an empty chart.

---

## 4. Architecture

### 4.1 Principle

**Every panel is a pure metric function returning a DataFrame, plus one or more
renderers.** Metrics never draw; renderers never query. This is what makes
`--terminal` cheap — it is a second renderer over the same metric layer, not a
second implementation.

### 4.2 Layout

```
analysis/
  __init__.py
  data.py         # connection, load_pitches() -> DataFrame with derived columns,
                  #   load_trajectories(), load_games(); cached per process
  filters.py      # Filter dataclass, add_filter_args(), filter_from_args()
  theme.py        # palettes, PITCH_NAMES (+FO), PITCHER_DISPLAY, benchmarks, rcParams
  metrics.py      # pure DataFrame -> DataFrame metric functions
  render_mpl.py   # figure/table/save helpers (column sizing fixed once)
  render_term.py  # rich renderers (tables, bar columns, zone grid)
  report.py       # HTML report writer
  figures/
    __init__.py   # FIGURES registry: id, section, title, caption, render fn
    arsenal.py location.py sequencing.py results.py umpire.py trends.py
pitch_analysis.py   # thin CLI entry point (unchanged invocation)
batting_analysis.py # phase 5: imports analysis.filters/data/theme
```

### 4.3 Derived columns (computed once in `data.py`)

`in_zone`, `is_swing`, `is_whiff`, `is_called_strike`, `is_terminal`,
`count_state` (`ahead`/`even`/`behind`/`two_strike`), `platoon` (from backfilled
`pitcher_hand` × `batter_hand`), `run_value`, `date`.

### 4.4 State

The module-level mutable `FILTER` / `OUT_DIR` / `conn` globals go away. A single
`AnalysisContext` (filter, dataframe, out_dir) is constructed in the CLI and
passed down explicitly.

---

## 5. Figure redesign

### Drop

- **Raw location scatter** — 24k overplotted points; verified unreadable.
- **Pie chart** of pitch mix — 8 slices, replaced by a sorted bar.

### Keep, fixed

Speed distributions, movement plot (add per-pitcher facets + 1σ ellipses),
count heatmap, dashboard, plate-discipline table, scouting card.

The scouting card benchmarks against **both** MLB and the dataset's own
percentile. Measured K% runs ~48% here, so fixed MLB thresholds saturate green
on every cell and carry no information on their own.

### New

| Figure | Reads |
|---|---|
| **Zone heatmaps** | 5×5 grid per pitch type, split by batter hand, colored by whiff% and by damage. Replaces the scatter. |
| **Tunneling** | Trajectories overlaid from release, commit point at y ≈ 23.8 ft (sample_idx 10–11), plus a tunnel-ratio table (plate separation ÷ commit separation) per pitch pair. |
| **Sequencing** | prev→current usage matrix and whiff% delta vs that pitch's baseline. |
| **Run value** | RV/100 pitches by pitch type, from empirical count-state run expectancy derived from this dataset's 8.3k PAs. |
| **Trends** | Rolling CSW% and wOBA-against over the 94-day span. |
| **Umpire accuracy** | The 167 miscalls by location; explicit "no challenges recorded" note. |

---

## 6. Terminal mode

`rich` 13.7.1 is already in `requirements.txt`.

```
python pitch_analysis.py                        # unchanged: PNGs + report.html
python pitch_analysis.py --terminal             # rich tables to stdout, no PNGs
python pitch_analysis.py --terminal --figures   # both
python pitch_analysis.py --terminal --sections arsenal,results
python pitch_analysis.py --pitcher degrom --terminal
```

`--terminal` skips figure rendering by default so a text read is instant; pass
`--figures` to force both. Panels: header (filter, N, date span), pitching line,
plate discipline, per-pitcher arsenal with unicode bar columns, scouting card as
background-colored cells, and a 5×5 zone grid in colored blocks.

Falls back to plain ASCII if `rich` is unavailable. `NO_COLOR` is honored by
`rich` automatically.

---

## 7. Phasing

1. **Correctness fixes in place** — small diff, verifiable against §2 numbers.
2. **Extract `analysis/`** — pure move; output identical except for phase 1.
3. **`--terminal`** over the phase-2 metric layer.
4. **New / redesigned figures.**
5. **`batting_analysis.py` onto the shared core** (removes ~150 duplicated lines).

### What actually shipped

Phases 1 and 2 landed together: the fixes all live in the metric layer, so
patching 1,333 lines of soon-to-be-deleted code first would have been wasted
work. The §2 numbers were verified directly against the new layer instead
(Whiff% 32.3 → 55.2, CSW% 38.7 → 53.6, PA 8,232 → 8,318, Sale ERA 0.00 → 5.58).

Three things were found during implementation that were not in the original
plan:

- **`batting_analysis.py` carried both §2.1 and §2.2 verbatim** — same
  `on_time = 0` whiff test, same missing `POP_UP`. Fixed there too; leaving it
  reporting Whiff% 32% while `pitch_analysis.py` reported 55% would have been
  worse than either number alone. Its `Miss / Foul / Perfect` timing labels
  were also renamed to `Mistimed / Foul timing / On time`, since they describe
  timing and never described contact.
- **Both scripts wrote `report.html` into the same per-filter folder** and had
  been silently overwriting each other. `batting_analysis.py` now writes
  `batting_report.html`.
- **Run value per count state is structurally zero.** The count-value model is
  fitted per count, so the mean run value of every pitch thrown in a given
  count is exactly zero by construction. The column was removed from
  `performance_by_count_state()` and replaced with `CSW%`, `Ends PA%`, and
  `K% of PA`. Run value remains meaningful per pitch type and per sequence,
  which do not partition by count.

Figure count went from 9 to 15, in six sections. A terminal-only run takes
~0.8s; a full figure run takes ~10s, up from 3.2s, almost entirely from the
486k trajectory rows the tunneling figure reads.

---

## 8. Decisions

- **Package split over single-file rewrite.** Justified by the duplication
  between the two analysis scripts and by the need for a metric layer that two
  renderers can share.
- **`--terminal` implies no PNGs.** Text-only runs should be instant; `--figures`
  opts back in.
- **`pitch_analysis.py` stays the entry point.** It is the documented command in
  `CLAUDE.md` and in the README; only its internals move.
