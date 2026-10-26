"""Write eight fictional Friday RVTools workbooks into data/raw.

Forecast charts need 4 weekly snapshots. Eight weeks is enough for a visible
trend that does not flip the linear forecast through zero.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

FRIDAYS = [
    date(2026, 9, 4),
    date(2026, 9, 11),
    date(2026, 9, 18),
    date(2026, 9, 25),
    date(2026, 10, 2),
    date(2026, 10, 9),
    date(2026, 10, 16),
    date(2026, 10, 23),
]

HOSTS = [
    ("esx-e1.lab.example", "cluster-east", False, 32, 64),
    ("esx-e2.lab.example", "cluster-east", False, 32, 136),
    ("esx-e3.lab.example", "cluster-east", False, 32, 72),
    ("esx-w1.lab.example", "cluster-west", False, 32, 64),
    ("esx-w2.lab.example", "cluster-west", False, 32, 64),
    ("esx-w3.lab.example", "cluster-west", True, 32, 16),
]

MEM_PCT = {
    "esx-e1.lab.example": lambda i: 34 + i * 0.5,
    "esx-e2.lab.example": lambda i: 49 + i * 0.4,
    "esx-e3.lab.example": lambda i: 43 + i * 0.5,
    "esx-w1.lab.example": lambda i: 22 + i * 0.3,
    "esx-w2.lab.example": lambda i: 19 + i * 0.2,
    "esx-w3.lab.example": lambda i: 6,
}
CPU_PCT = {
    "esx-e1.lab.example": lambda i: 18 + i * 0.35,
    "esx-e2.lab.example": lambda i: 24 + i * 0.25,
    "esx-e3.lab.example": lambda i: 15 + i * 0.2,
    "esx-w1.lab.example": lambda i: 11 + i * 0.15,
    "esx-w2.lab.example": lambda i: 13 + i * 0.1,
    "esx-w3.lab.example": lambda i: 3,
}

VMS = (
    [f"app-web-{n:02d}" for n in range(1, 13)]
    + [f"app-api-{n:02d}" for n in range(1, 9)]
    + [f"app-db-{n:02d}" for n in range(1, 5)]
    + [f"app-batch-{n:02d}" for n in range(1, 7)]
    + [f"util-mon-{n:02d}" for n in range(1, 5)]
    + [f"lab-dev-{n:02d}" for n in range(1, 21)]
)
TEMPLATES = ["tpl-web", "tpl-db"]
HOST_GIB = 768


def _mib_from_tib(tib: float) -> float:
    return tib * 1024 * 1024


def _guest(vm: str, disk: str, cap_gib: float, free_pct: float) -> dict:
    cap = cap_gib * 1024
    free = cap * free_pct / 100
    used = cap - free
    return {
        "VM": vm,
        "Disk": disk,
        "Capacity MiB": cap,
        "Consumed MiB": used,
        "Free MiB": free,
        "Free %": free_pct,
    }


def build_week(index: int, snapshot: date) -> dict[str, pd.DataFrame]:
    powered_on = 46 + index
    active_hosts = [h for h in HOSTS if not h[2]]
    on_vms = VMS[:powered_on]
    off_vms = VMS[powered_on:]

    info_rows = []
    for n, vm in enumerate(on_vms):
        host = active_hosts[n % len(active_hosts)][0]
        cluster = active_hosts[n % len(active_hosts)][1]
        info_rows.append(
            {"VM": vm, "Powerstate": "poweredOn", "Template": False, "Host": host, "Cluster": cluster}
        )
    for vm in off_vms:
        info_rows.append(
            {"VM": vm, "Powerstate": "poweredOff", "Template": False, "Host": active_hosts[0][0], "Cluster": "cluster-east"}
        )
    for vm in TEMPLATES:
        info_rows.append(
            {"VM": vm, "Powerstate": "poweredOff", "Template": True, "Host": active_hosts[0][0], "Cluster": "cluster-east"}
        )

    per_host = {h[0]: 0 for h in HOSTS}
    for row in info_rows:
        if row["Powerstate"] == "poweredOn":
            per_host[row["Host"]] += 1

    host_rows = []
    for name, cluster, maint, cores, vcpus in HOSTS:
        host_rows.append(
            {
                "Host": name,
                "Cluster": cluster,
                "in Maintenance Mode": maint,
                "CPU usage %": round(CPU_PCT[name](index), 1),
                "Memory usage %": round(MEM_PCT[name](index), 1),
                "# Memory": HOST_GIB * 1024,
                "# Cores": cores,
                "# vCPUs": vcpus,
                "vCPUs per Core": round(vcpus / cores, 2),
                "# VMs": per_host[name],
                "ESX Version": "VMware ESXi 8.0.3 build-00000000",
            }
        )

    stores = [
        ("DS-EAST-01", "cluster-east", 8.0, 27 - index * 1.4, 18, False),
        ("DS-EAST-02", "cluster-east", 12.0, 48 - index * 0.3, 16, True),
        ("DS-WEST-01", "cluster-west", 10.0, 41 - index * 0.2, 14, False),
        ("esx-e1_local", "cluster-east", 0.4, 92, 0, False),
    ]
    ds_rows = []
    for name, cluster, tib, free_pct, vm_count, thin in stores:
        cap = _mib_from_tib(tib)
        free = cap * free_pct / 100
        used = cap - free
        prov = cap * 1.15 if thin else used * 1.05
        ds_rows.append(
            {
                "Name": name,
                "Cluster name": cluster,
                "# VMs total": vm_count,
                "Capacity MiB": cap,
                "Provisioned MiB": prov,
                "In Use MiB": used,
                "Free MiB": free,
                "Free %": round(free_pct, 1),
            }
        )

    db_free = max(6.0, 16 - index * 1.3)
    parts = [
        _guest("app-db-01", "/", 40, 31),
        _guest("app-db-01", "/var", 20, db_free),
        _guest("app-db-01", "/boot", 1, 40),
        _guest("app-web-04", "/var", 12, 8),
        _guest("app-api-02", "/var", 16, 14),
        _guest("app-web-01", "/", 30, 44),
        _guest("util-mon-01", "/var/tmp", 0.4, 5),
    ]

    snap_vms = ["app-db-01", "app-web-03", "app-api-01"] + [f"app-batch-{n:02d}" for n in range(1, min(index, 6) + 1)]
    snap_rows = [
        {"VM": vm, "Name": "before-change", "Date": datetime.combine(snapshot - timedelta(days=3 + index), datetime.min.time())}
        for vm in snap_vms
    ]

    tool_state = {"app-web-09": "toolsNotRunning", "lab-dev-02": "toolsNotInstalled"}
    tools = [{"VM": vm, "Tools": tool_state.get(vm, "toolsOk")} for vm in VMS + TEMPLATES]

    created = datetime(snapshot.year, snapshot.month, snapshot.day, 4, 0, 0)
    return {
        "vInfo": pd.DataFrame(info_rows),
        "vCPU": pd.DataFrame([{"VM": r["VM"], "CPUs": 2} for r in info_rows]),
        "vMemory": pd.DataFrame([{"VM": r["VM"], "Ballooned": 0, "Swapped": 0} for r in info_rows]),
        "vDisk": pd.DataFrame([{"VM": r["VM"], "Capacity MiB": 40960} for r in info_rows]),
        "vPartition": pd.DataFrame(parts),
        "vSnapshot": pd.DataFrame(snap_rows),
        "vTools": pd.DataFrame(tools),
        "vSource": pd.DataFrame([{"Name": "vc-lab01"}]),
        "vCluster": pd.DataFrame(
            [
                {"Name": "cluster-east", "HA enabled": True, "DRS enabled": True},
                {"Name": "cluster-west", "HA enabled": True, "DRS enabled": True},
            ]
        ),
        "vHost": pd.DataFrame(host_rows),
        "vDatastore": pd.DataFrame(ds_rows),
        "vHealth": pd.DataFrame([{"Message": "No sample health findings"}]),
        "vMetaData": pd.DataFrame(
            [
                {
                    "RVTools version": "4.3.1",
                    "Server": "vc-lab01.lab.example",
                    "xlsx creation datetime": created,
                }
            ]
        ),
    }


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for index, snapshot in enumerate(FRIDAYS):
        path = RAW / f"RVTools_Sample_vCenter_vc-lab01_{snapshot.isoformat()}.xlsx"
        sheets = build_week(index, snapshot)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, frame in sheets.items():
                frame.to_excel(writer, sheet_name=name, index=False)
        print(path.name)


if __name__ == "__main__":
    main()
