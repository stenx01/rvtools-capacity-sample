from __future__ import annotations

from rvcap.config import Thresholds
from rvcap.metrics import Pack, datastore_table, guest_fs_hotspots, host_table, kpis


def status_with_reason(k: dict, thr: Thresholds) -> tuple[str, list[str]]:
    """Overall RAG is cluster capacity risk, not hygiene or the 45% host watch line."""
    red: list[str] = []
    if k["datastores_crit"]:
        red.append(f"{k['datastores_crit']} datastore(s) below {thr.datastore_free_crit_pct:.0f}% free")
    if k["hosts_mem_crit"]:
        red.append(f"{k['hosts_mem_crit']} host(s) at or above {thr.host_mem_crit_pct:.0f}% RAM")
    if k["balloon_gib"] > 1:
        red.append(f"balloon {k['balloon_gib']} GiB")
    if k["swapped_gib"] > 1:
        red.append(f"swapped {k['swapped_gib']} GiB")
    if red:
        return "RED", red

    amber: list[str] = []
    if k["datastores_warn"]:
        amber.append(f"{k['datastores_warn']} datastore(s) below {thr.datastore_free_warn_pct:.0f}% free")
    if k["hosts_cpu_warn"]:
        amber.append(f"{k['hosts_cpu_warn']} host(s) at or above {thr.host_cpu_warn_pct:.0f}% CPU")
    if amber:
        return "AMBER", amber

    extras: list[str] = []
    if k["hosts_mem_warn"]:
        extras.append(
            f"{k['hosts_mem_warn']} host(s) at or above {thr.host_mem_warn_pct:.0f}% RAM — listed in section 1, not enough for AMBER (no balloon/swap, none at {thr.host_mem_crit_pct:.0f}%)."
        )
    if k["snapshot_vms"]:
        extras.append(
            f"{k['snapshot_vms']} VM(s) have snapshots — hygiene in section 7, not a capacity status."
        )
    if extras:
        return "GREEN", extras
    return "GREEN", ["No cluster-level capacity thresholds breached."]


def _status(k: dict, thr: Thresholds) -> str:
    return status_with_reason(k, thr)[0]


def executive_summary(pack: Pack) -> list[str]:
    k = kpis(pack)
    thr = pack.config.thresholds
    status, reasons = status_with_reason(k, thr)
    lines = [
        f"Overall status {status} as of {pack.as_of.isoformat()} across {len(k['vcenters'])} vCenter(s): {', '.join(k['vcenters']) or 'n/a'}.",
        *reasons,
        f"{k['powered_on_vms']} powered-on VMs ({k['total_vms']} excluding templates) on {k['hosts']} hosts ({k['hosts_maintenance']} in maintenance).",
        f"Memory {k['memory_used_gib']:.0f} / {k['memory_total_gib']:.0f} GiB ({k['memory_used_pct']}%). CPU {k['cpu_weighted_pct']}% weighted by cores (simple average {k['cpu_avg_pct']}%).",
        f"Shared datastore {k['datastore_used_tib']:.1f} / {k['datastore_capacity_tib']:.1f} TiB used ({k['datastore_free_pct']}% free).",
    ]
    if k["history_points"] < thr.min_points_for_forecast:
        lines.append(
            f"History has {k['history_points']} weekly snapshot(s). Forecast charts appear after {thr.min_points_for_forecast} Friday dumps."
        )
    else:
        lines.append(f"Trend uses {k['history_points']} weekly snapshots; linear forecast is {thr.forecast_periods} weeks ahead.")
    return lines


def section_notes(pack: Pack) -> dict[str, list[str]]:
    k = kpis(pack)
    thr = pack.config.thresholds
    ht = host_table(pack)
    ds = datastore_table(pack)
    notes: dict[str, list[str]] = {}

    host_notes: list[str] = []
    if ht.empty:
        host_notes.append("No host rows in this snapshot.")
    else:
        if k["hosts_mem_warn"]:
            names = ht.loc[ht["Memory %"] >= thr.host_mem_warn_pct, "Host"].head(8).tolist()
            host_notes.append(
                f"{k['hosts_mem_warn']} host(s) at or above {thr.host_mem_warn_pct:.0f}% RAM: {', '.join(str(n) for n in names)}."
            )
        else:
            host_notes.append(f"No host above the {thr.host_mem_warn_pct:.0f}% memory watch line.")
        if k["hosts_cpu_warn"]:
            names = ht.loc[ht["CPU %"] >= thr.host_cpu_warn_pct, "Host"].head(8).tolist()
            host_notes.append(
                f"{k['hosts_cpu_warn']} host(s) at or above {thr.host_cpu_warn_pct:.0f}% CPU: {', '.join(str(n) for n in names)}."
            )
        else:
            host_notes.append(f"No host above the {thr.host_cpu_warn_pct:.0f}% CPU watch line.")
        if k["hosts_maintenance"]:
            host_notes.append(f"{k['hosts_maintenance']} host(s) in maintenance — exclude them from spare-capacity claims.")
        if k["balloon_gib"] or k["swapped_gib"]:
            host_notes.append(
                f"Guest memory pressure: balloon {k['balloon_gib']} GiB, swapped {k['swapped_gib']} GiB. Investigate those VMs before adding workload."
            )
        else:
            host_notes.append("No balloon or swap in vMemory — hosts are not in RAM distress even if some sit above 45%.")
        hot_ratio = ht[ht["vCPU/core"] >= thr.vcpu_per_core_warn]
        if not hot_ratio.empty:
            host_notes.append(
                f"{len(hot_ratio)} host(s) at ≥ {thr.vcpu_per_core_warn:.1f} vCPU/core. That is consolidation, not necessarily CPU saturation."
            )
    notes["hosts"] = host_notes

    mem_notes: list[str] = [
        f"Installed memory is {k['memory_total_gib']:.0f} GiB with {k['memory_used_pct']}% utilized (capacity-weighted from host counters).",
    ]
    if len(pack.history) >= 2:
        prev, cur = pack.history[-2], pack.history[-1]
        delta = cur.memory_used_gib - prev.memory_used_gib
        mem_notes.append(
            f"Used RAM changed {delta:+.0f} GiB versus {prev.snapshot_date.isoformat()} ({prev.memory_used_gib:.0f} → {cur.memory_used_gib:.0f})."
        )
    else:
        mem_notes.append("Need another Friday dump before week-on-week memory movement is meaningful.")
    if pack.mem_forecast is None:
        mem_notes.append("No memory forecast yet — keep ingesting weekly extracts.")
    else:
        last = pack.mem_forecast.iloc[-1]
        mem_notes.append(
            f"Linear forecast of used RAM in {len(pack.mem_forecast)} weeks: {last['value']:.0f} GiB. Treat as a trend, not a booking."
        )
    notes["memory"] = mem_notes

    cpu_notes: list[str] = [
        f"Capacity-weighted CPU is {k['cpu_weighted_pct']}% (better than averaging host % columns, which is {k['cpu_avg_pct']}% here).",
    ]
    if pack.cpu_forecast is None:
        cpu_notes.append("No CPU forecast yet.")
    else:
        last = pack.cpu_forecast.iloc[-1]
        raw = float(last["value"])
        shown = max(0.0, raw)
        if raw < 0:
            cpu_notes.append(
                f"Linear forecast of weighted CPU in {len(pack.cpu_forecast)} weeks falls below zero ({raw:.1f}%). The chart stops at 0%."
            )
        else:
            cpu_notes.append(f"Linear forecast of weighted CPU in {len(pack.cpu_forecast)} weeks: {shown:.1f}%.")
    notes["cpu"] = cpu_notes

    ds_notes: list[str] = []
    if ds.empty:
        ds_notes.append("No shared datastores after excluding host-local / depot / ISO volumes.")
    else:
        tight = ds.iloc[0]
        ds_notes.append(
            f"Tightest shared datastore is {tight['Datastore']} at {tight['Free %']:.0f}% free ({tight['Free TiB']:.1f} TiB of {tight['Capacity TiB']:.1f} TiB)."
        )
        if k["datastores_crit"]:
            ds_notes.append(f"{k['datastores_crit']} datastore(s) below {thr.datastore_free_crit_pct:.0f}% free — treat as critical.")
        elif k["datastores_warn"]:
            ds_notes.append(f"{k['datastores_warn']} datastore(s) below {thr.datastore_free_warn_pct:.0f}% free — plan growth or cleanup.")
        else:
            ds_notes.append(f"No shared datastore below the {thr.datastore_free_warn_pct:.0f}% free warning.")
        over = ds[ds["Provisioned TiB"] > ds["Capacity TiB"]]
        if not over.empty:
            ds_notes.append(f"{len(over)} datastore(s) are thin-overprovisioned (provisioned > capacity). Watch in-use, not provisioned.")
        under = ds[ds["Free %"] >= thr.datastore_underutil_pct]
        if not under.empty:
            ds_notes.append(
                f"{len(under)} shared datastore(s) still above {thr.datastore_underutil_pct:.0f}% free — possible stranded capacity, not host-local scratch."
            )
    notes["datastore"] = ds_notes

    crit = guest_fs_hotspots(pack, thr.guest_fs_crit_pct)
    warn = guest_fs_hotspots(pack, thr.guest_fs_warn_pct)
    fs_notes: list[str] = [
        "Tiny volumes (/boot, < 1 GiB) are excluded so the list is not dominated by small system mounts.",
    ]
    if crit.empty:
        fs_notes.append(f"No guest filesystem ≥ 1 GiB below {thr.guest_fs_crit_pct:.0f}% free.")
    else:
        sample = ", ".join(
            f"{row['VM']} {row['Disk']} ({row['Free %']:.0f}%)" for _, row in crit.head(5).iterrows()
        )
        fs_notes.append(f"{len(crit)} guest filesystem(s) ≤ {thr.guest_fs_crit_pct:.0f}% free. Worst: {sample}.")
    if len(warn) > len(crit):
        fs_notes.append(f"{len(warn)} guest filesystem(s) ≤ {thr.guest_fs_warn_pct:.0f}% free including the critical set.")
    notes["guest_fs"] = fs_notes

    vm_notes: list[str] = [
        f"{k['powered_on_vms']} powered-on VMs this snapshot ({k['templates']} templates excluded from the count).",
    ]
    if len(pack.history) >= 2:
        prev, cur = pack.history[-2], pack.history[-1]
        delta = cur.powered_on_vms - prev.powered_on_vms
        vm_notes.append(f"Powered-on count {delta:+d} versus {prev.snapshot_date.isoformat()}.")
        if abs(delta) > max(20, 0.05 * max(prev.powered_on_vms, 1)):
            vm_notes.append(
                "Large jump — confirm every vCenter dump arrived this week before treating it as real growth or shrinkage."
            )
    if pack.vm_forecast is None:
        vm_notes.append("VM-count forecast needs more weekly points.")
    notes["vms"] = vm_notes

    extra: list[str] = []
    if k["snapshot_vms"]:
        extra.append(
            f"{k['snapshot_vms']} VM(s) still have snapshots ({k['snapshot_rows']} snapshot files). Age them out unless they are active change windows."
        )
    if not pack.tools.empty and "Tools" in pack.tools.columns:
        bad = pack.tools[pack.tools["Tools"].astype(str).isin(["toolsNotInstalled", "toolsNotRunning"])]
        if not bad.empty:
            extra.append(f"{len(bad)} VM(s) with Tools not running or not installed.")
    notes["hygiene"] = extra
    return notes


def facts_payload(pack: Pack) -> dict:
    k = kpis(pack)
    status, reasons = status_with_reason(k, pack.config.thresholds)
    return {
        "kpis": k,
        "status": status,
        "status_reasons": reasons,
        "executive_summary": executive_summary(pack),
        "section_notes": section_notes(pack),
        "exceptions": {
            "hosts_mem": host_table(pack)
            .loc[lambda d: d["Memory %"] >= pack.config.thresholds.host_mem_warn_pct]
            .head(20)
            .to_dict("records")
            if not host_table(pack).empty
            else [],
            "datastores_warn": datastore_table(pack)
            .loc[lambda d: d["Free %"] < pack.config.thresholds.datastore_free_warn_pct]
            .head(20)
            .to_dict("records")
            if not datastore_table(pack).empty
            else [],
            "guest_fs_crit": guest_fs_hotspots(
                pack, pack.config.thresholds.guest_fs_crit_pct, limit=20
            ).to_dict("records"),
        },
    }
