"""Change over time — the axis the old script had data for but never plotted."""

from matplotlib.gridspec import GridSpec

from .. import metrics, theme
from ..render_mpl import empty_figure, figure_title, note, plt, save

WINDOW = 7


def trends(ctx):
    df = metrics.trends(ctx, window=WINDOW)
    if df.empty or len(df) < 3:
        return empty_figure(
            ctx, "14_trends.png", "Trends Over Time",
            "Need at least 3 distinct days of pitches in this slice.")

    fig = plt.figure(figsize=(16, 9.5))
    figure_title(fig, "Trends Over Time", ctx, y=0.98)
    gs = GridSpec(2, 2, figure=fig, hspace=0.34, wspace=0.22)

    panels = [
        (gs[0, 0], [("csw_pct", "CSW%", "#e74c3c"), ("whiff_pct", "Whiff%", "#f39c12")],
         "Stuff", "Percent"),
        (gs[0, 1], [("chase_pct", "Chase%", "#3498db")],
         "Chase rate (batter discipline)", "Percent"),
        (gs[1, 0], [("woba", "wOBA", "#2ecc71")], "wOBA allowed", "wOBA"),
        (gs[1, 1], [("rv_per_100", "RV/100 (batter)", "#9b59b6")],
         "Batter run value per 100 pitches", "runs"),
    ]

    for slot, series, title, ylabel in panels:
        ax = fig.add_subplot(slot)
        drew = False
        for col, label, color in series:
            if col not in df or df[col].dropna().empty:
                continue
            ax.plot(df["day"], df[col], color=color, alpha=0.28, linewidth=1.0,
                    marker="o", markersize=2.5)
            ax.plot(df["day"], df[f"{col}_roll"], color=color, linewidth=2.4,
                    label=f"{label} ({WINDOW}-day)")
            drew = True
        if not drew:
            note(ax, "No data")
            continue
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=9, frameon=False)
        ax.grid(True)
        ax.tick_params(axis="x", rotation=25, labelsize=8)

    total_days = int(df["pitches"].count())
    fig.text(0.5, 0.005,
             f"Faint line = per-day value, solid = {WINDOW}-day rolling mean over "
             f"{total_days} days with pitches. Days with few pitches are noisy by nature.",
             ha="center", fontsize=9, color=theme.MUTED, style="italic")
    return save(fig, ctx, "14_trends.png")


def volume(ctx):
    """Where the sample actually comes from — mode, difficulty, and pace."""
    if ctx.empty:
        return empty_figure(ctx, "15_volume.png", "Sample Composition")

    fig = plt.figure(figsize=(16, 5.6))
    figure_title(fig, "Sample Composition", ctx, y=1.03)
    gs = GridSpec(1, 3, figure=fig, wspace=0.28)

    ax = fig.add_subplot(gs[0, 0])
    counts = ctx.pitches["game_mode"].value_counts()
    ax.barh([str(i) for i in counts.index], counts.to_numpy(), color="#3498db",
            edgecolor=theme.BG)
    for i, v in enumerate(counts.to_numpy()):
        ax.text(v * 1.01, i, f"{v:,}", va="center", fontsize=9)
    ax.set_xlim(0, counts.max() * 1.18)
    ax.set_title("Pitches by mode", fontweight="bold")
    ax.grid(True, axis="x")

    ax = fig.add_subplot(gs[0, 1])
    counts = ctx.pitches["difficulty"].value_counts()
    ax.barh([str(i) for i in counts.index], counts.to_numpy(), color="#9b59b6",
            edgecolor=theme.BG)
    for i, v in enumerate(counts.to_numpy()):
        ax.text(v * 1.01, i, f"{v:,}", va="center", fontsize=9)
    ax.set_xlim(0, counts.max() * 1.18)
    ax.set_title("Pitches by difficulty", fontweight="bold")
    ax.grid(True, axis="x")

    ax = fig.add_subplot(gs[0, 2])
    per_day = ctx.pitches.groupby("day").size()
    ax.fill_between(per_day.index, per_day.to_numpy(), color="#2ecc71", alpha=0.55)
    ax.plot(per_day.index, per_day.to_numpy(), color="#2ecc71", linewidth=1.2)
    ax.set_title("Pitches per day", fontweight="bold")
    ax.tick_params(axis="x", rotation=25, labelsize=8)
    ax.grid(True)

    return save(fig, ctx, "15_volume.png")
