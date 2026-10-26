from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from rvcap.config import DEFAULT, ReportConfig, Thresholds
from rvcap.forecast import linear_forecast
from rvcap.util import boolish
from rvcap.warehouse import load_entity


def _num(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def _is_true(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return boolish(df[column].fillna(False))


def _exclude_name(name: str, substrings: tuple[str, ...]) -> bool:
    text = (name or "").lower()
    return any(token.lower() in text for token in substrings)


def _mount_excluded(mount: str, excluded: tuple[str, ...]) -> bool:
    text = (mount or "").strip().rstrip("\\").lower()
    return any(text == token.lower() or text.startswith(token.lower() + "/") for token in excluded)


@dataclass
class HistoryPoint:
    snapshot_date: date
    memory_used_gib: float
    memory_total_gib: float
    cpu_used_weighted_pct: float
    cpu_used_avg_pct: float
    powered_on_vms: int
    total_vms: int
    datastore_used_tib: float
    datastore_capacity_tib: float
    snapshot_vms: int = 0


@dataclass
class Pack:
    as_of: date
    vcenters: list[str]
    environments: list[str]
    current: pd.DataFrame
    history: list[HistoryPoint]
    hosts: pd.DataFrame
    clusters: pd.DataFrame
    datastores: pd.DataFrame
    guest_fs: pd.DataFrame
    snapshots: pd.DataFrame
    memory: pd.DataFrame
    tools: pd.DataFrame
    health: pd.DataFrame
    catalog_rows: pd.DataFrame
    mem_forecast: pd.DataFrame | None = None
    cpu_forecast: pd.DataFrame | None = None
    vm_forecast: pd.DataFrame | None = None
    config: ReportConfig = field(default_factory=lambda: DEFAULT)


def _current_slice(df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    if df.empty or "_snapshot_date" not in df.columns:
        return df
    return df[df["_snapshot_date"] == as_of].copy()


def _history(
    vinfo: pd.DataFrame,
    vhost: pd.DataFrame,
    vds: pd.DataFrame,
    vsnap: pd.DataFrame,
    cfg: ReportConfig,
) -> list[HistoryPoint]:
    if vinfo.empty:
        return []
    points: list[HistoryPoint] = []
    for snap, info in vinfo.groupby("_snapshot_date", sort=True):
        hosts = vhost[vhost["_snapshot_date"] == snap] if not vhost.empty else pd.DataFrame()
        stores = vds[vds["_snapshot_date"] == snap] if not vds.empty else pd.DataFrame()
        templates = _is_true(info, "Template") if cfg.exclude_templates_from_vm_count else False
        powered = info["Powerstate"].astype(str).str.lower().eq("poweredon")
        if isinstance(templates, pd.Series):
            powered_on = int((powered & ~templates).sum())
            total = int((~templates).sum())
        else:
            powered_on = int(powered.sum())
            total = len(info)

        mem_total = float(_num(hosts, "# Memory").sum()) / 1024 if not hosts.empty else 0.0
        mem_used = float((_num(hosts, "# Memory") * _num(hosts, "Memory usage %") / 100.0).sum()) / 1024 if not hosts.empty else 0.0
        cores = _num(hosts, "# Cores") if not hosts.empty else pd.Series(dtype=float)
        cpu_pct = _num(hosts, "CPU usage %") if not hosts.empty else pd.Series(dtype=float)
        cpu_avg = float(cpu_pct.mean()) if len(cpu_pct) else 0.0
        cpu_weighted = float((cpu_pct * cores).sum() / cores.sum()) if cores.sum() else cpu_avg

        if not stores.empty:
            keep = ~stores["Name"].astype(str).map(lambda n: _exclude_name(n, cfg.exclude_datastore_substrings))
            stores = stores[keep]
            cap = float(_num(stores, "Capacity MiB").sum()) / 1024 / 1024
            used = float(_num(stores, "In Use MiB").sum()) / 1024 / 1024
        else:
            cap = used = 0.0

        snap_rows = vsnap[vsnap["_snapshot_date"] == snap] if not vsnap.empty and "_snapshot_date" in vsnap.columns else pd.DataFrame()
        snapshot_vms = int(snap_rows["VM"].nunique()) if not snap_rows.empty and "VM" in snap_rows.columns else 0

        points.append(
            HistoryPoint(
                snapshot_date=snap,
                memory_used_gib=mem_used,
                memory_total_gib=mem_total,
                cpu_used_weighted_pct=cpu_weighted,
                cpu_used_avg_pct=cpu_avg,
                powered_on_vms=powered_on,
                total_vms=total,
                datastore_used_tib=used,
                datastore_capacity_tib=cap,
                snapshot_vms=snapshot_vms,
            )
        )
    return points


def build_pack(as_of: date, cfg: ReportConfig | None = None) -> Pack:
    cfg = cfg or DEFAULT
    vinfo = load_entity("vInfo", through=as_of)
    vhost = load_entity("vHost", through=as_of)
    vcluster = load_entity("vCluster", through=as_of)
    vds = load_entity("vDatastore", through=as_of)
    vpart = load_entity("vPartition", through=as_of)
    vsnap = load_entity("vSnapshot", through=as_of)
    vmem = load_entity("vMemory", through=as_of)
    vtools = load_entity("vTools", through=as_of)
    vhealth = load_entity("vHealth", through=as_of)
    from rvcap.warehouse import load_catalog

    catalog = load_catalog()
    if not catalog.empty:
        catalog = catalog[catalog["snapshot_date"] <= as_of]

    current_info = _current_slice(vinfo, as_of)
    current_hosts = _current_slice(vhost, as_of)
    current_ds = _current_slice(vds, as_of)
    current_part = _current_slice(vpart, as_of)

    if not current_ds.empty:
        current_ds = current_ds.copy()
        current_ds["_ignored"] = current_ds["Name"].astype(str).map(
            lambda n: _exclude_name(n, cfg.exclude_datastore_substrings)
        )
    if not current_part.empty:
        current_part = current_part.copy()
        current_part["_tiny"] = _num(current_part, "Capacity MiB") < cfg.thresholds.min_guest_fs_mib
        current_part["_excluded_mount"] = current_part["Disk"].astype(str).map(
            lambda m: _mount_excluded(m, cfg.exclude_guest_mounts)
        )

    history = _history(vinfo, vhost, vds, vsnap, cfg)
    dates = [p.snapshot_date for p in history]
    thr = cfg.thresholds
    mem_fc = linear_forecast(dates, [p.memory_used_gib for p in history], thr.forecast_periods)
    cpu_fc = linear_forecast(dates, [p.cpu_used_weighted_pct for p in history], thr.forecast_periods)
    vm_fc = linear_forecast(dates, [p.powered_on_vms for p in history], thr.forecast_periods)

    vcenters = sorted(set(current_info["_vcenter"].dropna().astype(str))) if not current_info.empty else []
    envs = sorted(set(current_info["_environment"].dropna().astype(str))) if not current_info.empty else []
    if not vcenters and not catalog.empty:
        latest = catalog[catalog["snapshot_date"] == as_of]
        vcenters = sorted(set(latest["vcenter"].astype(str)))
        envs = sorted(set(latest["environment"].astype(str)))

    return Pack(
        as_of=as_of,
        vcenters=vcenters,
        environments=envs,
        current=current_info,
        history=history,
        hosts=current_hosts,
        clusters=_current_slice(vcluster, as_of),
        datastores=current_ds,
        guest_fs=current_part,
        snapshots=_current_slice(vsnap, as_of),
        memory=_current_slice(vmem, as_of),
        tools=_current_slice(vtools, as_of),
        health=_current_slice(vhealth, as_of),
        catalog_rows=catalog,
        mem_forecast=mem_fc,
        cpu_forecast=cpu_fc,
        vm_forecast=vm_fc,
        config=cfg,
    )


def host_table(pack: Pack) -> pd.DataFrame:
    df = pack.hosts
    if df.empty:
        return df
    out = pd.DataFrame(
        {
            "Host": df["Host"],
            "Cluster": df["Cluster"] if "Cluster" in df.columns else "",
            "vCenter": df["_vcenter"],
            "Maintenance": _is_true(df, "in Maintenance Mode").map(lambda x: "Yes" if x else ""),
            "CPU %": _num(df, "CPU usage %"),
            "Memory %": _num(df, "Memory usage %"),
            "Memory GiB": _num(df, "# Memory") / 1024,
            "Cores": _num(df, "# Cores"),
            "vCPUs": _num(df, "# vCPUs"),
            "vCPU/core": _num(df, "vCPUs per Core"),
            "VMs": _num(df, "# VMs"),
            "ESXi": df["ESX Version"] if "ESX Version" in df.columns else "",
        }
    )
    return out.sort_values(["Memory %", "CPU %"], ascending=False)


def datastore_table(pack: Pack, include_ignored: bool = False) -> pd.DataFrame:
    df = pack.datastores
    if df.empty:
        return df
    if not include_ignored and "_ignored" in df.columns:
        df = df[~df["_ignored"]]
    out = pd.DataFrame(
        {
            "Datastore": df["Name"],
            "Cluster": df["Cluster name"] if "Cluster name" in df.columns else "",
            "vCenter": df["_vcenter"],
            "VMs": _num(df, "# VMs total"),
            "Capacity TiB": _num(df, "Capacity MiB") / 1024 / 1024,
            "Provisioned TiB": _num(df, "Provisioned MiB") / 1024 / 1024,
            "In use TiB": _num(df, "In Use MiB") / 1024 / 1024,
            "Free TiB": _num(df, "Free MiB") / 1024 / 1024,
            "Free %": _num(df, "Free %"),
        }
    )
    return out.sort_values("Free %", ascending=True)


def guest_fs_hotspots(pack: Pack, pct_limit: float, limit: int | None = None) -> pd.DataFrame:
    df = pack.guest_fs
    if df.empty:
        return df
    keep = (~df["_tiny"]) & (~df["_excluded_mount"]) & (_num(df, "Free %") <= pct_limit)
    hot = df[keep].copy()
    if hot.empty:
        return hot
    out = pd.DataFrame(
        {
            "VM": hot["VM"],
            "Disk": hot["Disk"],
            "Capacity GiB": _num(hot, "Capacity MiB") / 1024,
            "Consumed GiB": _num(hot, "Consumed MiB") / 1024,
            "Free GiB": _num(hot, "Free MiB") / 1024,
            "Free %": _num(hot, "Free %"),
            "vCenter": hot["_vcenter"],
        }
    )
    out = out.sort_values(["Free %", "Free GiB"])
    if limit is not None:
        return out.head(limit)
    return out


def kpis(pack: Pack) -> dict:
    info = pack.current
    hosts = pack.hosts
    thr: Thresholds = pack.config.thresholds
    templates = _is_true(info, "Template") if not info.empty else pd.Series(dtype=bool)
    powered = info["Powerstate"].astype(str).str.lower().eq("poweredon") if not info.empty else pd.Series(dtype=bool)
    if not info.empty:
        powered_on = int((powered & ~templates).sum()) if pack.config.exclude_templates_from_vm_count else int(powered.sum())
        total_vms = int((~templates).sum()) if pack.config.exclude_templates_from_vm_count else len(info)
        templates_n = int(templates.sum())
    else:
        powered_on = total_vms = templates_n = 0

    ht = host_table(pack)
    ds = datastore_table(pack)
    mem = pack.memory
    balloon = float(_num(mem, "Ballooned").sum()) / 1024 if not mem.empty else 0.0
    swapped = float(_num(mem, "Swapped").sum()) / 1024 if not mem.empty else 0.0
    mem_total = float(ht["Memory GiB"].sum()) if not ht.empty else 0.0
    mem_used = float((ht["Memory GiB"] * ht["Memory %"] / 100).sum()) if not ht.empty else 0.0
    cpu_w = float((ht["CPU %"] * ht["Cores"]).sum() / ht["Cores"].sum()) if not ht.empty and ht["Cores"].sum() else 0.0
    cpu_avg = float(ht["CPU %"].mean()) if not ht.empty else 0.0

    ds_cap = float(ds["Capacity TiB"].sum()) if not ds.empty else 0.0
    ds_used = float(ds["In use TiB"].sum()) if not ds.empty else 0.0
    ds_free_pct = (1 - ds_used / ds_cap) * 100 if ds_cap else 0.0

    return {
        "as_of": pack.as_of.isoformat(),
        "vcenters": pack.vcenters,
        "environments": pack.environments,
        "powered_on_vms": powered_on,
        "total_vms": total_vms,
        "templates": templates_n,
        "hosts": int(len(ht)),
        "hosts_maintenance": int((ht["Maintenance"] == "Yes").sum()) if not ht.empty else 0,
        "clusters": int(len(pack.clusters)),
        "memory_used_gib": round(mem_used, 1),
        "memory_total_gib": round(mem_total, 1),
        "memory_used_pct": round(100 * mem_used / mem_total, 1) if mem_total else 0.0,
        "cpu_weighted_pct": round(cpu_w, 1),
        "cpu_avg_pct": round(cpu_avg, 1),
        "balloon_gib": round(balloon, 2),
        "swapped_gib": round(swapped, 2),
        "datastore_capacity_tib": round(ds_cap, 2),
        "datastore_used_tib": round(ds_used, 2),
        "datastore_free_pct": round(ds_free_pct, 1),
        "hosts_mem_warn": int((ht["Memory %"] >= thr.host_mem_warn_pct).sum()) if not ht.empty else 0,
        "hosts_mem_crit": int((ht["Memory %"] >= thr.host_mem_crit_pct).sum()) if not ht.empty else 0,
        "hosts_cpu_warn": int((ht["CPU %"] >= thr.host_cpu_warn_pct).sum()) if not ht.empty else 0,
        "datastores_warn": int((ds["Free %"] < thr.datastore_free_warn_pct).sum()) if not ds.empty else 0,
        "datastores_crit": int((ds["Free %"] < thr.datastore_free_crit_pct).sum()) if not ds.empty else 0,
        "snapshot_vms": int(pack.snapshots["VM"].nunique()) if not pack.snapshots.empty else 0,
        "snapshot_rows": int(len(pack.snapshots)),
        "history_points": len(pack.history),
    }
