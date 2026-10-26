from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_raw() -> Path:
    return project_root() / "data" / "raw"


def warehouse_dir() -> Path:
    return project_root() / "data" / "warehouse"


def reports_monthly() -> Path:
    return project_root() / "reports" / "monthly"


def reports_weekly() -> Path:
    return project_root() / "reports" / "weekly"


def reports_tmp() -> Path:
    return project_root() / "reports" / ".tmp"


def logos_dir() -> Path:
    return project_root() / "assets" / "logos"


def logo_path(name: str) -> Path | None:
    folder = logos_dir()
    for filename in (f"{name}.png", f"{name}.jpg", f"{name}.jpeg", f"{name}.webp"):
        path = folder / filename
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def ensure_dirs() -> None:
    for path in (data_raw(), warehouse_dir(), reports_monthly(), reports_weekly(), reports_tmp(), logos_dir()):
        path.mkdir(parents=True, exist_ok=True)
