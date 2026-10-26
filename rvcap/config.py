from dataclasses import dataclass, field


@dataclass(frozen=True)
class Thresholds:
    host_mem_warn_pct: float = 45.0
    host_mem_crit_pct: float = 80.0
    host_cpu_warn_pct: float = 45.0
    host_cpu_crit_pct: float = 80.0
    datastore_free_warn_pct: float = 20.0
    datastore_free_crit_pct: float = 10.0
    datastore_underutil_pct: float = 90.0
    guest_fs_warn_pct: float = 20.0
    guest_fs_crit_pct: float = 10.0
    min_guest_fs_mib: float = 1024.0
    vcpu_per_core_warn: float = 4.0
    snapshot_age_warn_days: int = 7
    min_points_for_forecast: int = 4
    forecast_periods: int = 12


@dataclass(frozen=True)
class ReportConfig:
    title: str = "Capacity Report"
    host_table_limit: int = 40
    datastore_table_limit: int = 20
    guest_fs_table_limit: int = 25
    exclude_datastore_substrings: tuple[str, ...] = (
        "_local",
        "DEPOT",
        "ISO",
        "scratch",
    )
    exclude_guest_mounts: tuple[str, ...] = (
        "/boot",
        "/boot/efi",
        "/dev",
        "/sysroot",
        "/run",
    )
    exclude_templates_from_vm_count: bool = True
    thresholds: Thresholds = field(default_factory=Thresholds)


DEFAULT = ReportConfig()

SHEETS = (
    "vInfo",
    "vCPU",
    "vMemory",
    "vDisk",
    "vPartition",
    "vSnapshot",
    "vTools",
    "vSource",
    "vCluster",
    "vHost",
    "vDatastore",
    "vHealth",
    "vMetaData",
)
