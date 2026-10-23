"""Author-only generation. Neither source values nor this file enter the agent image."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import MultipleLocator
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "environment/app/report"
REGIONS = ["Alder", "Birch", "Cedar", "Delta"]
DATA = {
    "Alder": {
        "rate": [200, 200, 300, 300, 200, 200, 300, 300],
        "failure_pct": [8, 8, 7, 7, 6, 6, 5, 5],
        "p95_ms": [380, 370, 360, 350, 340, 320, 330, 350]},
    "Birch": {
        "rate": [1800, 2000, 1800, 2200, 2000, 2400, 2200, 2400],
        "failure_pct": [4, 4, 3.5, 3.5, 3, 3, 2.5, 2.5],
        "p95_ms": [460, 450, 440, 430, 420, 410, 420, 440]},
    "Cedar": {
        "rate": [800, 1000, 800, 1000, 800, 1000, None, None],
        "failure_pct": [1, 1.5, 1, 1.5, 1, 1.5, None, None],
        "p95_ms": [240, 250, 240, 250, 260, 270, None, None]},
    "Delta": {
        "rate": [1000, 1200, 1000, 1200, 1000, 1200, 1000, 1200],
        "failure_pct": [10, 10, 3, 3, 5, 5, 5, 5],
        "p95_ms": [600, 580, 340, 350, 360, 360, 370, 390]},
}
COLORS = ["#215a9b", "#c45f00", "#177653", "#794da2"]
LABELS = [f"W{i+1}\n{8+i//2:02d}:{30*(i%2):02d}" for i in range(8)]
SOURCES = {"rate": "P1", "failure_pct": "P2", "p95_ms": "P3", "status": "P4"}


def status(region, index):
    if region == "Cedar" and index >= 6:
        return "unknown"
    return "maintenance" if region == "Delta" and index < 2 else "normal"


def save(fig, filename):
    path = OUT / filename
    fig.savefig(path, dpi=120, facecolor="white")
    plt.close(fig)
    # Remove all metadata; only pixels, not data arrays, enter the report.
    with Image.open(path) as image:
        pixels = Image.fromarray(np.asarray(image.convert("RGB")))
        pixels.save(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 13, "axes.titlesize": 17, "axes.labelsize": 13,
                         "font.family": "DejaVu Sans"})
    x = np.arange(8)
    for metric, panel, title, ylabel in (
        ("rate", "P1", "Mean request arrival rate", "Requests / minute"),
        ("failure_pct", "P2", "Failed requests / all requests", "Failure percentage (%)"),
    ):
        fig, axes = plt.subplots(2, 2, figsize=(15, 10), layout="constrained")
        fig.suptitle(f"{panel} | {title}\n14 September 2026 | 30-minute windows | UTC", fontsize=21)
        for index, (region, ax) in enumerate(zip(REGIONS, axes.flat)):
            values = DATA[region][metric]
            numeric = [np.nan if v is None else v for v in values]
            if metric == "rate":
                ax.bar(x, numeric, width=.62, color=COLORS[index], edgecolor="#182533")
                top, major, minor = [(400, 100, 50), (3000, 500, 100),
                                     (1500, 250, 50), (1500, 250, 50)][index]
                ax.set_ylim(0, top)
                ax.yaxis.set_major_locator(MultipleLocator(major))
                ax.yaxis.set_minor_locator(MultipleLocator(minor))
            else:
                ax.plot(x, numeric, "-o", color=COLORS[index], lw=2.5, markersize=8)
                ax.set_ylim(0, 11)
                ax.yaxis.set_major_locator(MultipleLocator(1))
                ax.yaxis.set_minor_locator(MultipleLocator(.5))
            ax.set_title(region, color=COLORS[index], fontweight="bold")
            ax.set_ylabel(ylabel)
            ax.set_xticks(x, LABELS)
            ax.set_xlim(-.6, 7.6)
            ax.grid(axis="y", which="major", alpha=.45)
            ax.grid(axis="y", which="minor", alpha=.2, linestyle=":")
            ax.set_axisbelow(True)
            for i, value in enumerate(values):
                if value is None:
                    ax.axvspan(i-.45, i+.45, facecolor="#eeeeee", hatch="//", alpha=.7)
                    ax.text(i, ax.get_ylim()[1]*.5, "UNKNOWN", rotation=90,
                            ha="center", va="center", fontsize=11)
        fig.supxlabel("Window ID and start time. Each plotted value summarizes the full window.", fontsize=13)
        save(fig, f"{panel}-{'traffic' if metric == 'rate' else 'failures'}.png")

    fig, ax = plt.subplots(figsize=(15, 7), layout="constrained")
    values = np.array([[np.nan if v is None else v for v in DATA[r]["p95_ms"]] for r in REGIONS])
    image = ax.imshow(values, cmap="YlOrRd", vmin=200, vmax=650, aspect="auto")
    ax.set_title("P3 | Interval p95 latency (milliseconds)\nNumerical labels are authoritative", pad=24, fontsize=22)
    ax.set_xticks(x, LABELS)
    ax.set_yticks(range(4), REGIONS)
    for row in range(4):
        for col in range(8):
            value = values[row, col]
            text = "UNKNOWN" if np.isnan(value) else str(int(value))
            if np.isnan(value):
                ax.add_patch(Rectangle((col-.5, row-.5), 1, 1, facecolor="#eee", hatch="//"))
            ax.text(col, row, text, ha="center", va="center", fontsize=16,
                    color="white" if not np.isnan(value) and value >= 500 else "#121212")
    fig.colorbar(image, ax=ax, label="Milliseconds", shrink=.8)
    ax.set_xlabel("30-minute windows | 14 September 2026 | UTC", labelpad=20)
    save(fig, "P3-latency.png")

    fig, ax = plt.subplots(figsize=(15, 7), layout="constrained")
    states = ["normal", "maintenance", "unknown"]
    colors = ["#ccebdc", "#ffe0a6", "#e1e3e7"]
    matrix = [[states.index(status(r, i)) for i in range(8)] for r in REGIONS]
    ax.imshow(matrix, cmap=ListedColormap(colors), vmin=0, vmax=2, aspect="auto")
    for j, region in enumerate(REGIONS):
        for i in range(8):
            s = status(region, i)
            if s != "normal":
                ax.add_patch(Rectangle((i-.5, j-.5), 1, 1, fill=False, hatch="//",
                                       edgecolor="#8a8a8a"))
            ax.text(i, j, s.upper(), ha="center", va="center", fontsize=12, fontweight="bold")
    ax.axvline(3.5, color="#222", lw=2, ls="--")
    ax.text(3.5, -.85, "Deployment: 10:00 UTC", ha="center", fontsize=16,
            bbox={"facecolor": "white", "edgecolor": "#333"})
    ax.set_ylim(3.5, -1.2)
    ax.set_xticks(x, LABELS)
    ax.set_yticks(range(4), REGIONS)
    ax.set_title("P4 | Operational status and event timing", fontsize=22, pad=30)
    ax.set_xlabel("14 September 2026 | Each cell covers one 30-minute window", labelpad=20)
    ax.legend(handles=[Patch(facecolor=color, label=s.upper()) for s, color in zip(states, colors)],
              loc="upper center", bbox_to_anchor=(.5, -.18), ncol=3)
    save(fig, "P4-status.png")

    records = []
    for region in REGIONS:
        for i in range(8):
            rec = {"region": region, "window": f"W{i+1}", "status": status(region, i),
                   "sources": SOURCES}
            for metric in ("rate", "failure_pct", "p95_ms"):
                value = DATA[region][metric][i]
                rec[metric] = value
            records.append(rec)
    (ROOT / "tests").mkdir(exist_ok=True)
    (ROOT / "tests/truth.json").write_text(json.dumps({"records": records}, indent=2)+"\n")


if __name__ == "__main__":
    main()
