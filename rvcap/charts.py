from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from rvcap.metrics import HistoryPoint

NAVY = "#1f3654"
USED = "#2f5d8a"
FREE = "#a8c0d4"
FORECAST = "#c47b2d"
MUTED = "#5c6b7a"
WARN = "#b8860b"
CRIT = "#8c2f2f"


def _style(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.label.set_color(MUTED)
    ax.xaxis.label.set_color(MUTED)
    ax.title.set_color(NAVY)
    ax.grid(axis="y", color="#e6e6e6", linewidth=0.6)


def _date_axis(ax, start: date, end: date) -> None:
    span = max((end - start).days, 1)
    interval = 1 if span <= 35 else 2 if span <= 120 else 4
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.FR, interval=interval))


def _label_points(ax, dates: list, values: list[float], fmt: str, *, above_only: bool = False) -> None:
    count = max(len(dates), 1)
    for i, (when, value) in enumerate(zip(dates, values)):
        above = True if above_only else i % 2 == 0
        dx = (i - (count - 1) / 2) * (8 if count <= 6 else 0)
        ax.annotate(
            fmt.format(value),
            (when, value),
            textcoords="offset points",
            xytext=(dx, 8 if above else -12),
            ha="center",
            va="bottom" if above else "top",
            color=NAVY,
            fontsize=8,
            bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": 0.85},
        )


def _forecast_series(last_date: date, last_value: float, forecast: pd.DataFrame | None, scale: float = 1.0):
    if forecast is None or forecast.empty:
        return None
    values = [max(0.0, float(v) * scale) for v in forecast["value"]]
    return [last_date, *forecast["date"].tolist()], [max(0.0, last_value), *values]


def _padded_ylim(values: list[float], *, floor: float = 0.0, min_span_ratio: float = 0.08, min_span: float = 20.0):
    lo = min(values)
    hi = max(values)
    span = max(hi - lo, abs(hi) * min_span_ratio, min_span)
    mid = (lo + hi) / 2
    return max(floor, mid - span / 2), mid + span / 2


def memory_chart(history: list[HistoryPoint], forecast: pd.DataFrame | None, path: Path) -> Path | None:
    if not history:
        return None
    fig, ax = plt.subplots(figsize=(10.2, 3.2), dpi=140)
    dates = [p.snapshot_date for p in history]
    used = [p.memory_used_gib / 1024 for p in history]
    total = [p.memory_total_gib / 1024 for p in history]
    ax.fill_between(dates, used, color=USED, alpha=0.85, label="Used TiB")
    ax.plot(dates, used, color=USED, linewidth=1.6, marker="o", markersize=5)
    ax.plot(dates, total, color=NAVY, linewidth=1.4, marker="o", markersize=4, label="Installed TiB")
    _label_points(ax, dates, used, "{:.1f}", above_only=True)
    end = dates[-1]
    series = _forecast_series(dates[-1], used[-1], forecast, scale=1 / 1024)
    if series is not None:
        end = series[0][-1]
        ax.plot(series[0], series[1], color=FORECAST, linestyle="--", linewidth=1.4, label="Used forecast")
    _date_axis(ax, dates[0], end)
    ax.set_title("Memory used vs installed")
    ax.set_ylabel("TiB")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def cpu_chart(history: list[HistoryPoint], forecast: pd.DataFrame | None, path: Path) -> Path | None:
    if not history:
        return None
    fig, ax = plt.subplots(figsize=(10.2, 3.2), dpi=140)
    dates = [p.snapshot_date for p in history]
    weighted = [p.cpu_used_weighted_pct for p in history]
    average = [p.cpu_used_avg_pct for p in history]
    if len(dates) == 1:
        ax.bar([-0.18], weighted, width=0.32, color=USED, label="Weighted CPU %")
        ax.bar([0.18], average, width=0.32, color=FREE, label="Unweighted avg %")
        ax.set_xticks([0])
        ax.set_xticklabels([dates[0].isoformat()])
        ax.annotate(f"{weighted[0]:.1f}%", (-0.18, weighted[0]), textcoords="offset points", xytext=(0, 6), ha="center", color=NAVY, fontsize=8)
    else:
        ax.plot(dates, weighted, color=USED, linewidth=1.8, marker="o", markersize=5, label="Weighted CPU %")
        ax.plot(dates, average, color=FREE, linewidth=1.2, marker="o", markersize=4, label="Unweighted avg %")
        _label_points(ax, dates, weighted, "{:.1f}%", above_only=True)
        end = dates[-1]
        series = _forecast_series(dates[-1], weighted[-1], forecast)
        if series is not None:
            end = series[0][-1]
            ax.plot(series[0], series[1], color=FORECAST, linestyle="--", linewidth=1.4, label="Weighted forecast")
        _date_axis(ax, dates[0], end)
    ax.set_ylim(0, 100)
    ax.set_title("Host CPU utilization")
    ax.set_ylabel("%")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def vm_chart(history: list[HistoryPoint], forecast: pd.DataFrame | None, path: Path) -> Path | None:
    if not history:
        return None
    fig, ax = plt.subplots(figsize=(10.2, 3.2), dpi=140)
    dates = [p.snapshot_date for p in history]
    counts = [p.powered_on_vms for p in history]
    ax.plot(dates, counts, color=USED, linewidth=1.8, marker="o", markersize=5, label="Powered-on VMs")
    _label_points(ax, dates, [float(v) for v in counts], "{:.0f}")
    end = dates[-1]
    plotted = [float(v) for v in counts]
    series = _forecast_series(dates[-1], float(counts[-1]), forecast)
    if series is not None:
        end = series[0][-1]
        plotted.extend(series[1][1:])
        ax.plot(series[0], series[1], color=FORECAST, linestyle="--", linewidth=1.4, label="Forecast")
    _date_axis(ax, dates[0], end)
    ax.set_ylim(*_padded_ylim(plotted))
    ax.set_title("Powered-on VM count")
    ax.set_ylabel("VMs")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def datastore_free_chart(
    ds: pd.DataFrame,
    path: Path,
    n: int = 12,
    warn_pct: float = 20.0,
    crit_pct: float = 10.0,
) -> Path | None:
    if ds is None or ds.empty:
        return None
    top = ds.nsmallest(n, "Free %")
    fig, ax = plt.subplots(figsize=(10.2, 3.6), dpi=140)
    labels = [str(x)[:42] for x in top["Datastore"]]
    values = top["Free %"].iloc[::-1].tolist()
    colors = [CRIT if v < crit_pct else WARN if v < warn_pct else USED for v in values]
    ax.barh(labels[::-1], values, color=colors)
    ax.axvline(warn_pct, color=WARN, linestyle="--", linewidth=1, label=f"{warn_pct:.0f}% free")
    ax.axvline(crit_pct, color=CRIT, linestyle="--", linewidth=1, label=f"{crit_pct:.0f}% free")
    ax.set_xlabel("Free %")
    ax.set_title("Shared datastores with least free space")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def cluster_chart(
    hosts: pd.DataFrame,
    path: Path,
    mem_warn: float = 45.0,
    mem_crit: float = 80.0,
) -> Path | None:
    if hosts is None or hosts.empty or "Cluster" not in hosts.columns:
        return None
    active = hosts[hosts["Maintenance"] != "Yes"] if "Maintenance" in hosts.columns else hosts
    if active.empty:
        active = hosts
    rows = []
    for cluster, group in active.groupby(active["Cluster"].fillna("").astype(str)):
        ram = float(group["Memory GiB"].sum())
        mem_pct = float((group["Memory GiB"] * group["Memory %"]).sum() / ram) if ram else 0.0
        rows.append((cluster or "n/a", mem_pct))
    if not rows:
        return None
    rows.sort(key=lambda row: row[1])
    fig, ax = plt.subplots(figsize=(10.2, 2.8), dpi=140)
    labels = [name[:42] for name, _pct in rows]
    values = [pct for _name, pct in rows]
    colors = [CRIT if v >= mem_crit else WARN if v >= mem_warn else USED for v in values]
    ax.barh(labels, values, color=colors)
    ax.axvline(mem_warn, color=WARN, linestyle="--", linewidth=1, label=f"{mem_warn:.0f}% RAM")
    ax.axvline(mem_crit, color=CRIT, linestyle="--", linewidth=1, label=f"{mem_crit:.0f}% RAM")
    ax.set_xlim(0, 100)
    ax.set_xlabel("Capacity-weighted RAM %")
    ax.set_title("Cluster memory, excluding hosts in maintenance")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def snapshot_chart(history: list[HistoryPoint], path: Path) -> Path | None:
    if not history or not hasattr(history[0], "snapshot_vms"):
        return None
    fig, ax = plt.subplots(figsize=(10.2, 2.6), dpi=140)
    dates = [p.snapshot_date for p in history]
    counts = [float(p.snapshot_vms) for p in history]
    ax.plot(dates, counts, color=USED, linewidth=1.8, marker="o", markersize=5, label="VMs with snapshots")
    _label_points(ax, dates, counts, "{:.0f}")
    _date_axis(ax, dates[0], dates[-1])
    if max(counts) - min(counts) < 5:
        ax.set_ylim(*_padded_ylim(counts, min_span=10))
    ax.set_title("VMs with at least one snapshot")
    ax.set_ylabel("VMs")
    ax.legend(frameon=False, fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
