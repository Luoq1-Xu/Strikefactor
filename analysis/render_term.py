"""Terminal renderer.

Reads the same metric functions the figures do, so `--terminal` and the PNGs
can never disagree. Uses `rich` when available (it is pinned in
requirements.txt) and degrades to plain ASCII when it is not.
"""

import shutil

import numpy as np

from . import metrics, theme

try:
    from rich.box import SIMPLE_HEAD
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAVE_RICH = True
except ImportError:  # pragma: no cover - exercised only without rich installed
    HAVE_RICH = False

SPARK = "▁▂▃▄▅▆▇█"
BAR = "█"


# ═════════════════════════════════════════════════════════════════════════
# Plain-text fallback
# ═════════════════════════════════════════════════════════════════════════
class _PlainConsole:
    """Minimal stand-in so the renderer works without rich installed."""

    def print(self, *args, **kwargs):
        for a in args:
            print(a if isinstance(a, str) else str(a))

    def rule(self, title=""):
        width = shutil.get_terminal_size((100, 24)).columns
        print(f"\n── {title} ".ljust(width, "─"))


def _plain_table(rows, columns, title=None):
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows
              else len(str(c)) for i, c in enumerate(columns)]
    out = []
    if title:
        out.append(f"\n{title}")
    out.append("  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
    out.append("  ".join("-" * w for w in widths))
    for r in rows:
        out.append("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    return "\n".join(out)


# Widest table here needs roughly this much room. Below it rich truncates
# cells to "14…", which silently corrupts numbers — better to render at the
# floor width and let the terminal soft-wrap than to lose digits.
MIN_WIDTH = 118


def make_console(force_terminal=None, width=None):
    if not HAVE_RICH:
        return _PlainConsole()
    if width is None:
        width = max(shutil.get_terminal_size((MIN_WIDTH, 24)).columns, MIN_WIDTH)
    return Console(force_terminal=force_terminal, width=width, highlight=False)


# ═════════════════════════════════════════════════════════════════════════
# Building blocks
# ═════════════════════════════════════════════════════════════════════════
def _table(columns, rows, title=None, justify_first_left=True, left_cols=()):
    if not HAVE_RICH:
        return _plain_table(rows, columns, title)
    t = Table(box=SIMPLE_HEAD, title=title, title_style="bold",
              header_style="bold white on grey23", expand=False,
              pad_edge=False, title_justify="left")
    for i, c in enumerate(columns):
        left = (i == 0 and justify_first_left) or i in left_cols
        t.add_column(str(c), justify="left" if left else "right", no_wrap=True)
    for r in rows:
        t.add_row(*[Text.from_markup(str(v)) if isinstance(v, str) else str(v)
                    for v in r])
    return t


def _bar(value, vmax, width=12):
    if not vmax or not np.isfinite(value):
        return ""
    n = int(round(width * max(value, 0) / vmax))
    return BAR * max(n, 1 if value > 0 else 0)


def _spark(values, width=None):
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if len(vals) < 2:
        return ""
    if width and len(vals) > width:
        # Downsample by averaging into `width` buckets.
        step = len(vals) / width
        vals = [float(np.mean(vals[int(i * step):max(int((i + 1) * step), int(i * step) + 1)]))
                for i in range(width)]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return SPARK[len(SPARK) // 2] * len(vals)
    return "".join(SPARK[min(int((v - lo) / (hi - lo) * (len(SPARK) - 1)),
                             len(SPARK) - 1)] for v in vals)


def _colored_cell(text, bg_hex, width=None):
    """A background-filled cell — used by the scouting card and zone grid."""
    label = text if width is None else text.center(width)
    if not HAVE_RICH:
        return label
    fg = theme.text_color_for(bg_hex)
    return Text(label, style=f"{fg} on {bg_hex}")


def _rate_color(value, lo, hi, invert=False):
    """Blend red→cream→green across a range, for at-a-glance scanning."""
    if value is None or not np.isfinite(value):
        return theme.PANEL
    span = (hi - lo) or 1.0
    t = float(np.clip((value - lo) / span, 0, 1))
    if invert:
        t = 1 - t
    if t >= 0.5:
        return theme.to_hex(theme.blend(theme.NEUTRAL_RGB, theme.GOOD_RGB, (t - 0.5) * 2))
    return theme.to_hex(theme.blend(theme.BAD_RGB, theme.NEUTRAL_RGB, t * 2))


# ═════════════════════════════════════════════════════════════════════════
# Sections
# ═════════════════════════════════════════════════════════════════════════
def header(ctx, console):
    ov = metrics.overview(ctx)
    span = ctx.date_span
    span_txt = (f"{span[0]:%Y-%m-%d} → {span[1]:%Y-%m-%d} · {ov.get('days', 0)} days"
                if span else "no dates")

    if not HAVE_RICH:
        console.rule("StrikeFactor Pitch Analysis")
        console.print(f"{ctx.label}\n{span_txt}")
        console.print(
            f"pitches={ov['pitches']:,}  PA={ov['pa']:,}  CSW%={ov['csw_pct']:.1f}  "
            f"Whiff%={ov['whiff_pct']:.1f}  K%={ov['k_pct']:.1f}  "
            f"AVG={metrics.fmt_avg(ov['avg'])}  wOBA={metrics.fmt_avg(ov['woba'])}")
        return

    tiles = [
        ("Pitches", f"{ov['pitches']:,}"), ("PA", f"{ov['pa']:,}"),
        ("CSW%", f"{ov['csw_pct']:.1f}"), ("Whiff%", f"{ov['whiff_pct']:.1f}"),
        ("Chase%", f"{ov['chase_pct']:.1f}"), ("Zone%", f"{ov['zone_pct']:.1f}"),
        ("K%", f"{ov['k_pct']:.1f}"), ("BB%", f"{ov['bb_pct']:.1f}"),
        ("AVG", metrics.fmt_avg(ov["avg"])), ("OPS", metrics.fmt_avg(ov["ops"])),
        ("wOBA", metrics.fmt_avg(ov["woba"])),
    ]
    grid = Table.grid(padding=(0, 2))
    for _ in tiles:
        grid.add_column(justify="center")
    grid.add_row(*[Text(k, style="dim") for k, _ in tiles])
    grid.add_row(*[Text(v, style="bold") for _, v in tiles])

    console.print(Panel(
        Group(Text(ctx.label, style="bold cyan"), Text(span_txt, style="dim"),
              Text(""), grid),
        title="[bold]StrikeFactor — Pitch Analysis[/bold]", border_style="cyan",
        expand=False))


def overview_section(ctx, console):
    line = metrics.pitching_line(ctx)
    if not line.empty:
        rows = [[
            r["display"], r["g"] or "—", metrics.fmt_ip(r["outs"]), r["bf"], r["h"],
            r["r"], r["hr"], r["bb"], r["k"],
            metrics.fmt_num(r["era"]), metrics.fmt_num(r["whip"]),
            metrics.fmt_num(r["k_per_9"], 1),
        ] for _, r in line.iterrows()]
        console.print(_table(
            ["Pitcher", "G", "IP", "BF", "H", "R", "HR", "BB", "K", "ERA", "WHIP", "K/9"],
            rows, title="Pitching Line — GameDay"))
        if not bool(line["runs_exact"].all()):
            _dim(console, "  R is per-pitch where logged, otherwise prorated by "
                          "batters faced within each game.")
        dropped = line.attrs.get("dropped_pitches", 0)
        if dropped:
            _dim(console, f"  {dropped:,} pitches excluded — no game_id, so their "
                          f"runs cannot be attributed to any pitcher.")

    df = metrics.plate_discipline(ctx)
    if df.empty:
        return
    rows = [[
        r["display"], r["pa"], r["h"], r["hr"], r["bb"], r["k"],
        metrics.fmt_avg(r["avg"]), metrics.fmt_avg(r["obp"]),
        metrics.fmt_avg(r["slg"]), metrics.fmt_avg(r["ops"]),
        metrics.fmt_avg(r["woba"]),
        metrics.fmt_pct(100 * r["k_pct"]), metrics.fmt_pct(100 * r["bb_pct"]),
    ] for _, r in df.iterrows()]
    console.print(_table(
        ["Pitcher", "PA", "H", "HR", "BB", "K", "AVG", "OBP", "SLG", "OPS",
         "wOBA", "K%", "BB%"],
        rows, title="Batting Results vs Each Pitcher"))


def arsenal_section(ctx, console):
    ars = metrics.arsenal(ctx, by_pitcher=False)
    if ars.empty:
        return
    vmax = float(ars["usage_pct"].max())
    rows = []
    for _, r in ars.iterrows():
        rows.append([
            f"[bold]{r['name']}[/bold]" if HAVE_RICH else r["name"],
            f"{r['n']:,}",
            f"{r['usage_pct']:5.1f}% {_bar(r['usage_pct'], vmax, 10)}",
            f"{r['velo']:.1f}",
            f"{r['pfx_x']:+.1f}", f"{r['pfx_z']:+.1f}",
            metrics.fmt_pct(r["csw_pct"]), metrics.fmt_pct(r["whiff_pct"]),
            metrics.fmt_pct(r["chase_pct"]), metrics.fmt_pct(r["putaway_pct"]),
            metrics.fmt_avg(r["xba"]),
            f"{r['rv_per_100']:+.2f}",
        ])
    console.print(_table(
        ["Pitch", "N", "Usage", "Velo", "HB", "IVB", "CSW%", "Whiff%", "Chase%",
         "PutAway%", "xBA", "RV/100"],
        rows, title="Arsenal", left_cols={2}))  # bars read left-to-right
    _dim(console, "  HB/IVB in inches · RV/100 is runs saved per 100 pitches, "
                  "relative within this slice.")

    _scouting_card(ctx, console)


def _scouting_card(ctx, console):
    card = metrics.scouting_card(ctx)
    if card.empty or not HAVE_RICH:
        return
    cols = [("CSW%", "csw_pct", False), ("Whiff%", "whiff_pct", False),
            ("Chase%", "chase_pct", False), ("PutAway%", "putaway_pct", False),
            ("xBA", "xba", True)]

    t = Table(box=SIMPLE_HEAD, title="Scouting Card", title_style="bold",
              header_style="bold white on grey23", title_justify="left",
              pad_edge=False)
    t.add_column("Pitch", justify="left", no_wrap=True)
    for label, _, _ in cols:
        t.add_column(label, justify="center", no_wrap=True)

    for _, r in card.iterrows():
        cells = [Text(f"{r['name']} ({r['n']})", style="bold")]
        for label, key, invert in cols:
            lo, avg, hi = theme.SCOUTING_BENCH[label]
            val = r[key]
            bg = _rate_color(val, min(lo, hi), max(lo, hi), invert=invert)
            txt = metrics.fmt_avg(val) if key == "xba" else f"{val:.0f}%"
            cells.append(_colored_cell(f" {txt} ", bg))
        t.add_row(*cells)
    console.print(t)
    _dim(console, "  Colour is vs MLB benchmark from the pitcher's POV "
                  "(green better, red worse); xBA inverted.")


def location_section(ctx, console):
    _zone_grid(ctx, console, "whiff", "Whiff% by zone")
    # Density has no good/bad direction, so it gets a neutral volume ramp
    # rather than the red→green one used for rate stats.
    _zone_grid(ctx, console, "density", "Pitch density by zone", fmt="{:.1f}",
               sequential=True)

    hands = [h for h in ("L", "R")
             if len(ctx.pitches[ctx.pitches["batter_hand"] == h]) >= 100]
    if len(hands) >= 1:
        rows = []
        for _, g in sorted(ctx.pitches.groupby("platoon")):
            swings = int(g["is_swing"].sum())
            term = g[g["is_terminal"]]
            o = metrics._outcome_metrics(g) if len(term) else None
            rows.append([
                g["platoon"].iloc[0], f"{len(g):,}", f"{len(term):,}",
                metrics.fmt_pct(100 * g["in_zone"].mean()),
                metrics.fmt_pct(100 * g["is_swing"].mean()),
                metrics.fmt_pct(100 * g["is_whiff"].sum() / swings if swings else 0),
                metrics.fmt_avg(o["avg"]) if o else "—",
                metrics.fmt_avg(o["woba"]) if o else "—",
            ])
        console.print(_table(
            ["Matchup", "Pitches", "PA", "Zone%", "Swing%", "Whiff%", "AVG", "wOBA"],
            rows, title="Platoon Splits"))

    summary, _ = metrics.umpire_accuracy(ctx)
    if summary and summary.get("graded"):
        rows = [
            ["Graded calls", f"{summary['graded']:,}"],
            ["Coverage", metrics.fmt_pct(summary["coverage_pct"])],
            ["Correct", metrics.fmt_pct(summary["accuracy_pct"], 2)],
            ["Strikes stolen", f"{summary['stolen_strikes']:,}"],
            ["Strikes lost", f"{summary['lost_strikes']:,}"],
            ["ABS challenges", f"{summary['challenged']:,}"],
        ]
        console.print(_table(["Umpire", "Value"], rows, title="Umpire Accuracy"))
        if summary["challenged"] == 0:
            _dim(console, "  No ABS challenge has ever been logged.")


def _zone_grid(ctx, console, value, title, fmt="{:.0f}", sequential=False):
    vals, counts = metrics.zone_grid(ctx.pitches, value=value)
    finite = vals[np.isfinite(vals)]
    if not finite.size:
        return
    lo, hi = float(finite.min()), float(finite.max())
    span = (hi - lo) or 1.0

    def color_for(v):
        if not sequential:
            return _rate_color(v, lo, hi)
        t = float(np.clip((v - lo) / span, 0, 1))
        return theme.to_hex(theme.blend(theme.VOLUME_LO_RGB, theme.VOLUME_HI_RGB, t))

    if not HAVE_RICH:
        rows = [[fmt.format(v) if np.isfinite(v) else "·" for v in row] for row in vals]
        console.print(_plain_table(rows, ["", "", "zone", "", ""], title=title))
        return

    t = Table(box=SIMPLE_HEAD, title=title, title_style="bold", show_header=False,
              title_justify="left", pad_edge=False, padding=(0, 0))
    for _ in range(5):
        t.add_column(justify="center", no_wrap=True)
    for r in range(5):
        cells = []
        for c in range(5):
            v = vals[r, c]
            if not np.isfinite(v):
                cells.append(Text("   ·   ", style="grey35"))
                continue
            # Middle 3x3 is the strike zone; mark its border with brackets.
            in_zone = 1 <= r <= 3 and 1 <= c <= 3
            label = fmt.format(v)
            body = f"[{label}]" if in_zone else f" {label} "
            cells.append(_colored_cell(body.center(7), color_for(v)))
        t.add_row(*cells)
    console.print(t)
    _dim(console, "  Catcher's view, batter-relative (right = inside). "
                  "[bracketed] cells are in the strike zone.")


def sequencing_section(ctx, console):
    seq = metrics.sequencing(ctx)
    if not seq.empty:
        top, bottom = metrics.best_and_worst_sequences(seq, n=6)
        rows = []
        for tag, chunk in (("↑", top), ("↓", bottom)):
            for _, r in chunk.iterrows():
                rows.append([
                    tag, f"{r['prev_name']} → {r['cur_name']}", f"{r['n']:,}",
                    metrics.fmt_pct(r["whiff_pct"]),
                    metrics.fmt_pct(r["baseline_whiff_pct"]),
                    f"{r['whiff_delta']:+.1f}",
                ])
        console.print(_table(
            ["", "Sequence", "N", "Whiff%", "Baseline", "Δ"], rows,
            title="Sequencing — best and worst setups"))

    _, pairs = metrics.tunneling(ctx)
    if not pairs.empty:
        rows = [[
            r["display"], r["pair"], f"{r['n']:,}",
            f"{r['commit_sep_in']:.1f}\"", f"{r['plate_sep_in']:.1f}\"",
            f"{r['tunnel_ratio']:.2f}x",
        ] for _, r in pairs.head(10).iterrows()]
        console.print(_table(
            ["Pitcher", "Pair", "N", "Sep@commit", "Sep@plate", "Ratio"], rows,
            title="Tunneling — best pairs"))
        _dim(console, f"  Commit point at {theme.COMMIT_POINT_FT:.1f} ft. "
                      f"Higher ratio = looks the same longer, ends up further apart.")


def results_section(ctx, console):
    tab = metrics.outcome_breakdown(ctx)
    if not tab.empty:
        rows = []
        for pname, r in tab.iterrows():
            total = int(r.sum()) or 1
            rows.append([theme.pitcher_display(pname), f"{total:,}"]
                        + [str(int(r[o])) for o in theme.OUTCOME_ORDER])
        console.print(_table(
            ["Pitcher", "PA"] + [theme.OUTCOME_ABBREV[o] for o in theme.OUTCOME_ORDER],
            rows, title="At-Bat Outcomes (counts)"))

    st = metrics.performance_by_count_state(ctx)
    if not st.empty:
        rows = [[
            r["state"].replace("_", " "), f"{r['n']:,}",
            metrics.fmt_pct(r["usage_pct"]), metrics.fmt_pct(r["zone_pct"]),
            metrics.fmt_pct(r["swing_pct"]), metrics.fmt_pct(r["whiff_pct"]),
            metrics.fmt_pct(r["chase_pct"]), metrics.fmt_pct(r["csw_pct"]),
            metrics.fmt_pct(r["terminal_pct"]), metrics.fmt_pct(r["k_share"]),
        ] for _, r in st.iterrows()]
        console.print(_table(
            ["Count state", "Pitches", "Share", "Zone%", "Swing%", "Whiff%",
             "Chase%", "CSW%", "Ends PA%", "K% of PA"], rows,
            title="By Count State"))

    usage = metrics.usage_by_count(ctx)
    if not usage.empty:
        rows = [[theme.pitch_name(pt)] + [f"{v:.0f}" for v in usage.loc[pt]]
                for pt in usage.index]
        console.print(_table(["Pitch"] + list(usage.columns), rows,
                             title="Usage % by count"))

    df = metrics.plate_discipline(ctx)
    if not df.empty:
        rows = [[
            r["display"], r["pa"], f"{r['pitches']:,}",
            metrics.fmt_num(r["p_per_pa"]),
            metrics.fmt_pct(100 * r["csw_pct"]), metrics.fmt_pct(100 * r["whiff_pct"]),
            metrics.fmt_pct(100 * r["swing_pct"]), metrics.fmt_pct(100 * r["zone_pct"]),
            metrics.fmt_pct(100 * r["chase_pct"]),
            metrics.fmt_pct(100 * r["f_strike_pct"]),
            metrics.fmt_pct(100 * r["putaway_pct"]),
            metrics.fmt_avg(r["babip"]) if r["bip"] else "—",
        ] for _, r in df.iterrows()]
        console.print(_table(
            ["Pitcher", "TBF", "NP", "P/PA", "CSW%", "Whiff%", "Swing%", "Zone%",
             "Chase%", "F-Str%", "PutAway%", "BABIP"], rows,
            title="Plate Discipline"))


def trends_section(ctx, console):
    df = metrics.trends(ctx)
    if df.empty or len(df) < 3:
        _dim(console, "Not enough distinct days for a trend read.")
        return
    width = 32
    rows = []
    for col, label in (("csw_pct", "CSW%"), ("whiff_pct", "Whiff%"),
                       ("chase_pct", "Chase%"), ("woba", "wOBA")):
        series = df[col].dropna()
        if len(series) < 3:
            continue
        first = float(series.iloc[:max(len(series) // 4, 1)].mean())
        last = float(series.iloc[-max(len(series) // 4, 1):].mean())
        fmt = metrics.fmt_avg if col == "woba" else (lambda v: f"{v:.1f}")
        rows.append([label, _spark(series.tolist(), width), fmt(first), fmt(last),
                     f"{last - first:+.3f}" if col == "woba" else f"{last - first:+.1f}"])
    if rows:
        console.print(_table(["Metric", f"Trend ({len(df)} days)", "First 25%",
                              "Last 25%", "Δ"], rows, title="Trends"))

    per_mode = ctx.pitches["game_mode"].value_counts()
    rows = [[str(k), f"{v:,}", f"{100*v/len(ctx.pitches):.1f}%"]
            for k, v in per_mode.items()]
    console.print(_table(["Mode", "Pitches", "Share"], rows,
                         title="Sample Composition"))


SECTION_RENDERERS = {
    "overview": overview_section,
    "arsenal": arsenal_section,
    "location": location_section,
    "sequencing": sequencing_section,
    "results": results_section,
    "trends": trends_section,
}


def _dim(console, text):
    if HAVE_RICH:
        console.print(Text(text, style="dim"))
    else:
        console.print(text)


def render(ctx, sections=None, console=None, width=None):
    """Print the requested sections. Returns the console used."""
    console = console or make_console(width=width)
    if ctx.empty:
        console.print(f"No pitches match the active filter: {ctx.label}")
        return console

    header(ctx, console)
    from .figures import SECTIONS, SECTION_TITLES
    wanted = [s for s in SECTIONS if not sections or s in sections]
    for name in wanted:
        renderer = SECTION_RENDERERS.get(name)
        if renderer is None:
            continue
        console.rule(f"[bold]{SECTION_TITLES[name]}[/bold]" if HAVE_RICH
                     else SECTION_TITLES[name])
        renderer(ctx, console)
    return console
