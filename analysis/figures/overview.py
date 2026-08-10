"""Cover figure: the numbers you'd want if you only looked at one page."""

import numpy as np
from matplotlib.gridspec import GridSpec

from .. import metrics, theme
from ..render_mpl import bar_labels, figure_title, note, plt, save, styled_table


def dashboard(ctx):
    if ctx.empty:
        from ..render_mpl import empty_figure
        return empty_figure(ctx, "01_dashboard.png", "StrikeFactor Dashboard")

    line_rows = max(len(metrics.pitching_line(ctx)), 1)
    slash_rows = max(len(metrics.plate_discipline(ctx)), 1)

    fig = plt.figure(figsize=(17, 12))
    figure_title(fig, "StrikeFactor Dashboard", ctx)
    # Tables now fill their axes exactly, so size each row by its row count
    # instead of leaving a band of empty panel around a centred table.
    gs = GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.28,
                  height_ratios=[0.24 * (line_rows + 1), 0.24 * (slash_rows + 1),
                                 2.2])

    _pitching_line_panel(fig.add_subplot(gs[0, :]), ctx)
    _slash_line_panel(fig.add_subplot(gs[1, :]), ctx)
    _mix_panel(fig.add_subplot(gs[2, 0]), ctx)
    _rate_panel(fig.add_subplot(gs[2, 1]), ctx)
    _speed_panel(fig.add_subplot(gs[2, 2]), ctx)

    return save(fig, ctx, "01_dashboard.png")


def _pitching_line_panel(ax, ctx):
    line = metrics.pitching_line(ctx)
    if line.empty:
        note(ax, f"No GameDay innings recorded for {ctx.label}")
        ax.set_title("Pitching Line — GameDay", fontweight="bold", pad=10, fontsize=12)
        return

    rows = [[
        r["display"], r["g"] or "—", metrics.fmt_ip(r["outs"]), r["bf"], r["h"], r["r"],
        r["er"], r["hr"], r["bb"], r["k"],
        metrics.fmt_num(r["era"]), metrics.fmt_num(r["whip"]),
        metrics.fmt_num(r["k_per_9"], 1), metrics.fmt_num(r["bb_per_9"], 1),
    ] for _, r in line.iterrows()]
    cols = ["Pitcher", "G", "IP", "BF", "H", "R", "ER", "HR", "BB", "K",
            "ERA", "WHIP", "K/9", "BB/9"]
    styled_table(ax, rows, cols, fontsize=10.5)

    exact = bool(line["runs_exact"].all())
    src = ("R from per-pitch scoring" if exact else
           "R per-pitch where logged, else prorated by batters faced")
    dropped = line.attrs.get("dropped_pitches", 0)
    if dropped:
        src += f"; {dropped:,} unattributable pitches excluded"
    ax.set_title(f"Pitching Line — GameDay  ({src}; ER = R, no errors tracked)",
                 fontweight="bold", pad=10, fontsize=12)


def _slash_line_panel(ax, ctx):
    df = metrics.plate_discipline(ctx)
    if df.empty:
        note(ax, f"No completed at-bats match {ctx.label}")
        ax.set_title("Batting Performance vs Each Pitcher", fontweight="bold", pad=10)
        return

    rows = [[
        r["display"], r["pa"], r["h"], r["hr"], r["bb"], r["k"],
        metrics.fmt_avg(r["avg"]), metrics.fmt_avg(r["obp"]),
        metrics.fmt_avg(r["slg"]), metrics.fmt_avg(r["ops"]),
        metrics.fmt_pct(100 * r["k_pct"]), metrics.fmt_pct(100 * r["bb_pct"]),
        metrics.fmt_avg(r["babip"]) if r["bip"] else "—",
        metrics.fmt_avg(r["woba"]),
        metrics.fmt_pct(100 * r["csw_pct"]),
        metrics.fmt_pct(100 * r["whiff_pct"]),
    ] for _, r in df.iterrows()]
    cols = ["Pitcher", "PA", "H", "HR", "BB", "K", "AVG", "OBP", "SLG", "OPS",
            "K%", "BB%", "BABIP", "wOBA", "CSW%", "Whiff%"]
    styled_table(ax, rows, cols, fontsize=9.5)
    ax.set_title("Batting Performance vs Each Pitcher", fontweight="bold", pad=10)


def _mix_panel(ax, ctx):
    """Sorted bars — replaces the 8-slice pie, which was unreadable."""
    ars = metrics.arsenal(ctx, by_pitcher=False)
    if ars.empty:
        note(ax, "No data")
        return
    ars = ars.sort_values("usage_pct")
    colors = [theme.pitch_color(pt) for pt in ars["pitch_type"]]
    ax.barh(ars["name"], ars["usage_pct"], color=colors, edgecolor=theme.BG)
    bar_labels(ax, list(ars["usage_pct"]), fmt="{:.1f}%", offset=0.4)
    ax.set_xlabel("Usage %")
    ax.set_xlim(0, max(ars["usage_pct"]) * 1.18)
    ax.set_title("Pitch Mix", fontweight="bold")
    ax.grid(True, axis="x")


def _rate_panel(ax, ctx):
    ars = metrics.arsenal(ctx, by_pitcher=False)
    if ars.empty:
        note(ax, "No data")
        return
    ars = ars.sort_values("usage_pct", ascending=False)
    x = np.arange(len(ars))
    width = 0.38
    ax.bar(x - width / 2, ars["csw_pct"], width, label="CSW%",
           color="#e74c3c", edgecolor=theme.BG)
    ax.bar(x + width / 2, ars["whiff_pct"], width, label="Whiff%",
           color="#f39c12", edgecolor=theme.BG)
    ax.set_xticks(x)
    ax.set_xticklabels(ars["pitch_type"], fontsize=9)
    ax.set_ylabel("Percent")
    ax.set_title("Called-Strike+Whiff vs Whiff", fontweight="bold")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(True, axis="y")


def _speed_panel(ax, ctx):
    speeds, labels = [], []
    for pn in ctx.pitchers:
        s = ctx.for_pitcher(pn)["speed_mph"].dropna()
        if len(s):
            speeds.append(s.to_numpy())
            labels.append(theme.pitcher_short(pn))
    if not speeds:
        note(ax, "No data")
        return
    try:
        bp = ax.boxplot(speeds, patch_artist=True, tick_labels=labels)
    except TypeError:  # matplotlib < 3.9
        bp = ax.boxplot(speeds, patch_artist=True, labels=labels)
    for patch, color in zip(bp["boxes"], theme.PITCHER_PALETTE):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
    for median in bp["medians"]:
        median.set_color("#ffffff")
    ax.set_ylabel("Speed (mph)")
    ax.set_title("Velocity Range by Pitcher", fontweight="bold")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(True, axis="y")
